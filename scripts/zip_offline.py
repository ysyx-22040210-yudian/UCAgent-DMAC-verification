"""Convert a verified Linux offline release into a ZIP with regular files only."""

import argparse
import hashlib
import json
import posixpath
import shutil
import stat
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path


def digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def zip_info(member, name=None, size=None):
    stamp = time.gmtime(max(member.mtime, 315532800))[:6]
    info = zipfile.ZipInfo(name or member.name, stamp)
    info.create_system = 3
    mode = stat.S_IFDIR if member.isdir() else stat.S_IFREG
    info.external_attr = ((mode | member.mode) << 16) | (0x10 if member.isdir() else 0x20)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.file_size = member.size if size is None else size
    return info


def convert(archive, output, expected):
    if output.exists():
        raise ValueError("Output already exists: " + str(output))
    source_digest = digest_file(archive)
    if source_digest != expected:
        raise ValueError("Source archive SHA-256 mismatch")
    output.parent.mkdir(parents=True, exist_ok=True)
    pending = output.with_suffix(output.suffix + ".partial")
    if pending.exists():
        raise ValueError("Partial output already exists: " + str(pending))
    members, links, replacements, skipped = {}, {}, {}, {}
    root = None
    with zipfile.ZipFile(pending, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as package:
        with tarfile.open(archive, "r|gz") as source:
            for member in source:
                name = member.name.rstrip("/")
                if name.startswith("/") or ".." in name.split("/") or "\\" in name:
                    raise ValueError("Unsafe archive path: " + name)
                current_root = name.split("/", 1)[0]
                root = root or current_root
                if root != current_root or name in members:
                    raise ValueError("Unexpected root or duplicate path: " + name)
                members[name] = member
                relative = name[len(root) + 1:]
                if member.isdir():
                    package.writestr(zip_info(member, name + "/", 0), b"")
                elif member.issym():
                    target = posixpath.normpath(posixpath.join(posixpath.dirname(name), member.linkname))
                    if member.linkname.startswith("/") or not target.startswith(root + "/"):
                        raise ValueError("Link leaves package: " + name)
                    links[name] = target
                elif member.isfile():
                    stream = source.extractfile(member)
                    if relative in ("SHA256SUMS.json", "SYMLINKS.json"):
                        skipped[relative] = (member, stream.read())
                    elif relative == "README.md":
                        data = stream.read().replace(
                            b"tar -xzf UCAgent-DMAC-20261007-linux-x86_64.tar.gz",
                            b"unzip UCAgent-DMAC-20261007-linux-x86_64.zip")
                        package.writestr(zip_info(member, size=len(data)), data)
                        replacements[relative] = hashlib.sha256(data).hexdigest()
                    else:
                        with package.open(zip_info(member), "w") as destination:
                            shutil.copyfileobj(stream, destination, 1024 * 1024)
                else:
                    raise ValueError("Unsupported archive member: " + name)
                if len(members) % 5000 == 0:
                    print("Converted %d archive entries" % len(members), flush=True)

        for name, target in links.items():
            seen = {name}
            while target in links:
                if target in seen:
                    raise ValueError("Cyclic link: " + name)
                seen.add(target)
                target = links[target]
            if target not in members or not members[target].isfile():
                raise ValueError("Link target is not a packaged file: " + name)
            digest = hashlib.sha256()
            info = zip_info(members[target], name=name)
            with tempfile.TemporaryFile() as contents:
                with package.open(target) as source:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(block)
                        contents.write(block)
                contents.seek(0)
                with package.open(info, "w") as destination:
                    shutil.copyfileobj(contents, destination, 1024 * 1024)
            replacements[name[len(root) + 1:]] = digest.hexdigest()

        note = ("ZIP 版直接解压即可，没有内层 tar.gz。\n"
                "WinRAR 中选择自己的可写目录，例如下载目录。\n"
                "此包运行环境为 Linux x86_64；Windows 可解压和查看报告。\n"
                "在 Linux 直接使用 unzip 解压，可保留程序执行权限。\n"
                "进入包目录后运行 ./Start-UCAgent，纯 SSH 使用 ./Run-DMAC --suite smoke。\n"
                "需要运行时，建议将 ZIP 原样复制到 Linux 后解压，以保留执行权限。\n"
                "原归档中的文件链接已转换为内容一致的普通文件，工具与 RTL 内容未改动。\n").encode("utf-8-sig")
        template = members[root + "/README.md"]
        package.writestr(zip_info(template, name=root + "/ZIP_README.txt", size=len(note)), note)
        replacements["ZIP_README.txt"] = hashlib.sha256(note).hexdigest()
        links_data = b"{}\n"
        link_member = skipped["SYMLINKS.json"][0]
        package.writestr(zip_info(link_member, size=len(links_data)), links_data)
        replacements["SYMLINKS.json"] = hashlib.sha256(links_data).hexdigest()
        inventory = json.loads(skipped["SHA256SUMS.json"][1])
        inventory.update(replacements)
        inventory_data = (json.dumps(inventory, indent=2, sort_keys=True) + "\n").encode("utf-8")
        package.writestr(zip_info(skipped["SHA256SUMS.json"][0], size=len(inventory_data)), inventory_data)

    with zipfile.ZipFile(pending) as package:
        bad = package.testzip()
        if bad:
            raise ValueError("ZIP CRC mismatch: " + bad)
        if any(stat.S_ISLNK(item.external_attr >> 16) for item in package.infolist()):
            raise ValueError("ZIP contains a symbolic link")
        for name, expected_hash in inventory.items():
            with package.open(root + "/" + name) as stream:
                digest = hashlib.sha256()
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != expected_hash:
                raise ValueError("Packaged inventory mismatch: " + name)
    pending.rename(output)
    digest = digest_file(output)
    output.with_suffix(output.suffix + ".sha256").write_text(digest + "  " + output.name + "\n", encoding="ascii")
    report = dict(source_sha256=source_digest, zip_sha256=digest, zip_bytes=output.stat().st_size,
                  source_members=len(members), copied_links=len(links), remaining_links=0,
                  inventory_files=len(inventory), zip_crc="passed", file_hashes="passed")
    output.with_suffix(output.suffix + ".validation.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    convert(args.archive, args.output, args.expected_sha256)
