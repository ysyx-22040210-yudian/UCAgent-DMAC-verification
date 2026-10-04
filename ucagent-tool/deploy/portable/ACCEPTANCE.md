
# Studio 0.3.0 Linux 离线版验收记录

验收日期：2026-09-06。目标设备：192.168.31.116，CentOS 7 x86_64，内核 3.10.0-1160.53.1.el7。使用普通 `ucagent` 用户、包内 Python 3.11.6 / Tk 8.6 和真实 EDA 二进制。使用独立网络命名空间，仅启用 loopback，不修改主机网络；Tk 显示由 Xvfb 提供。

## 真实运行

| 场景 | 实际验收结果 |
|---|---|
| Tk 向导启动 counter `prove` | 已完成、验证通过，ASSERT 为 proven |
| counter 开启 RTL 缺陷 | 已完成、验证失败，保存 falsified 属性及 VCD 反例 |
| 无反例的有限深度 `bmc` | inconclusive，不伪报为完整证明 |
| `cover` 命中 / 未命中 | covered / uncovered，未命中不当作 DUT 缺陷 |
| 求解超时 | timeout，未报 Pass |
| 手动取消 / 关闭执行服务 | cancelled，重启仍保留正确终态 |
| HDL 语法错误 | 执行 error，不冒充 DUT 反例 |
| 自有工程入口 | 嵌套 filelist、include、宏、参数及含空格的项目根目录 / 源文件名真实证明通过 |
| 状态恢复 | Run、属性、产物、日志游标在服务重启后可继续读取 |
| 反例下载 | 下载后的 VCD SHA-256 与登记值一致 |
| 本机认证 / 数据锁 | 无口令 API 请求返回 401，同一数据目录第二个服务拒绝启动 |
| 搬移发行目录 | 含空格的新安装目录中重复整套断网、Tk、SBY 验收通过 |
| 完整性 | 搬移与运行后，19,500 个登记文件和符号链接校验通过 |
| 正式启动器 | `Start-UCAgent --diagnostics` 返回 0，无启动错误 |

两次完整验收分别保留在仓库 `desktop/review-artifacts/portable-0.3.0/acceptance.json` 和 `relocation.json`。`workbench.png`、`sby-wizard.png` 是已人工查看的真实 Linux Tk 截图，不是设计稿。复现脚本为 `deploy/accept_portable.py`。

## 回归测试

- Linux Python 3.11：SBY、现有 EDA Adapter、JobRunner、输入闭包、安全、parser、项目、工作台、API、反例关联及恢复等定向测试 **172 passed**。
- Windows Python 3.8.20 / Tk 8.6.13：原生界面、HTTP、后台任务、本机服务监督及窗口交互 **50 passed**。
- 新增与修改的 Python 文件通过编译检查；`git diff --check` 通过。
- 未运行 MkDocs 严格构建：本地未安装文档构建依赖。未把该项计入通过数量。

## 验收边界

此结果验证 Linux x86_64 离线 SBY 执行链，不是 VCS / VC Formal 商业流程的重新验收。原有 VM 的商业服务没有替换。未声称已测试 ARM、所有 Linux 发行版、完整商业 SVA、VHDL 或真实动态反例回放。

SBY 运行用户编写的 RTL / formal harness，不会离线自动调用 LLM 生成 golden model。相对 include 目录名暂不支持空白字符，启动前检查会明确拒绝。包需要图形显示环境和至少 10 GiB 可用工作盘空间；不需要联网安装 Python、求解器或第三方字体。
