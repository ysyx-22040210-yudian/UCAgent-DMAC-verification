"""Re-run immutable DMAC SBY inputs and actual simulation in independent directories."""
import argparse
import datetime
import json
from pathlib import Path
import shutil
import os
import signal
import subprocess
import sys
import uuid

from check_delivery import verify

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'verification/reports'


def call(argv, cwd, log, timeout):
    """Retain command and combined output; never turn an exception into a tool success."""
    (cwd / (log + '.command.json')).write_text(json.dumps(argv, ensure_ascii=False), encoding='utf-8')
    with (cwd / log).open('w', encoding='utf-8') as stream:
        process = subprocess.Popen(argv, cwd=str(cwd), stdout=stream, stderr=subprocess.STDOUT,
                                   start_new_session=os.name == 'posix')
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == 'posix':
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait()
            raise


def sby_case(case, target, executable, timeout):
    """Use the exact saved configuration and inputs, with separate result interpretation."""
    cwd = target / case
    cwd.mkdir()
    if case.startswith('guided_'):
        mode = case.split('_', 1)[1]
        ids = {'bmc': 'sby-872c6e8dd8bc4642988787232188507c',
               'cover': 'sby-36b62d07a5ac4849952f6b3aca922448'}
        inputs = REPORTS / 'guided/tests/sby_runs' / ids[mode] / 'inputs'
        config = REPORTS / 'guided/tests' / (mode + '.sby')
    else:
        inputs = REPORTS / 'evidence' / case / 'inputs'
        config = REPORTS / 'evidence' / case / 'control/run.sby'
        mode = 'bmc' if case.startswith('fault_') else ('cover' if 'cover' in case else 'prove')
    shutil.copytree(inputs, cwd / 'inputs')
    shutil.copy2(config, cwd / 'run.sby')
    code = call([executable, '-f', '-d', 'proof', 'run.sby'], cwd, 'console.log', timeout)
    status_path = cwd / 'proof/status'
    status = status_path.read_text(encoding='utf-8').split()[0] if status_path.is_file() else 'MISSING'
    log_path = cwd / 'proof/logfile.txt'
    text = log_path.read_text(encoding='utf-8') if log_path.is_file() else ''
    expected = False
    conclusion = '执行失败或无有效结论'
    if case.startswith('fault_'):
        expected = code == 2 and status == 'FAIL' and 'Assert failed' in text and bool(list((cwd / 'proof').rglob('trace*.vcd')))
        if expected:
            conclusion = '故障对照有效：检测到预期断言反例'
    elif case == 'guided_cover':
        expected = code in (0, 2) and status in ('PASS', 'FAIL') and bool(list((cwd / 'proof').rglob('trace*.vcd')))
        if expected:
            conclusion = '覆盖全部命中' if status == 'PASS' else '覆盖仍有未命中项，结论未决'
    else:
        expected = code == 0 and status == 'PASS'
        if expected:
            conclusion = '有界深度内无反例，仍未决' if mode == 'bmc' else ('覆盖全部命中' if mode == 'cover' else '本参数实例安全证明通过')
    return dict(case=case, mode=mode, exit_code=code, tool_status=status,
                conclusion=conclusion, expected_observation=expected)


def replay_cases(target, iverilog, vvp, timeout):
    """Compile original or deliberately faulty RTL; require all 19 actual replay outcomes."""
    rows = []
    histories = json.loads((REPORTS / 'replay/results.json').read_text(encoding='utf-8'))
    if len(histories) != 19:
        raise RuntimeError('历史回放清单不是 19 项')
    for item in histories:
        case = item['case']
        cwd = target / ('replay_' + case)
        cwd.mkdir()
        rtl = REPORTS / 'evidence' / case[:-7] / 'inputs/rtl' if case.endswith('_mutant') else ROOT / 'dmac/rtl'
        for name in ('dmac.sv', 'dmac_fifo.sv'):
            shutil.copy2(rtl / name, cwd / name)
        shutil.copy2(REPORTS / 'replay' / case / 'replay_tb.sv', cwd / 'replay_tb.sv')
        code = call([iverilog, '-g2012', '-DSYNTHESIS', '-s', 'replay_tb', '-o',
                     'sim', 'dmac.sv', 'dmac_fifo.sv', 'replay_tb.sv'], cwd, 'compile.log', timeout)
        run_code = call([vvp, 'sim'], cwd, 'run.log', timeout) if code == 0 else None
        expected_code = 1 if case.endswith('_baseline') else 0
        log = (cwd / 'run.log').read_text(encoding='utf-8') if run_code is not None else ''
        marker = 'VECTOR_MISMATCH' if expected_code else 'PASS replay'
        expected = code == 0 and run_code == expected_code and marker in log
        rows.append(dict(case=case, compile_code=code, run_code=run_code,
                         expected_run_code=expected_code, expected_observation=expected))
    return rows


def main():
    """A successful runner means expected evidence was observed, not that all DUT checks passed."""
    parser = argparse.ArgumentParser(description='DMAC 可搬运 SBY 与回放入口（不调用模型）')
    parser.add_argument('--suite', choices=['smoke', 'native', 'guided', 'replay', 'all'], default='smoke')
    parser.add_argument('--runtime-bundle', type=Path, help='完整离线包目录；自动使用包内工具，无需系统安装 SBY')
    parser.add_argument('--sby', help='仅源码模式下覆盖工具路径')
    parser.add_argument('--iverilog', help='仅源码模式下覆盖工具路径')
    parser.add_argument('--vvp', help='仅源码模式下覆盖工具路径')
    parser.add_argument('--timeout', type=int, default=300, help='每个工具进程的时间上限（秒）')
    parser.add_argument('--output-root', type=Path, default=ROOT / 'results')
    args = parser.parse_args()
    verify(ROOT)
    if args.timeout <= 0:
        parser.error('--timeout 必须为正整数')
    bundled = args.runtime_bundle or (ROOT.parent if (ROOT.parent / 'bundle.json').is_file() else None)
    if bundled:
        bundled = bundled.resolve(strict=True)
        metadata = json.loads((bundled / 'bundle.json').read_text(encoding='utf-8'))
        if metadata.get('platform') != 'linux-x86_64':
            parser.error('离线运行时必须为 Linux x86_64')
    def tool(name):
        return str(bundled / 'oss-cad-suite/bin' / name) if bundled else getattr(args, name) or name
    tools = {} if args.suite == 'replay' else {'sby': tool('sby')}
    if args.suite in ('smoke', 'replay', 'all'):
        tools.update(iverilog=tool('iverilog'), vvp=tool('vvp'))
    for key, value in list(tools.items()):
        resolved = shutil.which(value)
        if not resolved:
            parser.error('缺少工具 %s：%s；请配置 PATH 或对应启动参数' % (key, value))
        tools[key] = resolved
    if bundled:
        os.environ['PATH'] = str(bundled / 'oss-cad-suite/bin') + ':/usr/bin:/bin'
    target = args.output_root.resolve() / (datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    target.mkdir(parents=True, exist_ok=False)
    result = dict(suite=args.suite, tool_paths=tools, verification_status='尚未运行', runs=[], replay=[])
    exit_code = 1
    try:
        versions = {}
        for name, executable in tools.items():
            versions[name] = call([executable, '--version' if name == 'sby' else '-V'],
                                  target, name + '-version.log', min(args.timeout, 15))
        result['version_commands'] = versions
        cases = []
        if args.suite == 'smoke':
            cases = ['accepted_prove_a32_l1_f4', 'fault_address_step']
        elif args.suite in ('native', 'all'):
            cases = sorted(p.name for p in (REPORTS / 'evidence').iterdir() if not p.name.startswith('joint_'))
        if args.suite in ('guided', 'all'):
            cases += ['guided_bmc', 'guided_cover']
        for case in cases:
            row = sby_case(case, target, tools['sby'], args.timeout)
            result['runs'].append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
        if args.suite in ('smoke', 'replay', 'all'):
            result['replay'] = replay_cases(target, tools['iverilog'], tools['vvp'], args.timeout)
        checks = result['runs'] + result['replay']
        exit_code = 0 if checks and all(r['expected_observation'] for r in checks) else 1
        result['verification_status'] = '按预期产生证据；设计总体验证结论仍未决' if exit_code == 0 else '存在执行错误或结果不符合预期'
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        result['error'] = str(error)
        result['verification_status'] = '执行错误或超时，无通过结论'
    finally:
        (target / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('结果目录：' + str(target), flush=True)
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
