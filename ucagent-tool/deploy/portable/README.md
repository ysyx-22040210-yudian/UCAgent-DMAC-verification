
# UCAgent Studio：Linux 内置 SBY / 可选 VC Formal

适用 Linux x86_64，使用普通用户启动。完整包包含 Tk 桌面、独立 Python 运行时、SBY、Yosys、SMTBMC、Z3 及执行服务依赖。运行时不需要联网、pip、系统 Python、商业许可证或已有 UCAgent 服务。

图形界面需要可用的 Linux 桌面显示环境（X11，或带 XWayland 的 Wayland）。包内附带开源中文字体，不安装系统字体。纯 SSH 会话请使用 X11 转发或在有桌面的机器启动；无显示环境可执行诊断，不会凭空创建桌面。解压后的软件目录应保留可执行权限。

## 启动

```sh
./Start-UCAgent
```

启动器自动启动本机、仅监听回环地址的执行服务，不使用固定端口。认证口令只在内存传递，不写入项目、日志或配置。

启动诊断（初始化本地数据，但不创建 EDA Run）：

```sh
./Start-UCAgent --diagnostics
```

首次启动在工作台显示 `sby_counter` 和 `sby_counter_bug` 两个真实源代码工程。进入工程，点击“启动验证” → 检查参数 → “启动前检查” → “启动”。前者应证明通过；后者包含显式开启的 RTL 缺陷，应报告失败并提供 VCD 反例。没有预置假运行记录。

## 选择 SBY 或 VC Formal

同一个 APP 中选择“Formal”验证方式，在向导“范围与输出”页选择证明引擎：

| 引擎 | 工具链 | 使用条件 |
|---|---|---|
| `sby` | `bundled_sby` | 包内已包含工具；不需要商业许可证 |
| `vc_formal`（VCF） | 用户配置的 VCF 主机工具链 | 执行端已安装 VCF，并有可签出的有效许可证 |

引擎选项始终可见；未配置引擎时显示接入说明并阻止启动，不会偷偷改用另一引擎。工具链下拉框列出与当前引擎匹配的配置；只有一个匹配项时自动带入，多个匹配项时由用户选择。切换会分别保留 SBY 深度/模式和 VCF 时钟/复位参数，不转换 RTL、harness 或断言语法。

本机 VCF 接入：参考随包 `toolchains.vcf.example.yaml`，由管理员按实际安装路径配置 `~/.ucagent/toolchains.yaml`；已有配置时添加一个独立 profile，**不要覆盖原文件**。`bundled_sby` 是保留名称，主机配置不能替换它。该文件只存路径、环境设置和许可证变量名称，不存许可证值。

也可使用一个明确的配置文件：

```sh
./Start-UCAgent --toolchains /absolute/path/to/toolchains.yaml
```

在已经初始化合法 Synopsys 授权环境的终端启动 APP。桌面入口仅将 `SNPSLMD_LICENSE_FILE`、`LM_LICENSE_FILE` 传入本机服务内存；执行服务只向声明对应变量名的工具链提供这些值，SBY 不继承 VCF 许可证。不会执行 YAML 中的 Shell 命令或自动 source 环境脚本。配置修改后重启本机 APP，再在“工具链”页执行真实探测。

如果 VCF 仅安装在另一台服务器，通过 APP 的“连接”切换到对应执行服务；工程路径和主机工具链属于那个执行端，不能把远程安装路径当作本机工具使用。VCF 授权不可用时保留明确诊断，不能把 SBY 通过解释为 VCF 验收通过。

## 使用自己的 RTL

通过“项目空间 → 导入项目”导入用户 home 下已有工程目录，也可将工程放到数据目录下的 `projects`。配置文件采用 `.ucagent/project.yaml`，参考随包示例。向导中选择 `Formal`、工具链 `bundled_sby`、引擎 `sby`。

支持显式 Verilog/SystemVerilog RTL 和 harness 源文件、include 目录、宏、数值参数，以及只包含源文件、`-f/-F`、`-I`、`+incdir+`、`+define+` 和 `-sverilog` 的 filelist。项目中的任意 Shell、插件加载、Tcl 和自定义 `.sby` 脚本不会被执行。

项目根目录和源文件名可包含空格；Yosys 的 include 选项有不同的引号语义，当前相对 include 目录名必须不含空白字符。违反限制时启动前检查会说明需要修改的目录，不会启动一个已知无效的任务。

时钟、复位和输入约束应写在 HDL harness 中，支持 Yosys 能解析的 `assert`、`assume`、`cover`、`$past` 等构造。工具不会根据时钟名字自动添加假设，也不承诺支持完整商业 SVA、UVM 或 VHDL。不可解析的输入会明确失败。

- `prove`：无界安全属性证明；可能无法收敛。
- `bmc`：有限深度检查。未发现反例显示 `inconclusive` 并说明已检查深度，不显示 `proven`。
- `cover`：目标可达性。生成的覆盖轨迹不是 DUT 缺陷。

SBY 产生的反例会保存为 VCD 等产物，只有另行完成真实仿真回放才可称为“动态复现”。此离线包没有把商业 UVM/VCS 复现授权替换为开源授权。

## 数据与退出

默认数据目录是 `~/.local/share/ucagent-studio`，保留 SQLite、源代码工程、日志和签名产物。重启不会清空历史，已存在的示例不会覆盖。换目录使用 `./Start-UCAgent --data /absolute/user-owned/path`。

退出本地版会确认并停止本机服务、取消未结束的本机任务。远程商业服务不受影响。一个数据目录不能同时由两个 Studio 服务打开。磁盘门禁仍为 10 GiB；大型任务还需预留额外空间。

## Python 3.8 和远程商业流程

桌面代码仍支持 Python 3.8+。若使用已有含 Tk 的 Python 3.8，可执行：

```sh
python3.8 UCAgent-Desktop.pyz --local --bundle /absolute/path/to/bundle
```

执行内核使用包内 Python 3.11，不要求系统安装 3.11。连接原有 VM 商业服务时使用：

```sh
./oss-cad-suite/bin/tabbypy3 UCAgent-Desktop.pyz --server http://127.0.0.1:8800
```

该地址应是已建立的 SSH 隧道；商业授权仍由对应服务器提供。

## 版本与许可

版本、工具版本和依赖列表见 `bundle.json`，上游归档 SHA-256 见 `runtime.lock.json`，补充动态库与字体来源见 `runtime-support.lock.json`、`ui-assets.lock.json`，文件校验清单见 `SHA256SUMS.json`。第三方许可保存在 `oss-cad-suite/license` 和 `fonts`，来源说明见 `THIRD_PARTY.md`。本包保留完整官方运行时并补充匹配版本的 librt，因此体积明显大于纯 Python 桌面包。

搬移或复制后可校验发行包是否损坏（不会修改文件）：

```sh
./oss-cad-suite/bin/tabbypy3 -B Verify-Bundle.py
```

此文件清单校验源文件、二进制、依赖及资源，排除可重新生成的 Python `.pyc` 缓存；不是第三方公钥签名。验证任务另行使用本机私有密钥生成 HMAC 签名清单。
