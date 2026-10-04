
# Studio 0.3.1 双引擎选择验收

2026-09-06，在 192.168.31.116 的 CentOS 7 x86_64 VM 上，以普通 `ucagent` 用户运行独立发行包。原有 `ucagent-platform` 服务、其主机配置和运行历史未替换。

## 实际验证

- 纯离线环境仅保留 loopback：内置 SBY 的证明、反例、有限深度、cover、超时、取消、重启恢复、VCD 下载和输入闭包等完整验收通过。
- 接入真实主机 VCF profile 后：Tk 向导可从 SBY 切到 `vc_formal`，工具链切换到唯一匹配的 VCF profile；时钟和复位不自动填造。切回 SBY 后，其模式、深度与工具链恢复，并由原生向导发起真实证明通过。
- 真实 VCF 探测：`binary_available=true`、`version_probe_status=completed`，但 `license_status=unavailable`、`license_probe_status=error`。界面显示许可证失败。这是引擎接入及失败诊断验证，**不是 VCF 证明通过验收**。
- 接入 VCF 后重复 SBY 全套真实验收通过；商业许可失败未阻塞 SBY。
- 发行包 19,501 个登记文件及符号链接通过完整性检查。

实际 JSON 报告见 `desktop/review-artifacts/portable-0.3.1/offline.json`、`dual-engine.json`。`sby-wizard.png`、`vcf-wizard.png` 是已查看的真实 Linux Tk 截图。

## 自动化测试

- Linux Python 3.11：183 项定向测试通过，覆盖现有执行内核、两种 Formal Adapter、输入/证据安全、API、持久化，以及主机 profile 与内置 profile 共存。
- Windows Python 3.8.20 / Tk 8.6.13：53 项桌面测试通过，包含引擎切换、参数分离、未配置引擎阻止启动、许可证只在内存传递。
- 验证主机配置不能替换 `bundled_sby`；损坏或含内联许可证值的配置不会移除内置 SBY，也不会在诊断中泄露授权值。
- Python 编译检查与 `git diff --check` 通过。未执行 MkDocs 严格构建，本地未安装该构建依赖。

## 复现

纯离线验收方法见 `BUILD.md`。双引擎验收需要真实主机配置和授权网络，不应放入隔离外网的命名空间：

```sh
./oss-cad-suite/bin/tabbypy3 -B /source/deploy/accept_portable.py \
  --bundle /releases/UCAgent-Studio-0.3.1-linux-x86_64 \
  --data /home/tester/fresh-dual-engine-test \
  --toolchains /absolute/path/to/toolchains.yaml \
  --vcf-profile host_vcf --gui --screenshots
```

`--screenshots` 使用已有 X11 `xwd`；无此工具时省略该选项。数据目录必须全新。此脚本会发起真实 VCF 授权 smoke，可能占用许可证，但不会修改授权配置或将签出失败改写为 Pass。
