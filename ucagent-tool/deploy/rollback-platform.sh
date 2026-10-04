#!/usr/bin/env bash
set -euo pipefail

# Atomically switch to the previous or an explicitly named validated release.
if [[ "${EUID}" -ne 0 ]]; then
  echo "rollback-platform.sh must run as root" >&2
  exit 2
fi
if [[ "$#" -gt 1 ]]; then
  echo "usage: rollback-platform.sh [release-id]" >&2
  exit 2
fi

install_root="${UCAGENT_INSTALL_ROOT:-/home/ucagent-lab}"
systemctl_bin="${UCAGENT_SYSTEMCTL:-systemctl}"
service_name="ucagent-platform.service"
if [[ "${install_root}" != /* ]]; then
  echo "UCAGENT_INSTALL_ROOT must be an absolute path" >&2
  exit 2
fi
install_root="$(readlink -m -- "${install_root}")"
release_root="$(readlink -m -- "${install_root}/releases")"
current_link="${install_root}/current"
previous_link="${install_root}/previous"

if [[ ! -L "${current_link}" ]]; then
  echo "current release symlink is missing" >&2
  exit 3
fi
old_current="$(readlink -f -- "${current_link}" || true)"
case "${old_current}" in
  "${release_root}/"*) [[ -d "${old_current}" ]] ;;
  *)
    echo "current symlink does not target a managed release" >&2
    exit 3
    ;;
esac

if [[ "$#" -eq 1 ]]; then
  release_id="$1"
  if [[ ! "${release_id}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]]; then
    echo "release id is not filesystem-safe" >&2
    exit 2
  fi
  rollback_target="$(readlink -f -- "${release_root}/${release_id}" || true)"
else
  if [[ ! -L "${previous_link}" ]]; then
    echo "previous release symlink is missing" >&2
    exit 3
  fi
  rollback_target="$(readlink -f -- "${previous_link}" || true)"
fi
case "${rollback_target}" in
  "${release_root}/"*) [[ -d "${rollback_target}" ]] ;;
  *)
    echo "rollback target is not a managed release" >&2
    exit 3
    ;;
esac
if [[ ! -x "${rollback_target}/venv/bin/python" || \
      ! -f "${rollback_target}/release.json" ]]; then
  echo "rollback target is incomplete" >&2
  exit 3
fi
if [[ "${rollback_target}" == "${old_current}" ]]; then
  echo "requested release is already active"
  exit 0
fi

# Replace a release symlink through a same-directory atomic rename.
atomic_link() {
  local target="$1"
  local link="$2"
  local candidate="${link}.new.$$"
  rm -f -- "${candidate}"
  ln -s -- "${target}" "${candidate}"
  mv -Tf -- "${candidate}" "${link}"
}

atomic_link "${rollback_target}" "${current_link}"
service_ready=0
active_checks=0
if "${systemctl_bin}" restart "${service_name}"; then
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
  atomic_link "${old_current}" "${current_link}"
  "${systemctl_bin}" restart "${service_name}" || true
  echo "rollback target failed to stay active; restored original release" >&2
  exit 4
fi
atomic_link "${old_current}" "${previous_link}"
echo "UCAgent platform rolled back to $(basename -- "${rollback_target}")"
