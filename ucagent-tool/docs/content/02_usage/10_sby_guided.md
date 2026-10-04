
# 使用 SBY 执行原始 UCAgent 形式化流程

SBY 与 FormalMC 共用 `formal.yaml` 的 11 个主阶段、三个规格子阶段和 Check/Complete 操作。引擎相关的指导、生成器和证据检查分别实现，FormalMC 仍是默认值，不自动切换。

## 启动

使用后端 Python 3.11+ 的已安装 `ucagent` 命令，在新的形式化工作区启动：

```bash
ucagent /path/to/workspace Counter --config formal.yaml --output formal_out \
  --override runtime_options.formal_engine=sby \
  --override runtime_options.formal_toolchain=sby
```

原 FormalMC 启动方式保持不变：

```bash
ucagent /path/to/workspace Counter --config formal.yaml --output formal_out
```

也可在个人配置中填写相同的 `runtime_options`。解析后保存到非秘密 runtime_config，后续脚本不重新读取环境变量。不要直接把 FormalMC 的已有属性记录或旧工作区 Guide_Doc 当作 SBY 属性输入。

## 主机准备

执行身份的 `~/.ucagent/toolchains.yaml` 中声明 SBY profile。以下路径仅为部署示例，按本机实际路径填写；不下载商业工具，不需要商业许可证。

```yaml
profiles:
  sby:
    tools:
      sby: /opt/oss-cad-suite/bin/sby
      yosys: /opt/oss-cad-suite/bin/yosys
      yosys-smtbmc: /opt/oss-cad-suite/bin/yosys-smtbmc
      z3: /opt/oss-cad-suite/bin/z3
    environment:
      PATH: /opt/oss-cad-suite/bin:/usr/local/bin:/usr/bin:/bin
    minimum_free_bytes: 10737418240
    minimum_root_free_bytes: 1073741824
    max_concurrency: 1
```

profile 由管理员控制，不能放进 `.formal_records.yaml`。私有签名密钥自动存于 `~/.ucagent/formal-manifest.key`，不得上传到工程或复制进报告。正式部署需保护主机配置和密钥目录；本版仍是单用户研发工具，不提供多租户隔离。

## 日常操作

读取启动时复制的 `Guide_Doc/sby_workflow.md`，它含完整计数器记录示例及每阶段输入契约。维护同一个 `.formal_records.yaml`：规划→接口→FG/FC/CK→属性→环境配置→审查→覆盖→反例→Bug→总结。

- 不要求用户手写 .sby、Yosys 命令或 Shell。
- `sva_body` 是原生表达式；并发 SVA 不会被自动翻译。
- 证明检查与 Cover 检查各自执行并保留签名证据。
- 端口与实际展开结果核对；初始复位极性和周期数必须显式声明。
- 输入改变后证据失效，需要重跑并重新审查；不删除旧运行目录。
- 使用 Check/Complete 的 CLI、TUI、原始 Agent MCP 工具共享同一阶段逻辑。

TK 客户端兼容 Python 3.8。“形式化工作台”在创建时选择引擎，之后 SBY 和 FormalMC 共用“启动 / 继续 Agent”、Check/Complete、人工审核、暂停恢复及重开操作，使用原始 StageManager 和 Checker。工程师也可手动读取输入、编辑记录并审查差异。具体操作及共用 Claude Code 前置配置见[形式化 GUI 阶段工作台](11_formal_gui.md)。原有“新建运行”是已经准备好 harness 的 EDA 直接运行入口，两者不混用。

## 不能混淆的结果

SBY 的 COI 门禁显示不支持；业务 Cover 和 guard witness 单独统计。guard witness 不属于完整空洞性分析，bmc 未发现反例不属于无界证明。阶段工作完成与 passed / failed / inconclusive 的验证结论分开；未决项可以带分析报告交付，不能自动变绿。

当前自动生成范围为组合或单时钟、整数参数及展开后的整数端口宽度；完整并发 SVA、多时钟、自动白盒导出、无界活性不在本生成器支持范围内。复杂工程可继续使用已有原生 SBY harness 路径。
