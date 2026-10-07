"""Build an offline Linux x86_64 delivery from a verified complete OSS runtime bundle."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipapp


def inventory(root):
    """Pin regular file bytes and link targets without dereferencing packaged symlinks."""
    files, links = {}, {}
    for path in sorted(root.rglob('*')):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            path.resolve(strict=True).relative_to(root)
            links[name] = os.readlink(path)
        elif path.is_file() and path.suffix != '.pyc' and name not in ('SHA256SUMS.json', 'SYMLINKS.json'):
            with path.open('rb') as stream:
                files[name] = hashlib.file_digest(stream, 'sha256').hexdigest()
    (root / 'SYMLINKS.json').write_text(json.dumps(links, indent=2, sort_keys=True) + '\n')
    files['SYMLINKS.json'] = hashlib.sha256((root / 'SYMLINKS.json').read_bytes()).hexdigest()
    (root / 'SHA256SUMS.json').write_text(json.dumps(files, indent=2, sort_keys=True) + '\n')


def build(project, runtime, output, dependencies=None):
    """Reuse verified runtime bytes; include current code, projects, scripts and all dependencies."""
    project, runtime = project.resolve(strict=True), runtime.resolve(strict=True)
    output = output.resolve()
    if output.exists():
        raise FileExistsError('Refusing to replace an existing offline release')
    if sys.platform != 'linux':
        raise ValueError('Build the Linux release on Linux to preserve modes and symlinks')
    spec = importlib.util.spec_from_file_location('verify_base', runtime / 'Verify-Bundle.py')
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    checked = verifier.verify(runtime)
    if not checked['passed']:
        raise ValueError('Base runtime integrity failed: ' + json.dumps(checked))
    old = json.loads((runtime / 'bundle.json').read_text())
    if old.get('platform') != 'linux-x86_64':
        raise ValueError('A Linux x86_64 runtime is required')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.dmac-offline-build-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'release'
        stage.mkdir()
        ignore = shutil.ignore_patterns('.git', '__pycache__', '*.pyc', '.pytest_cache', 'results', 'dist', '*.egg-info')
        for name in ('oss-cad-suite', 'fonts'):
            shutil.copytree(runtime / name, stage / name, symlinks=True, ignore=ignore)
        dep_source = dependencies.resolve(strict=True) if dependencies else runtime / 'backend-deps'
        shutil.copytree(dep_source, stage / 'backend-deps', symlinks=True, ignore=shutil.ignore_patterns(
            '__pycache__', '*.pyc', '__editable__*', '_virtualenv*', 'ucagent', 'ucagent-*.dist-info', 'ucagent-*.egg-info'))
        # Editable installs and virtualenv .pth files may carry source-machine paths.
        for path in (stage / 'backend-deps').glob('*.pth'):
            if any(line.strip() and not line.startswith(('#', 'import ')) and Path(line.strip()).is_absolute()
                   for line in path.read_text().splitlines()):
                raise ValueError('Absolute dependency search path: ' + path.name)
        shutil.copytree(project, stage / 'project', symlinks=True, ignore=ignore)
        backend = stage / 'backend'
        backend.mkdir()
        shutil.copytree(project / 'ucagent-tool/ucagent', backend / 'ucagent', ignore=ignore)
        desktop = stage / '.desktop-build'
        desktop.mkdir()
        shutil.copytree(project / 'ucagent-tool/desktop/ucagent_tk', desktop / 'ucagent_tk', ignore=ignore)
        shutil.copy2(project / 'ucagent-tool/desktop/ucagent_app.py', desktop / '__main__.py')
        zipapp.create_archive(desktop, target=stage / 'UCAgent-Desktop.pyz', compressed=True)
        shutil.rmtree(desktop)
        examples = stage / 'examples'
        examples.mkdir()
        for name in ('sby_counter', 'sby_counter_bug'):
            shutil.copytree(runtime / 'examples' / name, examples / name, ignore=ignore)
        shutil.copytree(project / 'projects/DMAC-native', examples / 'DMAC-native', ignore=ignore)
        main = examples / 'DMAC-main'
        snapshot = project / 'verification/reports/guided/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/inputs'
        shutil.copytree(snapshot, main)
        import yaml
        config = yaml.safe_load((project / 'projects/DMAC-guided/.ucagent/project.yaml').read_text())
        config['design'].update(top='dmac_wrapper', sources=['dmac/rtl/dmac_fifo.sv', 'dmac/rtl/dmac.sv',
                              'formal_out/tests/dmac_checker.sv', 'formal_out/tests/dmac_wrapper.sv'])
        config['toolchain'] = 'bundled_sby'
        (main / '.ucagent').mkdir(exist_ok=True)
        (main / '.ucagent/project.yaml').write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
        for name in ('DMAC-native', 'sby_counter', 'sby_counter_bug'):
            path = examples / name / '.ucagent/project.yaml'
            entry = yaml.safe_load(path.read_text())
            entry['toolchain'] = 'bundled_sby'
            path.write_text(yaml.safe_dump(entry, allow_unicode=True, sort_keys=False))
        for name in ('Start-UCAgent', 'Run-DMAC', 'Check-Package'):
            shutil.copy2(project / 'offline' / name, stage / name)
            (stage / name).chmod(0o755)
        shutil.copy2(project / 'offline/README.md', stage / 'README.md')
        for name in ('Verify-Bundle.py', 'runtime.lock.json', 'runtime-support.lock.json', 'ui-assets.lock.json', 'THIRD_PARTY.md'):
            shutil.copy2(runtime / name, stage / name)
        shutil.copy2(project / 'NOTICE.md', stage / 'NOTICE.md')
        python = stage / 'oss-cad-suite/bin/tabbypy3'
        env = {k: v for k, v in os.environ.items() if not k.startswith(('PYTHON', 'LD_')) and 'LICENSE' not in k}
        env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1',
                   PYTHONPATH=str(backend) + ':' + str(stage / 'backend-deps'))
        subprocess.run([str(python), '-c', 'import tkinter; from ucagent.server.portable_main import main; print("Bundled backend/Tk imports OK")'], env=env, check=True, timeout=30)
        versions = {}
        for name, flag in [('sby', '--version'), ('yosys', '-V'), ('z3', '--version'), ('iverilog', '-V'), ('vvp', '-V')]:
            p = subprocess.run([str(stage / 'oss-cad-suite/bin' / name), flag], env=env, capture_output=True, text=True, check=True, timeout=30)
            versions[name] = (p.stdout or p.stderr).strip().splitlines()[0]
        versions['yosys-smtbmc'] = 'bundled with ' + versions['yosys']
        dep_list = subprocess.check_output([str(python), '-c', 'import importlib.metadata as m,json;print(json.dumps({d.metadata["Name"]:d.version for d in m.distributions(path=["backend-deps"])}))'], cwd=stage, env=env, text=True)
        release = dict(schema_version=1, version='DMAC-20261007', platform='linux-x86_64', runtime=old['runtime'],
                       runtime_support=old['runtime_support'], runtime_modifications=old.get('runtime_modifications', []),
                       tools=versions, projects=['sby_counter', 'sby_counter_bug', 'DMAC-native', 'DMAC-main'],
                       python_dependencies=json.loads(dep_list), source_sha256=json.loads((project / 'DELIVERY_SHA256.json').read_text())['files'],
                       base_runtime_inventory_sha256=hashlib.sha256((runtime / 'SHA256SUMS.json').read_bytes()).hexdigest())
        (stage / 'bundle.json').write_text(json.dumps(release, indent=2, ensure_ascii=False) + '\n')
        inventory(stage)
        os.replace(stage, output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--runtime-bundle', type=Path, required=True)
    parser.add_argument('--backend-deps', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(build(args.project, args.runtime_bundle, args.output, args.backend_deps), flush=True)
