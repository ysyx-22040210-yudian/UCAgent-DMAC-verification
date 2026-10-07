# UCAgent DMAC：Linux x86_64 完整离线版

此发行包自带 Python、Tk 桌面、执行服务与依赖，以及 **SBY、Yosys、yosys-smtbmc、Z3、Icarus Verilog 和 vvp**。目标设备不需要安装 SBY、Python 或 UCAgent，不需要联网下载工具，也不需要商业许可证。

适用普通 Linux x86_64 用户。图形界面需要已有 Linux 桌面显示环境；纯 SSH 可直接使用命令行重跑。模型生成新属性仍需要另行配置模型账号；打开和重跑本包的已有 SBY 项目不调用模型。

## 解压与启动

```sh
tar -xzf UCAgent-DMAC-20261007-linux-x86_64.tar.gz
cd UCAgent-DMAC-20261007-linux-x86_64
./Start-UCAgent
```

首次启动自动注册四个工程：正常 Counter、故障 Counter、`DMAC-native`（完整辅助 harness）、`DMAC-main`（此前阶段主任务生成的 checker/wrapper）。工程源文件复制到本用户数据目录中，后续启动保留修改、结果和历史。

进入工程 → 启动验证 → 选择 **SBY / bundled_sby** → 启动前检查 → 启动。无需填写求解器路径或导入历史数据库。新机器首次运行状态为尚未运行。

`DMAC-native` 默认执行安全证明；`DMAC-main` 默认执行深度 12 有界检查。BMC 无反例仍为未决。若选择 Cover，未命中目标仍为未决，不能因旧机器的运行通过就自动标记新设备通过。

## 无桌面的命令行

```sh
./Run-DMAC --suite smoke
./Run-DMAC --suite all
```

`smoke` 跑一组安全证明、一项故障对照和 19 次动态回放；`all` 跑 18 个 SBY 任务和全部回放。工具和 Python 路径均从包位置自动解析，允许移动到包含空格的其他目录。

结果默认保存至 `~/.local/share/ucagent-dmac/results/` 的独立子目录，可用 `--output-root /路径` 指定。不会覆盖包内历史证据。返回码 0 表示该范围产生预期证据；总体验证结论仍受未决属性和覆盖缺口限制。

## 校验与诊断

```sh
./Check-Package
./Start-UCAgent --diagnostics
```

可用 `--data /新路径` 指定桌面数据目录，适合在其他设备验证首次启动。桌面服务仅监听随机回环端口，并在进程内生成认证信息。不要以 root 启动桌面。

更完整的规格、测试点、14 阶段使用方法与证据在 `project/docs/使用手册.md` 和 `project/verification/reports/`。第三方来源、版本和许可证分别保留在 `bundle.json`、`THIRD_PARTY.md`、`oss-cad-suite/license/` 和各依赖元数据中。

本包适用于 Linux x86_64，不是 Windows 原生安装包。FormalMC 不在包内；SBY 结果不代表 FormalMC 验收。
