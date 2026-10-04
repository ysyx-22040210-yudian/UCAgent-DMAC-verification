"""Add only the missing librt from the exact same glibc as the pinned EDA runtime."""

import ctypes
import hashlib
import io
from pathlib import Path
import sys
import tarfile


def extract(package, runtime):
    """Read a verified Debian ar archive with the runtime's own Zstandard library.

    Execute with the bundled interpreter/loader. Never load or replace a host
    glibc; the byte-identical libc check prevents mixing incompatible builds.
    """
    data = Path(package).read_bytes()
    if data[:8] != b"!<arch>\n":
        raise ValueError("Runtime support package is not a Debian ar archive")
    offset, compressed = 8, None
    while offset + 60 <= len(data):
        header = data[offset:offset + 60]
        size = int(header[48:58])
        if size < 0 or offset + 60 + size > len(data) or header[58:60] != b"`\n":
            raise ValueError("Malformed runtime support archive")
        if header[:16].decode("ascii").strip().rstrip("/") == "data.tar.zst":
            compressed = data[offset + 60:offset + 60 + size]
        offset += 60 + size + size % 2
    if compressed is None:
        raise ValueError("Runtime support archive has no data.tar.zst")
    runtime = Path(runtime)
    zstd = ctypes.CDLL(str(runtime / "lib/libzstd.so.1"))
    zstd.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
    zstd.ZSTD_decompress.restype = ctypes.c_size_t
    zstd.ZSTD_isError.argtypes = [ctypes.c_size_t]
    zstd.ZSTD_isError.restype = ctypes.c_uint
    target = ctypes.create_string_buffer(64 * 1024**2)
    size = zstd.ZSTD_decompress(target, len(target), compressed, len(compressed))
    if zstd.ZSTD_isError(size):
        raise ValueError("Runtime support archive is invalid or exceeds 64 MiB")
    with tarfile.open(fileobj=io.BytesIO(target.raw[:size])) as archive:
        libc = archive.extractfile("./lib/x86_64-linux-gnu/libc.so.6").read()
        if hashlib.sha256(libc).digest() != hashlib.sha256((runtime / "lib/libc.so.6").read_bytes()).digest():
            raise ValueError("Runtime support libc does not match the pinned EDA runtime")
        for source, destination in (
            ("./lib/x86_64-linux-gnu/librt.so.1", runtime / "lib/librt.so.1"),
            ("./usr/share/doc/libc6/copyright", runtime / "license/ucagent-glibc-support.txt"),
        ):
            # Only explicit regular files are copied; no archive paths are extracted.
            if not archive.getmember(source).isfile():
                raise ValueError("Runtime support member is not a regular file")
            with destination.open("xb") as stream:
                stream.write(archive.extractfile(source).read())


if __name__ == "__main__":
    extract(sys.argv[1], sys.argv[2])
