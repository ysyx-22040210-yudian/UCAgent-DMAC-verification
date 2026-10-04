
# UCAgent Studio · 原生 Tk 桌面 APP

## 当前源码：共用形式化阶段工作台

2026-09-12 候选版本在“形式化工作台”创建时选择 `formalmc` 或 `sby`，
之后共用“启动 / 继续 Agent”、阶段 Check/Complete、差异审查、人工审核、取消和恢复。
原始 FormalMC 阶段定义与脚本保持不变；SBY 差异放在适配与能力说明中，不要求用户改走另一套操作。
操作和共用 Claude Code 配置见[形式化 GUI 手册](../docs/content/02_usage/11_formal_gui.md)。
候选版本的实测范围与外部阻塞见[共用 Agent 验收记录](../acceptance/FORMAL_SHARED_AGENT.md)。

“新建运行”仍是已有 harness 的直接 EDA 执行入口，不等同于上述完整阶段工作台。
以下保留版本化发行说明，不表示旧离线包已自动升级。

## 2026-09-08 FormalMC 回退版本

2026-09-08 起，新建 Formal 任务默认使用原始 UCAgent FormalMC，不再根据安装工具自动选择 VCF 或 SBY。需要执行端安装并配置真实 FormalMC；缺少工具或授权时明确阻塞。选择一个 FormalMC 入口 Tcl，时钟、复位和约束在脚本中定义，不填写 VCF 的 timing 参数。

原始 `formal.yaml` 负责规格、SVA、验证环境和报告的 Agent 工作流；TK 运行向导负责执行准备好的 Tcl，不能用“选中 FormalMC”代替生成和检查验证环境。已有 VCF/SBY 项目及历史 Run 不会被改写，只有明确选择时才使用这些引擎。下文 0.3.1 离线包是此前已发布版本，不会因源码修改自动升级。

配置与部署边界见 [FormalMC 回退记录](../acceptance/FORMALMC_RESTORE.md)。

已在 `192.168.0.102` 部署独立回退版本 `20260908-formalmc-restore1`。轻量客户端为 `desktop/dist/UCAgent-Desktop-FormalMC-20260908.pyz`；VM 上可运行 `python3.8 /home/ucagent-lab/current/desktop/UCAgent-Desktop.pyz --server http://127.0.0.1:8800`。已用实际 Python 3.8.13 完成 56 项测试。该版本没有改写已有 SBY 离线包，也没有发布开发中的 Campaign 功能；VM 尚未发现 FormalMC 安装，因此真实证明仍会阻塞。

这是独立的 `tkinter + ttk` 桌面应用，最低 Python **3.8**，仅使用标准库，不嵌入网页，不需要 Node、React、浏览器或 `pip install ucagent`。

**版本边界：Python 3.8 适用于桌面 APP；执行服务需要 Python 3.11。** 界面通过 `/api/v1` 调用同一个执行内核。Linux 离线版已经包含所需解释器、执行服务、SBY、Yosys、SMTBMC 和 Z3；远程模式继续连接原有 VM，不在客户端启动 VCS。

## Studio 0.3：Linux 离线 SBY

将完整 `UCAgent-Studio-0.3.1-linux-x86_64.tar.gz` 解压到普通用户可访问的 Linux x86_64 桌面，运行其中的 `Start-UCAgent`。内置 SBY 不需要系统 Python、联网、pip、Node、SSH 隧道或商业许可证。默认数据位于 `~/.local/share/ucagent-studio`，退出时确认停止本机服务并取消尚未完成的本机任务；重启保留项目、运行、属性、产物和日志历史。磁盘门禁仍为 10 GiB。

工作台自带正常及故意出错的两个计数器项目。进入项目，点击“启动验证”，选择 SBY 的 `prove / bmc / cover`、深度和超时，通过启动前检查后运行。时钟、复位、输入假设必须在 HDL harness 中明确编写；不会自动套用 VC Formal 的约束。VCD 反例可以直接下载，尚未经过仿真回放时不会标为动态复现。

0.3.1 支持在同一向导明确选择 `sby` 或 `vc_formal`（VCF），筛选对应工具链并分别保留参数。VCF 不包含在离线包中：通过 `~/.ucagent/toolchains.yaml` 或 `--toolchains /absolute/path.yaml` 接入执行端已有安装与有效授权。缺少工具链或许可证时明确阻塞，不自动回退。详细配置见下方完整说明。

SBY 执行用户提供的 RTL/harness，不等同于自动调用 LLM 生成完整验证环境。当前离线发行包不包含商业 Verific 前端、完整商业 SVA 支持或 Synopsys 授权，也不包含内嵌的 VCD 查看器。

完整说明见 [`deploy/portable/README.md`](../deploy/portable/README.md)。单独 `.pyz` / wheel 仍是轻量桌面客户端，不包含 EDA 工具；不要把它们当作完整离线包。

## Studio 0.2 界面

深海蓝导航、浅色工作区和靛蓝主操作采用统一的字体、间距、原生矢量图标与状态色。工作台直接显示已有工程、最新验证结论、需要处理的结果和真实工具状态；不生成演示数据或虚构进度。

- 主窗口默认 1440 × 940，最低 1120 × 760；向导最低 920 × 710。长页面可滚动，操作栏保留在窗口内。
- `Ctrl+K`：按项目名、Run ID 或测试名搜索并跳转；`Enter` 打开选中项，`Esc` 关闭搜索。
- `Ctrl+N`：启动验证向导；`F5`：刷新当前页面。
- 项目列表支持方向键、滚轮、双击和右侧箭头；表格点击列标题排序，刷新保留排序和选中记录。缺失数值仍显示 `--`，不会填零。
- 高级 Include / Define / 参数默认收起，展开、收起不会丢掉已保存输入。
- 运行详情先显示独立的执行状态、验证结论、实测计数和本次范围。原始证据收在明确的展开控件后，日志使用深色等宽阅读区。
- 按钮具有键盘焦点、悬停和禁用状态；无溢出的文本框和表格不显示空滚动条。

本版没有 WebView、第三方主题包或远程字体依赖。原 Web 平台和后端证据继续保留，不因界面升级被清空。

## 1. 启动

先确认当前解释器有 Tk：

```powershell
python --version
python -m tkinter
```

然后运行：

```powershell
python D:\UCAGENT\desktop\ucagent_app.py
```

Windows 无终端窗口启动：

```powershell
powershell -NoProfile -File D:\UCAGENT\desktop\Start-UCAgent.ps1
```

指定自己的 Python 3.8 解释器：

```powershell
powershell -NoProfile -File D:\UCAGENT\desktop\Start-UCAgent.ps1 -Python C:\Python38\python.exe
```

`C:\Python38\python.exe` 是示例路径，请替换为实际安装位置。启动器不会安装软件或修改 PATH。若 `.pyw` 已关联 Python 3.8+，也可双击 `ucagent_app.pyw`。

Linux 桌面可以执行 `python3 ucagent_app.py`，但解释器必须包含 tkinter，且必须存在图形显示环境；纯 SSH 终端不提供本地窗口。界面语言资源随包分发，不依赖当前目录。

## 2. 连接 VM

后端继续监听 VM 的 `127.0.0.1:8800`。本机先保持 SSH 转发：

```powershell
ssh -N -L 8800:127.0.0.1:8800 root@192.168.31.116
```

应用右上角“连接”填 `http://127.0.0.1:8800`。如果已经有可用的 8800 隧道，不要重复创建。也可使用管理员提供的非 root SSH 登录账号；EDA 服务本身仍以专用 `ucagent` 用户执行。

APP 不管理 SSH、不保存 SSH 密码、不接受项目里的许可证值。非回环地址必须使用 HTTPS；不关闭证书校验、不跟随重定向、不使用环境代理转发本地请求。

只读诊断：

```powershell
python D:\UCAGENT\desktop\ucagent_app.py --diagnostics
```

远程模式未连接时窗口仍可操作，并明确显示连接错误，此时无法执行远程 EDA。离线 SBY 模式由 `Start-UCAgent` 自动启动本机服务，不需要连接 VM。

## 3. 日常验证流程

1. 在“工作台”双击项目，或选中后按 Enter / 点击右侧箭头进入项目。已有 VM 项目直接显示，不需要重新导入。
2. 新项目通过“项目空间 → 导入项目”填写**服务器工程路径**。正常读取工程的 `.ucagent/project.yaml`；需要时可以填写高级结构化项目 JSON。
3. 在项目里点击“启动验证”，完成三步向导：
   - 项目与方式：UnityTest、原生 SV、UVM 或 Formal，工具链、top、filelist、源文件、参数。
   - 范围与输出：UVM 的 UT/IT/ST、真实 test 类、seed、覆盖率、波形；Formal 的引擎、clock/reset、属性集和反例复现策略。
   - 启动前检查：查看全部检查项、实际 test × seed 矩阵、脱敏命令。阻塞时只能重新检查，不能启动。
4. 启动后进入独立运行记录。选择“查看下一步”，直接进入当前结果需要的测试、任务、属性、覆盖率或产物页。
5. 修改验证范围时用“复用配置重跑”。它读取该次 Run 保存的不可变请求，生成新的 Run，不覆盖历史。

“输入文件上传”最多 16 个文件、总计 32 MiB，服务器保存到项目内 `.ucagent/uploads/`，拒绝覆盖。将返回路径显式加入下次运行的源文件配置。上传不是 ZIP 工程导入，不自动解压、不自动修改编译输入；如果一批上传中途失败，先确认已经成功保存的文件再重试。

## 4. 结果与证据

运行页包含概览、完整阶段树、任务、测试矩阵、覆盖率、Formal 属性、问题、产物、实时日志、协作与审阅。

- **执行状态与验证结论分开**：断言失败可以是 `completed + failed`；许可证失败是执行异常，不会显示验证通过。
- 工作流目录显示全部 6 条当前目录项及其子阶段，未启用的 Formal、Mock、覆盖率、CEX 等条件分支仍有禁用原因。资产编写模式保持 `guided / incremental / vibe` 字段，不冒充 EDA 引擎。
- 未提供覆盖率计数或签核目标时显示缺失，不填 0 或 100%。没有 FG/FC/CK 映射就显示未映射。
- 日志以 SSE 断线续读，保留已消费游标；“从头读取日志”可重看历史。屏幕最多保留 3000 行，完整内容以服务器日志产物为准。保存游标不是保存本地完整日志副本。
- 人工审批仅作用于服务器声明的待审阶段。批准不会抹掉失败测试或生成缺失证据。
- 下载流式写入独立临时文件，校验登记的 SHA-256 和文件大小，成功后原子替换目标。失败或取消不覆盖原文件。
- FSDB 下载后在本地 Verdi 打开；VCD/FST 下载后使用本地波形工具。APP 不嵌入 Surfer 或 FSDB 浏览器。

```bash
verdi -ssf downloaded.fsdb
```

Formal 反例复现必须指定真实 UVM/UnityTest 用例，后端检查签名 CEX 并实际运行，不能靠文档或函数名宣称“已复现”。复现记录按钮显示后端已登记的尝试。

“生成 UVM 1.2 环境”要求真实 DUT 端口、时钟、复位和输入路径。结构检查不等于功能签核。参考模型仅接受用户提供的模型契约，默认为 `null`；不会由 AI 猜出一个 golden model。

## 5. Agent、MCP 和后端能力边界

本版桌面端负责组织、发起、检查和审阅验证运行。Agent 资产编写仍通过实际 Agent / CLI / MCP 客户端完成；“MCP 接入”展示后端真正提供的协议 URL 和 Schema。“协作与审阅”仅显示持久化的真实事件，**不是内置 LLM 聊天客户端**。

VCS / URG / VC Formal / FormalMC / Picker 的能力取决于后端配置和许可证。界面显示入口不代表许可证可用，也不代表本次已经完成商业验收。原 Web 入口暂时保留，不删除历史数据库或产物。

关闭远程模式 APP 不停止 VM 上的 Run。窗口立即关闭，客户端在后台等待已经发出的有超时 I/O 结束后退出；不会自动重试不确定的 POST。若启动请求超时，先查运行记录再决定是否重发。

## 6. 本地数据与安全

默认仅保存 `~/.ucagent-tk/preferences.json`：服务 origin 和最多 500 个运行游标。可用 `--preferences <path>` 指定测试配置路径。不保存 API Key、SSH 密码、许可证值或完整项目配置。更换服务时清除游标、关闭旧服务的编辑窗口，并丢弃旧响应。

大型 FSDB、VDB、proof DB 仍在 VM 文件系统；只有明确下载的文件存到本机。APP 没有自动清理远端产物的按钮。后端磁盘门禁默认 10 GiB，本次没有降低它。

## 7. 打包与回归

从 `desktop` 目录执行：

```powershell
python -m compileall -q ucagent_tk
python -m unittest discover -s tests -p "test_*.py" -v
python build.py
python dist/UCAgent-Desktop.pyz --diagnostics
python dist/UCAgent-Desktop.pyz
```

`.pyz` 是可分发的单文件 Python 应用，不含 Python/Tcl/Tk 解释器，需要接收方有 Python 3.8+ 和 tkinter。也可在该目录 `python -m pip install .` 安装独立的 `ucagent-desktop` 包；**不要为了桌面端安装仓库根目录的后端依赖**。

测试使用标准库 unittest 和真实 Tk 窗口，不依赖 pytest、Playwright 或浏览器。Linux 无图形显示时 GUI 测试会跳过，因此不能用无显示环境的绿色结果宣称通过 GUI 验收。

VM 只读原生界面验收（不会启动 EDA）：

```powershell
python tests/acceptance_vm.py --output review-artifacts/readonly
```

完整原生视觉检查，包含运行详情各页、搜索、向导和小窗口截图；只读已有 Run，不启动 EDA：

```powershell
python tests/acceptance_vm.py --visual-review --output review-artifacts/studio-review
```

明确发起真实 Adder Pass/Fail 和 UART UVM 两 seed、URG、FSDB 验收：

```powershell
python tests/acceptance_vm.py --execute --output review-artifacts/vm
```

测试脚本使用已有指定名称的验收工程，不扫描或清空 VM 工程。Windows 截图仅捕获被测试的 Tk 窗口。验收脚本截图、JSON、波形输出均已在 `.gitignore` 排除。

桌面进程将 CPython 循环垃圾回收安排到 Tk 主线程，防止后台 HTTP 线程回收已关闭的 Tcl 对象；窗口关闭会回收变量、移除定时器并排空 I/O。这是独立桌面程序的生命周期策略，不应将 `Application` 嵌入另一个拥有不同 GC/事件循环策略的宿主。

## 8. 实测记录

2026-09-06，Windows / Python **3.8.20** / Tk **8.6.13**，原生按钮驱动当前 VM 后端：

| 验收 | 结果 | Run ID |
| --- | --- | --- |
| Adder 原生 VCS，seed 17 | completed / passed | `dec81e9fbf4348cb9a7541c5dc01f3a1` |
| Adder 注入断言失败 | completed / failed，未弱化检查 | `8c931fd7ee294ad8a4c07df060f7bb8c` |
| UART UVM，seed 11、29 | completed / passed，4 个任务、5 项覆盖率 | `72c77ee550b44293a71f79e13422eba3` |
| UART FSDB 原生下载 | 9779 bytes，SHA-256 一致 | `bbda5a8077c6a0e606d6ba77c46be5451baeefd9b005f8eb50d22f73f5602308` |
| VC Formal | 启动前被现有许可证检查拦截，未宣称 proof 通过 | `tool:vcf = blocked` |

具体桌面验收记录：`review-artifacts/20260906-py38-verified/acceptance.json`。这一轮没有重新运行 XiangShan full-chip、FormalMC 或 UnityTest EDA，它们的既有记录继续可读。

0.1 版的 33 项传输、参数、原生 GUI 和生命周期回归在 Python 3.8.20、Python 3.11.5 均通过；没有跳过 GUI 测试。上述 EDA 记录属于该轮真实运行，界面重设计不把读取旧证据算成新一轮 EDA 验收。

Studio **0.2.0** 界面回归：42 项测试在 Python **3.8.20** 和 **3.11.5** 均通过，包含原生控件键盘/禁用行为、搜索的真实 ID 跳转、高级字段收起保留、数值排序、缺失值语义、证据展开和小窗口下全部标签/操作入口可达。

已使用 Python 3.8 的隔离模式加载实际 `dist/UCAgent-Desktop.pyz`，连接当前 VM 完成全部 7 个主页面、6 个工作流目录项、既有 UART Run 详情、向导、搜索和小窗口视觉检查，共 28 张原生截图，Tk 回调错误为 0。该轮只读已有证据和启动前检查，没有新建 EDA Run。记录位于 `review-artifacts/studio-0.2-py38/acceptance.json`，截图保存在同目录。

分发包为 `dist/UCAgent-Desktop.pyz` 和 `dist/ucagent_desktop-0.2.0-py3-none-any.whl`；wheel 声明 `Requires-Python: >=3.8`，无额外运行依赖。Python/Tcl/Tk 本身需要预先安装。
