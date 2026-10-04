
# 商业验证可视化平台

UCAgent 商业验证平台把验证方法、执行工具和编写模式拆成三个独立维度。VCS 是仿真器，UVM 是方法学，Picker 是 Python DUT 绑定生成器，VC Formal 和 FormalMC 是形式验证引擎；它们不再被混成同一种“工作流”。

平台提供原生 Tk 桌面和 React 页面，共用 FastAPI `/api/v1` 与同一个 EDA 执行内核。大型 FSDB、VDB 和 proof database 保存在文件系统中，SQLite 只保存索引和规范化结果。Linux x86_64 的 Studio 离线发行包内置 SBY、Yosys、SMTBMC、Z3、Python/Tk 和服务依赖，解压后使用普通用户执行 `Start-UCAgent` 即可运行开源形式验证；商业工具仍需单独配置和授权。

## 支持矩阵

| 工作流族 | 方法学 | 工具链 | 主要结果 |
|---|---|---|---|
| simulation | unitytest | Picker + Verilator 或 VCS | Python DUT、toffee 测试和波形 |
| simulation | systemverilog | VCS | 原生 SV testbench 结果 |
| simulation | uvm | VCS + UVM 1.2 + URG | UT/IT/ST 矩阵、覆盖率、FSDB/VPD |
| formal | systemverilog | 默认 FormalMC（原始 UCAgent 流程） | 属性状态、反例和 proof artifacts |
| formal | systemverilog | SBY + Yosys + SMTBMC + Z3 | 无界证明、有限深度检查、cover 和 VCD 轨迹 |

## FormalMC 原始流程（默认）

新建 Formal 任务默认采用原始 UCAgent FormalMC。不再按主机上已有的 VCF/SBY 自动选择引擎。VCF、SBY 仍可显式选择；已有项目和运行快照不会被静默转换，VCF Tcl 不能直接当作 FormalMC Tcl 使用。

完整的 Agent 编写流程继续使用 `ucagent/lang/zh/config/formal.yaml`：需求规划、设计理解、功能规格、SVA 属性、脚本、环境迭代、覆盖分析、反例测试、证明执行、静态候选验证及总结。原始模板、Formal_Doc、Checker 与可选分支保持有效，`Undec` 不视为通过，反例复现仍要求真实测试证据。

TK/API 执行准备好的脚本时，`formal.property_sets` 必须包含且只包含一个 `.tcl` 入口；辅助脚本通过该入口引用。时钟、复位和假设写在 FormalMC Tcl 的 `def_clk`、`def_rst` 等命令中，`formal.clock` 和 `formal.reset` 留空。平台执行 `FormalMC -f <入口> -override -work_dir <独立目录>` 并读取 `avis.log`，不生成 VCF 的 `check_fv` 流程。

```yaml
schema_version: 1
design:
  top: Adder
  sources: [Adder/Adder.sv]
workflow:
  family: formal
  methodology: systemverilog
  authoring_mode: guided
toolchain: formalmc_local
formal:
  engine: formalmc
  property_sets: [formal_out/tests/Adder_formal.tcl]
  clock: {}
  reset: {}
  cex_replay:
    enabled: false
    methodology: unitytest
```

示例路径必须对应项目中的真实设计和已生成脚本。FormalMC 是独立商业工具，需要执行端的真实安装和有效授权；UCAgent 不附带其二进制或许可证。缺少工具时预检阻塞，不自动换成 VCF/SBY。主机管理员可参考仓库中的 `deploy/toolchains.formalmc.example.yaml` 配置工具路径；许可证值不得写入项目配置。

## 内置 SBY

原生 Tk 的 Formal 向导可以选择 `sby`，通过结构化字段设置模式、深度、超时和多时钟。SBY 执行已提供的 RTL/harness，不自动运行 Agent 资产编写；本次没有执行的编写阶段保留在流程树中并显示禁用原因。当前 Web 向导未提供 SBY 专用表单，SBY 使用原生 Tk 或公共 API。

```yaml
schema_version: 1
design:
  top: counter
  sources: [counter.sv]
workflow:
  family: formal
  methodology: systemverilog
  authoring_mode: guided
toolchain: bundled_sby
formal:
  engine: sby
  clock: {}
  reset: {}
  property_sets: []
  sby:
    mode: prove
    depth: 20
    timeout_seconds: 120
    multiclock: false
  cex_replay:
    enabled: false
    methodology: uvm
```

时钟、复位和输入假设写入 HDL harness；`formal.clock/reset` 不会转成 SBY 假设，填写冲突字段会被拒绝。只接受 Yosys 支持的 RTL/断言及受限字面 filelist，不执行项目提交的任意 Shell、Tcl 或 `.sby` 脚本。BMC 的 PASS 是有界证据，规范化为 `inconclusive`，不是 `proven`；cover 未命中也不是 DUT 缺陷。状态文件、JUnit 属性、实际退出码和轨迹经过交叉校验，再由执行器签名发布。缺失、损坏或互相矛盾的报告不能得到 Pass。准备完成后 filelist 发生变化必须重新准备任务，不能执行旧计划。

离线包将用户数据保存在 `~/.local/share/ucagent-studio`，程序目录与数据分离；新任务保留 10 GiB 磁盘门禁。内核自带 Python 3.11，桌面代码仍支持 Python 3.8+。当前发行目标是 Linux x86_64，不代表 ARM、Windows 完整离线包或商业 SVA 前端已经支持。

`guided`、`incremental` 和 `vibe` 是 `authoring_mode`，表示验证资产的编写方式，不表示一种新的仿真器或方法学。

UnityTest 必须显式设置 `simulation.simulator`。选择 `verilator` 时 Picker 使用 direct-memory 绑定并支持 VCD/FST；选择 `vcs` 时使用 DPI 绑定并支持 FSDB。原生 SystemVerilog 和 UVM 固定使用 VCS。波形设为 `none` 时 Picker 不生成隐含波形文件。

UnityTest 还必须显式列出项目内 pytest 文件；Picker 成功发布 Python DUT 后，平台按“pytest 文件 × seed”执行真实测试，而不是把“绑定生成成功”当成验证通过：

```yaml
workflow:
  family: simulation
  methodology: unitytest
  authoring_mode: guided

simulation:
  simulator: verilator
  unitytest_tests:
    - tests/test_smoke.py
    - tests/test_corner.py
  seeds: [1, 29]
  coverage: []
  waveform: fst
```

pytest 断言失败表示 `completed + failed`；collection、fixture 或框架错误表示 `error + unknown`；没有实际执行任何测试表示 `completed + inconclusive`。

## 页面入口

平台默认监听服务器回环地址：

```text
http://127.0.0.1:8800/platform/
```

远程使用时建立 SSH 隧道，不要把服务直接暴露到局域网：

```bash
ssh -L 8800:127.0.0.1:8800 <user>@<server>
```

然后在本机打开 `http://127.0.0.1:8800/platform/`。

工作台以项目为中心：从「继续项目」进入项目工作区，查看验证范围、已有测试集、参考模型、输入文件及历史运行。「验证记录」集中查询运行中、验证失败和执行阻塞的记录。工具链、MCP 与设置放在独立的平台区域。

「流程指南」列出全部工作流；展开任一工作流可查看完整 DAG。当前配置没有选择的 UT/IT/ST、覆盖率、波形、VC Formal、FormalMC 和反例复现节点仍然显示，并附带 `disabled_reason`。

### 日常验证操作

1. 在「项目空间」导入管理员允许目录中的工程，然后进入项目。确认顶层、工程入口、测试集与参考模型；生成 UVM 环境的结构检查不能替代功能验证。
2. 点击「启动验证」。第一步自动带入项目的 top、filelist、defines、parameters 和工具链，再选择原生 SV、UVM、UnityTest 或 Formal。高级设计输入可展开修改。
3. 第二步选择实际测试范围及输出。UVM 按所选 UT/IT/ST 层级带入对应测试和 seed；不同层级的测试不会混成额外的交叉组合。填写的每个 seed 都必须是正整数，错误输入不会被静默丢弃。波形和覆盖率继承项目配置。
4. 点击「检查运行条件」。服务端只读检查输入路径、所选工具、最近许可证探测、磁盘及执行计划，不创建 Run、不编译、不写入项目。检查页展示阻塞项、修复入口、实际测试矩阵和脱敏命令。只有没有阻塞项才显示启动按钮；未知许可证容量仍需由真实执行确认。
5. 启动后进入「结果总览」。运行状态自动刷新，进度来自已终结任务数而不是虚构的验证百分比。页面给出下一步入口：运行中查看任务；基础设施阻塞查看诊断；测试失败查看用例；Formal 未决查看属性；成功后审查覆盖与证据。
6. 点击「复用配置」开始下一轮。它读取原运行的不可变请求，保留参数、测试、seed 和输出选择，并创建独立记录，不覆盖历史运行。需要定位详细证据时进入执行任务、测试用例、覆盖率、形式属性、问题与证据、运行产物或实时日志。

当前 Web 启动的是结构化 EDA 执行。Agent 资产编写与对话需要连接实际 Agent/MCP 客户端；没有收到 Agent 消息时，「协作与审阅」会明确说明，不把工具日志伪装成 Agent 对话。运行通过也不自动代表规格、参考模型、覆盖率和人工签核已全部完成。

## 项目配置

每个项目使用 `<project>/.ucagent/project.yaml`。配置只允许结构化字段，未知字段、重复 YAML key、绝对路径、父目录穿越、命令注入字符和常见秘密字段会被拒绝。

```yaml
schema_version: 1

design:
  top: tb_top
  filelists:
    - uvm_env/files.f
  sources: []
  include_dirs: []
  defines: []
  parameters: {}

workflow:
  family: simulation
  methodology: uvm
  authoring_mode: guided

toolchain: synopsys_o2018

simulation:
  simulator: vcs
  uvm_version: "1.2"
  recipe:
    kind: native
  suites:
    - name: block_ut
      level: UT
      tests:
        - demo_uvm_test
      seeds:
        - 1
        - 2
  seeds:
    - 1
    - 2
  coverage:
    - line
    - cond
    - tgl
    - fsm
    - branch
    - assert
  coverage_mapping:
    - requirement_id: FG-UART
      scopes:
        - tb_top.dut.uart
      metrics:
        - line
        - cond
        - assert
      target_percent: 95
  waveform: fsdb
  reference_model: null

formal:
  engine: vc_formal
  property_sets: []
  clock: {}
  reset: {}
  cex_replay:
    enabled: true
    methodology: uvm
```

所有文件路径都相对项目根目录。项目配置、运行快照、数据库和日志不得包含许可证值、API key 或 SSH 凭据。

### 用户参考模型

参考模型只能声明为用户提供的 SV、DPI-C/C++ 或项目内外部可执行模型。例如：

```yaml
simulation:
  simulator: vcs
  uvm_version: "1.2"
  recipe:
    kind: native
  reference_model:
    kind: dpi_c
    provenance: user_provided
    sources:
      - ref/model.cpp
    include_dirs:
      - ref/include
    libraries: []
```

Agent 可以为该模型生成 DPI 或 scoreboard 适配层，但不能把 AI 猜测生成的算法当作 golden model。未接入参考模型时，生成的 scoreboard 仅检查环境活性，不等价于功能正确性签核。

### 接管已有 Makefile

Imported recipe 只允许一个已声明目标和已声明变量，不接收网页输入的 Shell 字符串。`test_variable`、`seed_variable` 和 `output_variable` 是必需的 runner 管理变量；需要网页控制覆盖率或波形时，还必须声明 `coverage_variable`、`waveform_variable` 及对应产物契约。所有 runner 管理变量必须互不相同，也不能出现在静态 `variables` 中：

```yaml
simulation:
  simulator: vcs
  uvm_version: "1.2"
  recipe:
    kind: make
    makefile: Makefile
    target: smoke
    variables:
      MODE: ci
    test_variable: TEST
    seed_variable: SEED
    output_variable: RUN_DIR
    coverage_variable: COVERAGE
    coverage_databases:
      - coverage/simv.vdb
    waveform_variable: WAVEFORM
    waveform_artifacts:
      fsdb:
        - waves.fsdb
      vpd:
        - waves.vpd
    artifacts:
      - logs/compile.log
    result_logs:
      - logs/simulation.log
    success_markers:
      - PROJECT TEST PASSED
```

平台按所选 `suite × test × seed` 生成独立 Job，并以单个 argv 参数分别传入 `TEST=<test>`、`SEED=<seed>` 和 `RUN_DIR={SESSION_DIR}`。`{SESSION_DIR}` 只能由执行内核展开成该 Job 的临时目录；成功后目录才会原子发布。

声明覆盖率能力后，平台始终传入 `COVERAGE=<value>`：关闭时为 `none`，开启时按 `line+cond+tgl+fsm+branch+assert` 的规范顺序拼接实际选择。每个 Job 只在开启覆盖率时要求并签名 `coverage_databases`，全部数据库完成后自动交给 URG 合并。声明波形能力后，平台始终传入 `WAVEFORM=none|fsdb|vpd`，并且只要求当前选中格式在 `waveform_artifacts` 中对应的产物；关闭波形时不会错误要求 FSDB 或 VPD。

`artifacts` 仅列无条件产物，不能再次列出覆盖数据库、波形或 `result_logs`。`result_logs` 会参与确定性结果解析，并与当前实际启用的无条件、覆盖率和波形产物一起写入签名清单及产物索引。网页请求了覆盖率或波形但 recipe 没有声明对应变量和产物时，项目会在启动任务前拒绝，不能静默忽略选项。

被接管脚本仍是项目拥有的可信代码。管理员应先审查目标及其依赖，并确保所有构建、覆盖数据库和波形输出都写到 `output_variable` 指定的目录。所有路径均为任务目录内的精确相对路径，不支持 glob。

## 主机工具链配置

主机管理员在 `~/.ucagent/toolchains.yaml` 或服务启动参数指定的文件中维护工具路径：

```yaml
profiles:
  synopsys_o2018:
    display_name: Synopsys O-2018.09-SP2
    tools:
      make: /usr/local/bin/make
      vcs: /opt/synopsys/vcs/bin/vcs
      urg: /opt/synopsys/vcs/bin/urg
      vcf: /opt/synopsys/vcf/bin/vcf
      verdi: /opt/synopsys/verdi/bin/verdi
      python: /opt/ucagent/venv/bin/python
    versions:
      vcs: O-2018.09-SP2
      vc_formal: O-2018.09-SP2
      uvm: "1.2"
    fsdb_pli:
      table: /opt/synopsys/verdi/share/PLI/VCS/linux64/novas.tab
      library: /opt/synopsys/verdi/share/PLI/VCS/linux64/pli.a
      runtime_library_dirs:
        - /opt/synopsys/verdi/share/PLI/lib/linux64
    license_environment_names:
      - SNPSLMD_LICENSE_FILE
      - LM_LICENSE_FILE
    max_concurrency: 1
    minimum_free_bytes: 10737418240
    execution_user: ucagent
```

`license_environment_names` 只保存变量名。变量值必须由 systemd 的临时 `EnvironmentFile`、受控登录环境或其他主机秘密机制注入进程，不能写入 YAML。执行内核不会 `source` 网页指定的脚本；需要 setup script 的工具链必须由管理员先将其解析成明确环境。

原生 VCS 生成 FSDB 时必须显式配置 `fsdb_pli.table`、`fsdb_pli.library` 和非空的 `runtime_library_dirs`。平台在编译 argv 中加入 `-P <novas.tab> <pli.a>`，在仿真 Job 的 `LD_LIBRARY_PATH` 前置声明的运行库目录，并在启动前检查文件和目录可读；不会根据 `VERDI_HOME`、当前目录或 PATH 猜测 PLI 路径。Imported recipe 仍由项目 recipe 自己声明 FSDB 产物，不注入这两个参数。

Toolchains 页的 Probe 会先读取版本，再在平台受控目录执行最小 VCS compile 和最小 VC Formal FPV，以真实许可证签出结果标记 `available`、`busy`、`unavailable` 或 `unknown`。可执行文件存在只代表安装可见，不能代替真实 compile、simulation 或 proof 验收。

## UVM 1.2 生成与验证

Projects 页可以生成 interface、transaction、sequence、sequencer、driver、monitor、agent、scoreboard、coverage、env、test、`tb_top`、package 和 filelist。发布前执行以下确定性检查：

- 文件集合和 include 顺序完整；
- 不存在 TODO、TBD 或未实现占位符；
- DUT、clock、reset 和端口连接来自用户提供的结构化信息；
- 用户参考模型的来源、文件和哈希可验证；
- 生成树具有签名 manifest；
- 后续 VCS compile 和 smoke 必须真正通过。

选择 FSDB 时，生成的 `tb_top` 通过受控 `UCAGENT_ENABLE_FSDB` 宏和 `+fsdbfile=<task-path>` 创建每个 run 独立的波形。已有环境必须实现相同的波形契约或由 Imported recipe 明确生成产物；平台不会伪造一个空 FSDB。

UT、IT 和 ST suite 分别展开为 `test × seed`。UVM `ERROR/FATAL`、断言失败和项目成功标记由确定性解析器合并判断。正确暴露 DUT 缺陷的 Fail 用例会保留并进入问题与波形证据流程，不会通过删除断言或弱化 scoreboard 获得假 Pass。

## VCS 与 URG 执行

Native 流程从 filelist、source、include、define、parameter、coverage 和 waveform 字段构造 argv。浏览器不能提交任意 Shell 命令。

典型 UVM 1.2 编译语义为：

```bash
vcs -full64 -sverilog -ntb_opts uvm-1.2 \
  -F <filelist> -top <top> -o <session>/simv
```

测试名、随机种子和普通 plusarg 分开处理：

```bash
<simv> +UVM_TESTNAME=<test> +ntb_random_seed=<seed>
```

覆盖率任务为每个测试创建独立 VDB，完成后由 URG 合并和解析。VCS 编译错误属于 `execution_status=error`；仿真进程正常结束但 UVM/断言失败属于 `execution_status=completed`、`verification_status=failed`。

`simulation.coverage_mapping` 是 URG 层次范围与规格标签之间的唯一映射来源。`requirement_id` 只能是 `FG-*`、`FC-*` 或 `CK-*`；`scopes` 使用精确层次前缀而不是 glob/正则，`metrics` 指定适用的覆盖率种类，`target_percent` 给出签核目标。没有显式映射的 URG 项会显示 `Unmapped`，Agent 不会根据模块名猜测规格关系。只有 parser 实际提供逐测试覆盖数据时才显示回归贡献，不从合并百分比虚构单个测试贡献。

## VC Formal FPV

VC Formal O-2018.09-SP2 使用固定批处理入口：

```bash
vcf -batch -no_ui -no_restore -fmode FPV \
  -out_dir <session_dir> \
  -output_log_file <console.log> \
  -f <run.tcl>
```

平台生成的 Tcl 生命周期为：

```tcl
analyze -format sverilog -vcs { -f <filelist> }
elaborate -sva <top>
create_clock ...
create_reset ...
sim_run -stable
sim_save_reset
check_fv -block
report_fv -list
report_fv -verbose
exit
```

在 O-2018 中，`report_fv -list` 与 `report_fv -verbose` 必须分别调用；将两个开关写在同一条命令会触发互斥参数错误。`-output_log_file` 使用相对于 `-out_dir` 的 `console.log`，避免旧版工具再次拼接绝对输出目录。

属性规范化为 `proven`、`falsified`、`vacuous`、`covered`、`uncovered`、`inconclusive` 和 `disabled`。`Undec` 不能被丢弃，必须映射为 `inconclusive`。

产生反例只表示 Formal 已经找到一条违例轨迹，不等于动态环境已经复现。只有 falsified 属性关联到签名 proof 目录内的精确 CEX 文件，用户又指定了实际 UVM test class 或 UnityTest pytest 路径，平台才允许创建独立动态 Run。子 Run 必须真实执行、以 `completed + failed` 暴露同一错误，并且自身签名 manifest、输入哈希和产物哈希均有效，复现状态才会变成 `reproduced`。仅存在一个 Python 函数、Markdown 说明、旧日志或执行成功但测试通过的 Run 都不能作为复现证据；RTL、测试或 CEX 被改动后，重启恢复会把证据降为 `evidence_invalid`。

网页 Run Detail 的 Formal 页可以配置这次重跑。REST 接口为 `GET /runs/{id}/counterexample-replays` 和 `POST /runs/{id}/counterexample-replays`，MCP 同步公开 `list_counterexample_replays` 与 `start_counterexample_replay`。方法学必须与源 Formal Run 的不可变 `cex_replay` 策略一致，test、suite、seed、simulator、waveform 和 plusargs 都是结构化字段。

## 执行状态与验证结论

每个 Run、Job 和 Attempt 分开保存两类状态：

| 字段 | 值 |
|---|---|
| `execution_status` | `queued`、`running`、`completed`、`error`、`timeout`、`cancelled` |
| `verification_status` | `unknown`、`passed`、`failed`、`inconclusive` |

`completed + failed` 是有效验证结果，不是基础设施崩溃。`error + unknown` 通常表示编译、许可证、磁盘、配置或进程启动问题。

## 证据与缓存

每个 EDA Job 在临时目录运行，终态证据成功校验后才原子发布。`manifest.json` 使用主机私钥签名，包含工具和版本、脱敏 argv、执行主机、test/seed/property set、输入 SHA-256、时间、状态以及产物 SHA-256。

页面中的阶段状态不是由 Agent 文本推进。实际 Job 直接驱动 compile、UT/IT/ST、URG 和所选 Formal engine；preflight、UVM 环境生成/接管、result observer、波形发布、Formal execution 与 signoff 则从持久化 Job、规范化结果和重新验证过的签名 manifest 推导。执行失败或证据缺失会留下 `error/inconclusive`，不会为了让 DAG 变绿而自动补成 Pass。

编译缓存和 proof cache 只在完整输入指纹一致且原 manifest 签名与所有产物哈希通过时复用。RTL、filelist、TB、SVA、配置、命令语义或工具版本任一变化都会产生新指纹。缓存命中也会生成属于当前 run 的新签名 manifest。

SQLite 使用 WAL，保存 Project、Workflow、Run、Stage、Job、Attempt、Event、Artifact、TestResult、CoverageMetric、FormalProperty、Issue、HumanApproval 和 AuditEvent。服务重启会把中断中的进程状态标记为可诊断终态，已完成记录、日志游标和产物索引仍可查询。

## 波形

VCD/FST 使用现有 Surfer 页面。FSDB 不在网页中转换或解析，Artifacts 页显示大小、SHA-256 和生成任务，支持 Range 下载。下载后使用本机 Verdi：

```bash
verdi -ssf <downloaded.fsdb>
```

目录型 VDB 和 proof database 作为目录产物登记，不提供伪造的单文件下载按钮。

## REST API

主要端点位于 `/api/v1`：

- `GET /workflows`
- `GET /toolchains` 和 `POST /toolchains/{id}/probe`
- `POST /projects` 和 `GET /projects`
- `GET /projects/{id}`，包含只读 `run_defaults` 草稿
- `POST /runs/preview`，接收与创建运行相同的结构化请求但不执行任务
- `POST /runs`、`GET /runs/{id}` 和 `POST /runs/{id}/cancel`
- `GET /runs/{id}/events?after=<sequence>`
- `GET /runs/{id}/tests|coverage|properties|issues|artifacts`
- `GET/POST /runs/{id}/counterexample-replays`
- `GET /artifacts/{id}/download`
- `POST /stages/{id}/approve|reject|retry`

事件接口使用 SSE 的 `id` 和 `after` 游标断线续传。文件下载支持单一 HTTP Range。所有状态变更端点执行同源检查；导入和下载路径必须位于管理员允许的根目录。

Run 响应包含不可变 `request` 和基于规范化结果的 `summary`。`progress` 是已终结 Job 占比；尚未规划 Job 时为 `null`，不表示功能覆盖率或验证收敛率。MCP 的 `preview_verification_run` 使用与网页相同的只读预检契约。

`/mcp` 是平台内嵌的 streamable-HTTP MCP 协议端点，不是浏览器页面。使用 `--mcp-enabled` 启动独立平台后，它会公开与 `/api/v1` 共用同一个 `PlatformRuntime` 的结构化工具，包括项目、工作流、工具链探测、Run 创建/取消、阶段审批和结果查询；这些工具不接受任意 Shell 字符串。请打开 `/platform/#/mcp` 查看状态、协议 URL、实际注册的工具 Schema 和可复制的客户端配置。未启用时页面会明确显示不可用，不能把普通 HTML 或 REST URL 当作已启动的 MCP 服务。

## 单机部署

发行目录必须先在有 Node 的开发机或 CI 执行前端构建，VM 运行时不需要 Node：

```bash
cd web
npm ci
npm run test
npm run build
cd ..
python -m build --wheel --outdir dist
```

将包含且只包含一个 `dist/ucagent-*.whl` 的完整发行目录解压到服务器临时目录后，以 root 仅执行安装脚本：

```bash
bash deploy/install-platform.sh <absolute-release-source> <release-id>
```

脚本不会访问 Python 包索引或 Git 仓库。它会校验 `/home/ucagent-lab` 至少有 10 GiB 可用空间，创建非 root 的 `ucagent` 账号，将已验证的 `/home/ucagent-lab/venv` 克隆到版本化 release，再离线安装本地 wheel。只有依赖检查、非 root import smoke 和服务存活检查均通过后，才原子切换 `/home/ucagent-lab/current`；失败时自动恢复旧链接和旧 systemd unit。systemd 服务只监听 `127.0.0.1:8800`，所有临时文件写入 `/home/ucagent-lab/tmp`。

默认目录：

```text
/home/ucagent-lab/releases/<release-id>
/home/ucagent-lab/current
/home/ucagent-lab/previous
/home/ucagent-lab/state
/home/ucagent-lab/workspaces
/home/ucagent-lab/artifacts
/home/ucagent-lab/tmp
/home/ucagent-lab/config/toolchains.yaml
```

快速回退到 `previous`，或回退到指定的已验证 release：

```bash
bash /home/ucagent-lab/current/deploy/rollback-platform.sh
bash /home/ucagent-lab/current/deploy/rollback-platform.sh <release-id>
```

回退目标无法持续运行时，脚本会恢复原版本。许可证连接变量只允许由 root 写入权限受限的 `/etc/ucagent/eda.env`（目录 0700、文件 0600），确保重启后仍然存在；不要复制许可证文件、SSH 密码或 API key 到 release、toolchains YAML、项目、日志或数据库。

## 故障定位

- `insufficient_disk_space`：任务启动前磁盘门禁失败；清理明确选中的旧产物或更换管理员批准的产物盘。
- `license_unavailable`：许可证未注入、队列繁忙或 feature 不可用；检查 Toolchains Probe 和管理员运行环境。
- `missing_declared_artifact`：工具退出但没有产生声明的 FSDB、VDB、proof DB 或报告；检查 TB/recipe 的产物契约，不能删除门禁来假装成功。
- `inputs_changed_during_run`：EDA 运行期间输入发生变化；冻结项目快照后重试。
- `dependency_not_completed`：前置编译或任务未完成，后续回归被跳过。
- `execution_status=completed, verification_status=failed`：工具正常工作且发现验证失败；应保留用例和证据并分析 DUT，而不是重装工具。
