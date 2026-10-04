"""Verify the published inventory without depending on UCAgent or an EDA tool."""
import argparse
import hashlib
import json
from pathlib import Path


def verify(root):
    """Reject missing, changed or escaping inventory entries before running hardware tools."""
    root = root.resolve()
    manifest = json.loads((root / 'DELIVERY_SHA256.json').read_text(encoding='utf-8'))
    failures = []
    for name, digest in manifest['files'].items():
        path = (root / name).resolve()
        if root not in path.parents or not path.is_file():
            failures.append(name + ': 文件缺失或路径越界')
        elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            failures.append(name + ': SHA-256 不匹配')
    if failures:
        raise RuntimeError('\n'.join(failures))
    return len(manifest['files'])


def main():
    parser = argparse.ArgumentParser(description='校验完整交付包的文件哈希')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print('校验通过：%d 个文件，SHA-256 全部匹配。' % verify(args.root))


if __name__ == '__main__':
    main()

