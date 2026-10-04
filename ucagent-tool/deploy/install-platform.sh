#!/usr/bin/env bash
set -euo pipefail

# Install an already-built, local-wheel release and atomically make it current.
if [[ "${EUID}" -ne 0 ]]; then
  echo "install-platform.sh must run as root" >&2
  exit 2
fi
if [[ "$#" -ne 2 ]]; then
  echo "usage: install-platform.sh <absolute-release-source> <release-id>" >&2
  exit 2
fi

release_source="$1"
release_id="$2"
install_root="${UCAGENT_INSTALL_ROOT:-/home/ucagent-lab}"
base_venv="${UCAGENT_BASE_VENV:-${install_root}/venv}"
systemd_unit_dir="${UCAGENT_SYSTEMD_UNIT_DIR:-/etc/systemd/system}"
systemctl_bin="${UCAGENT_SYSTEMCTL:-systemctl}"
minimum_free_kb="${UCAGENT_MINIMUM_FREE_KB:-10485760}"
service_name="ucagent-platform.service"
release_root="${install_root}/releases"
release_target="${release_root}/${release_id}"
current_link="${install_root}/current"
previous_link="${install_root}/previous"
unit_target="${systemd_unit_dir}/${service_name}"
staging_target=""
unit_backup=""
unit_candidate=""
published_release=""
activation_succeeded=0

if [[ "${release_source}" != /* || ! -d "${release_source}" ]]; then
  echo "release source must be an existing absolute directory" >&2
  exit 2
fi
if [[ "${install_root}" != /* || "${base_venv}" != /* || "${systemd_unit_dir}" != /* ]]; then
  echo "deployment roots must be absolute paths" >&2
  exit 2
fi
if [[ ! "${release_id}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]]; then
  echo "release id is not filesystem-safe" >&2
  exit 2
fi
if [[ ! "${minimum_free_kb}" =~ ^[0-9]+$ || "${minimum_free_kb}" -lt 1 ]]; then
  echo "UCAGENT_MINIMUM_FREE_KB must be a positive integer" >&2
  exit 2
fi
if [[ ! -f "${release_source}/deploy/install_release_wheel.py" || \
      ! -f "${release_source}/deploy/ucagent-platform.service" || \
      ! -f "${release_source}/deploy/toolchains.synopsys-o2018.example.yaml" ]]; then
  echo "release source is missing required deployment files" >&2
  exit 2
fi
if [[ ! -x "${base_venv}/bin/python" ]]; then
  echo "validated base virtual environment is missing: ${base_venv}" >&2
  exit 4
fi

release_source="$(readlink -f -- "${release_source}")"
install_root="$(readlink -m -- "${install_root}")"
base_venv="$(readlink -f -- "${base_venv}")"
systemd_unit_dir="$(readlink -m -- "${systemd_unit_dir}")"
release_root="${install_root}/releases"
release_target="${release_root}/${release_id}"
current_link="${install_root}/current"
previous_link="${install_root}/previous"
unit_target="${systemd_unit_dir}/${service_name}"
case "${release_root}/" in
  "${release_source}/"*)
    echo "release source cannot contain the destination release directory" >&2
    exit 2
    ;;
esac

# Remove only the unpublished staging directory after a failed preparation.
cleanup_staging() {
  local status="$?"
  if [[ -n "${staging_target}" && -d "${staging_target}" ]]; then
    case "${staging_target}" in
      "${release_root}/.${release_id}.staging."*) rm -rf -- "${staging_target}" ;;
      *) echo "refusing to remove unexpected staging path" >&2 ;;
    esac
  fi
  if [[ -n "${unit_backup}" && -f "${unit_backup}" ]]; then
    case "${unit_backup}" in
      "${install_root}/tmp/.${service_name}.backup."*) rm -f -- "${unit_backup}" ;;
      *) echo "refusing to remove unexpected unit backup" >&2 ;;
    esac
  fi
  if [[ -n "${unit_candidate}" && -f "${unit_candidate}" ]]; then
    case "${unit_candidate}" in
      "${unit_target}.new."*) rm -f -- "${unit_candidate}" ;;
      *) echo "refusing to remove unexpected unit candidate" >&2 ;;
    esac
  fi
  if [[ "${status}" -ne 0 && "${activation_succeeded}" -eq 0 && \
        "${published_release}" == "${release_target}" && -d "${published_release}" ]]; then
    current_target="$(readlink -f -- "${current_link}" 2>/dev/null || true)"
    if [[ "${current_target}" != "${published_release}" ]]; then
      rm -rf -- "${published_release}"
    fi
  fi
  exit "${status}"
}
trap cleanup_staging EXIT

if ! getent group ucagent >/dev/null 2>&1; then
  groupadd --system ucagent
fi
if ! id -u ucagent >/dev/null 2>&1; then
  useradd --create-home --home-dir "${install_root}/home" --shell /bin/bash --gid ucagent ucagent
elif [[ "$(id -u ucagent)" -eq 0 ]]; then
  echo "the ucagent service account must not be root" >&2
  exit 4
fi

install -d -o root -g root -m 0755 "${install_root}" "${release_root}" "${systemd_unit_dir}"
install -d -o ucagent -g ucagent -m 0700 \
  "${install_root}/state" "${install_root}/artifacts" "${install_root}/tmp" \
  "${install_root}/home"
install -d -o ucagent -g ucagent -m 0750 "${install_root}/workspaces"
install -d -o root -g ucagent -m 0750 "${install_root}/config"

available_kb="$(df -Pk "${install_root}" 2>/dev/null | awk 'NR==2 {print $4}')"
if [[ -z "${available_kb}" || "${available_kb}" -lt "${minimum_free_kb}" ]]; then
  echo "insufficient free space under the deployment filesystem" >&2
  exit 3
fi
if [[ -e "${release_target}" || -L "${release_target}" ]]; then
  echo "release already exists: ${release_target}" >&2
  exit 2
fi

PYTHONNOUSERSITE=1 "${base_venv}/bin/python" -c \
  'import sys; raise SystemExit(sys.version_info < (3, 11))'
PYTHONNOUSERSITE=1 "${base_venv}/bin/python" -c \
  'import fastapi, multipart, psutil, pydantic, uvicorn, yaml'

staging_target="${release_root}/.${release_id}.staging.$$"
if [[ -e "${staging_target}" || -L "${staging_target}" ]]; then
  echo "staging path already exists" >&2
  exit 2
fi
install -d -o root -g root -m 0755 "${staging_target}"
cp -a -- "${release_source}/." "${staging_target}/"
if [[ -e "${staging_target}/venv" || -L "${staging_target}/venv" ]]; then
  echo "release source must not contain a virtual environment" >&2
  exit 4
fi
install -d -o root -g root -m 0755 "${staging_target}/venv"
if cp --help 2>/dev/null | grep -q -- '--reflink'; then
  cp -a --reflink=auto -- "${base_venv}/." "${staging_target}/venv/"
else
  cp -a -- "${base_venv}/." "${staging_target}/venv/"
fi

wheels=()
while IFS= read -r wheel; do
  wheels+=("${wheel}")
done < <(find "${staging_target}" -maxdepth 3 -type f -name 'ucagent-*.whl' -print)
if [[ "${#wheels[@]}" -ne 1 ]]; then
  echo "release must contain exactly one prebuilt ucagent-*.whl within three levels" >&2
  exit 4
fi

release_python="${staging_target}/venv/bin/python"
if [[ ! -x "${release_python}" ]]; then
  echo "cloned release virtual environment has no executable Python" >&2
  exit 4
fi
export TMPDIR="${install_root}/tmp"
export TMP="${install_root}/tmp"
export TEMP="${install_root}/tmp"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1
"${release_python}" "${staging_target}/deploy/install_release_wheel.py" \
  "${wheels[0]}" --release-id "${release_id}" \
  --receipt "${staging_target}/release.json"
"${release_python}" -c \
  'from ucagent.server.platform_main import create_platform_app; import fastapi, pydantic, uvicorn, yaml'
"${release_python}" -m ucagent.server.platform_main --help >/dev/null

chown -R root:ucagent "${staging_target}"
chmod -R u=rwX,g=rX,o= "${staging_target}"
runuser -u ucagent -- env -i \
  HOME="${install_root}/home" PATH="/usr/bin:/bin" TMPDIR="${install_root}/tmp" \
  TMP="${install_root}/tmp" TEMP="${install_root}/tmp" PYTHONDONTWRITEBYTECODE=1 \
  PYTHONNOUSERSITE=1 "${release_python}" -c \
  'from ucagent.server.platform_main import create_platform_app'

available_kb="$(df -Pk "${install_root}" 2>/dev/null | awk 'NR==2 {print $4}')"
if [[ -z "${available_kb}" || "${available_kb}" -lt "${minimum_free_kb}" ]]; then
  echo "release preparation crossed the minimum free-space threshold" >&2
  exit 3
fi

if [[ ! -f "${install_root}/config/toolchains.yaml" ]]; then
  install -o root -g ucagent -m 0640 \
    "${staging_target}/deploy/toolchains.synopsys-o2018.example.yaml" \
    "${install_root}/config/toolchains.yaml"
fi
chown root:ucagent "${install_root}/config/toolchains.yaml"
chmod 0640 "${install_root}/config/toolchains.yaml"
"${release_python}" -c \
  'import pathlib, sys, yaml; data=yaml.safe_load(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")); assert isinstance(data, dict) and isinstance(data.get("profiles"), dict)' \
  "${install_root}/config/toolchains.yaml"

old_current=""
if [[ -L "${current_link}" ]]; then
  old_current="$(readlink -f -- "${current_link}" || true)"
  case "${old_current}" in
    "${release_root}/"*) [[ -d "${old_current}" ]] || old_current="" ;;
    *)
      echo "current symlink does not target a managed release" >&2
      exit 5
      ;;
  esac
elif [[ -e "${current_link}" ]]; then
  echo "current must be a symlink" >&2
  exit 5
fi

mv -- "${staging_target}" "${release_target}"
staging_target=""
published_release="${release_target}"

unit_backup="${install_root}/tmp/.${service_name}.backup.$$"
unit_candidate="${unit_target}.new.$$"
had_unit=0
if [[ -f "${unit_target}" ]]; then
  cp -a -- "${unit_target}" "${unit_backup}"
  had_unit=1
fi
was_enabled=0
was_active=0
if "${systemctl_bin}" is-enabled --quiet "${service_name}" >/dev/null 2>&1; then
  was_enabled=1
fi
if "${systemctl_bin}" is-active --quiet "${service_name}" >/dev/null 2>&1; then
  was_active=1
fi

# Replace a symlink through a same-directory rename so readers never see a partial target.
atomic_link() {
  local target="$1"
  local link="$2"
  local candidate="${link}.new.$$"
  rm -f -- "${candidate}"
  ln -s -- "${target}" "${candidate}"
  mv -Tf -- "${candidate}" "${link}"
}

install -o root -g root -m 0644 \
  "${release_target}/deploy/ucagent-platform.service" "${unit_candidate}"
mv -f -- "${unit_candidate}" "${unit_target}"
unit_candidate=""
atomic_link "${release_target}" "${current_link}"

service_ready=0
active_checks=0
if "${systemctl_bin}" daemon-reload && \
   "${systemctl_bin}" enable "${service_name}" >/dev/null && \
   "${systemctl_bin}" restart "${service_name}"; then
  for _ in {1..20}; do
    if "${systemctl_bin}" is-active --quiet "${service_name}"; then
      active_checks=$((active_checks + 1))
      if [[ "${active_checks}" -ge 3 ]]; then
        service_ready=1
        break
      fi
    else
      active_checks=0
    fi
    sleep 1
  done
fi

if [[ "${service_ready}" -ne 1 ]]; then
  echo "new release failed to become active; restoring the previous service state" >&2
  if [[ -n "${old_current}" ]]; then
    atomic_link "${old_current}" "${current_link}"
  elif [[ -L "${current_link}" ]]; then
    rm -f -- "${current_link}"
  fi
  if [[ "${had_unit}" -eq 1 ]]; then
    install -o root -g root -m 0644 "${unit_backup}" "${unit_candidate}"
    mv -f -- "${unit_candidate}" "${unit_target}"
    unit_candidate=""
  else
    rm -f -- "${unit_target}"
  fi
  "${systemctl_bin}" daemon-reload || true
  if [[ "${was_enabled}" -eq 1 ]]; then
    "${systemctl_bin}" enable "${service_name}" >/dev/null 2>&1 || true
  else
    "${systemctl_bin}" disable "${service_name}" >/dev/null 2>&1 || true
  fi
  if [[ "${was_active}" -eq 1 && -n "${old_current}" ]]; then
    "${systemctl_bin}" restart "${service_name}" || true
  else
    "${systemctl_bin}" stop "${service_name}" || true
  fi
  rm -f -- "${unit_backup}"
  unit_backup=""
  exit 6
fi

activation_succeeded=1
if [[ -n "${old_current}" && "${old_current}" != "${release_target}" ]]; then
  atomic_link "${old_current}" "${previous_link}"
fi
rm -f -- "${unit_backup}"
unit_backup=""
echo "UCAgent platform release ${release_id} is active"
