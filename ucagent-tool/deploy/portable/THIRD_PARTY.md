
# Third-party runtime notices

This distribution retains the complete OSS CAD Suite runtime release dated 2026-07-27, obtained from YosysHQ. Its source release and original archive identity are recorded in `runtime.lock.json`.

- Distribution/build recipes: https://github.com/YosysHQ/oss-cad-suite-build/tree/2026-07-27
- SBY source: https://github.com/YosysHQ/sby
- Yosys source: https://github.com/YosysHQ/yosys
- Z3 source: https://github.com/Z3Prover/z3
- Python source: https://github.com/python/cpython

The runtime addition is `lib/librt.so.1`, needed by the backend's manylinux Python wheels. It comes from Canonical's `libc6 2.35-0ubuntu3.8` package, whose libc must be byte-identical to the suite's bundled libc before extraction is permitted. No host system library is modified. The exact package URL, size, SHA-256 and source location are in `runtime-support.lock.json`; the original notice is retained as `oss-cad-suite/license/ucagent-glibc-support.txt`.

UCAgent modified the two shell launchers `bin/sby` and `bin/yosys-smtbmc` on 2026-09-06 to quote the interpreter path in their `exec` statements. This permits installation directories containing spaces. The modified launcher sources remain in the package; SBY, Yosys and solver implementations are not patched. This change is also declared in `bundle.json`.

Noto Sans CJK SC 2.004 is included under the SIL Open Font License 1.1. Its font and original license are retained in `fonts`; source URLs and hashes are in `ui-assets.lock.json`. No Microsoft font is redistributed.

Original notices and license texts are retained in `oss-cad-suite/license` and the component directories. Backend Python package metadata, licenses and versions are retained in `backend-deps` and recorded in `bundle.json`. UCAgent does not relicense these components. If distributing this package outside your organization, satisfy each component's applicable redistribution and corresponding-source obligations; the source links here are not a replacement for those obligations.

The open-source SBY/Yosys frontend is not YosysHQ's commercial Verific frontend and does not supply any Synopsys VCS, Verdi or VC Formal license.
