# UCAgent DMAC 验证工程

本仓库包含 **DMAC 验证项目、实际使用的 UCAgent 源码与桌面客户端、中文报告和使用手册**。

**在其他 Linux x86_64 设备上使用，请下载完整离线发行包，而不是仅下载仓库源码 ZIP。** 离线包自带 Python、执行服务、SBY、Yosys、Z3 与 Icarus，无需在目标机安装 SBY。

[下载完整离线版](https://github.com/ysyx-22040210-yudian/UCAgent-DMAC-verification/releases/tag/v2026.10.07-offline) · [离线版启动说明](offline/README.md) · [断网验收报告](docs/离线版验收.md)

解压后运行 `./Start-UCAgent`，首次启动自动显示已准备好的 `DMAC-native` 和 `DMAC-main` 工程。无桌面时运行 `./Run-DMAC --suite all`。新设备运行结果独立保存，不继承旧机的通过和审批状态。

**14 个启用阶段已完成；主任务设计验证结论仍为未决。** 63 条主任务断言在深度 12 内无反例；触发可达见证命中 61/63，业务覆盖命中 14/19。四组原生辅助安全证明通过，七项故障对照被检测，19 次动态回放完成。工具回归 66 项通过。辅助证明不等于全部主任务属性获证；FormalMC 和 VCS 尚未实测。

- **[DMAC 详细验证文档](docs/DMAC详细验证文档.md)**：完整方案、验证策略、88 个检测点、时序示例与实际报告；[离线 HTML](docs/DMAC详细验证文档.html) · [88 CK 清单](docs/DMAC检测点清单.csv)。
- [中文使用手册](docs/使用手册.md)：安装、启动桌面客户端、14 阶段流程、迁移与重跑方法。
- [完整中文验证报告](verification/reports/DMAC_完整流程验证报告.md)。
- [功能与检测点分解](verification/reports/guided/03_dmac_functions_and_checks.md)：12 FG、48 FC、88 CK。
- [需求追踪表](verification/reports/guided/08_dmac_requirement_traceability.md)。
- [逐属性中文证据表](verification/reports/testpoint-evidence.csv)。
- [打包与搬运验收](docs/交付验收.md)。

下载整个仓库后，用浏览器打开 `verification/reports/testpoints.html`，即可离线查看中文交互报告，按需求、检测点、参数和结论筛选。GitHub 文件预览不会执行该页面的 JavaScript。

## 目录

| 目录 | 内容 |
| --- | --- |
| `ucagent-tool/` | 虚拟机实测工具源码、阶段配置、模板、后端、桌面代码、测试及来源清单 |
| `bin/UCAgent-Desktop.pyz` | 可直接启动的轻量桌面客户端，Python 3.8+ 与 Tkinter |
| `bin/ucagent-0.9.1-py3-none-any.whl` | 在 VM 实际构建的后端安装包，Python 3.11+；依赖另行安装 |
| `dmac/rtl/` | 未修改的原始 DMAC 与 FIFO RTL |
| `verification/reports/` | 规格、属性、14 阶段记录、SBY 输入、日志、波形、回放与回归证据 |
| `scripts/` | 校验包、独立 SBY 重跑及动态回放入口 |
| `config/` | 工具链路径配置示例 |
| `docs/` | 中文手册与交付验收记录 |

## 快速开始

完整离线版：

```sh
tar -xzf UCAgent-DMAC-20261007-linux-x86_64.tar.gz
cd UCAgent-DMAC-20261007-linux-x86_64
./Start-UCAgent
# 纯 SSH 环境：
./Run-DMAC --suite smoke
```

以下为仅下载源码时的开发者入口；普通用户使用上述离线版即可。

仅查看报告：无需安装 UCAgent 或求解器。

校验交付文件（Python 3.8+）：

```sh
python3 scripts/check_delivery.py
```

在 Linux 上将已安装的 OSS CAD Suite `bin` 加入 PATH 后，重跑一组安全证明、一项故障对照及 19 次回放：

```sh
python3 scripts/run_dmac.py --suite smoke
```

新的运行写入独立的 `results/` 子目录，不覆盖历史证据。缺少工具、编译错误、超时和缺失结果都会报错；故障对照必须出现真实断言反例才能计为对照有效。

启动桌面客户端：

```sh
python3 bin/UCAgent-Desktop.pyz --server http://127.0.0.1:8800
```

后端需要 Python 3.11+ 与依赖，部署步骤见手册。已有证据不会自动恢复成可编辑的完成会话；在新机器新建任务、运行并形成新证据。
