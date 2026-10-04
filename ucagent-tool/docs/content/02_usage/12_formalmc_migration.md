
# SBY 工程内部迁移到 FormalMC

打开已执行的 guided SBY 任务，保存草稿后点击“迁移到 FormalMC”。工具核对当前输入与 SBY 执行证据，生成固定版本的 FormalMC 工程，并直接打开工程页。整个操作在工具内部完成。

## 使用

1. 完成当前 RTL、属性与配置的 SBY prove/bmc、cover 编译和执行。失败或未决结果也可以迁移。
2. 保存全部文件和日志草稿，点击“迁移到 FormalMC”。输入过期、依赖缺失、未编译或存在未知转换含义时，修复提示的问题并重新 Check。
3. 在目标工程页查看来源 SBY 任务、源版本及独立运行记录。来源按钮可返回 SBY 任务。
4. 配置目标设备的 FormalMC 工具链，点击现有“新建运行”。迁移本身不调用模型，也不启动证明或消耗许可证。

同一份输入的重复点击打开已有目标工程；源输入更新且完成新的 SBY Check 后，生成新版本目标。源任务、审批和执行记录继续保留，目标初始为尚未运行，不继承 SBY 通过结论。

## 转换与记录

时序 Assert/Assume 保持同沿 guard |-> body，业务 Cover 保持 guard && body，guard witness 独立保留。组合检查不增加时钟。保留 $past、历史有效条件和 none/initial/unconstrained 复位规则，不增加默认 disable iff 或源工程未定义的约束。

生成工程保留 RTL、必要依赖、规格、参数、宏及 include 顺序，包含 checker/wrapper、Tcl、逐 FG/FC/CK 转换报告和输入哈希清单。内存初始化路径改为工程内相对路径并逐项记录。第一版仅支持本套 guided SBY 单时钟或组合设计；未知工具扩展、自定义验证代码和未解析依赖会阻止迁移并定位文件或 CK。

目标工程通过既有 FormalMC 适配器运行，每次独立保存版本、日志、逐属性结果和反例。所有转换检查及 guard witness 均需获得可识别结果；缺失、超时、编译或许可证失败不会显示为通过。用户可以选择目标工具链，固定转换输入发生变化时需要新建迁移。

## API

POST /api/v1/formal-sessions/{id}/migrate-formalmc 接受 revision、request_id。响应包含 project、migration 来源记录和更新后的源 session。项目登记、迁移回执、请求去重及源事件一起提交；失败不保留可见的半成品工程。请求参数冲突、版本过期、任务运行中和目标输入被修改时，返回具体原因。

## 验收边界

conversion_status=checked 表示确定性转换检查通过，目标初始验证状态为 not_run。SBY 回归、VCS 编译/回放与真实 FormalMC 验收分别记录。当前尚无 FormalMC 设备，实际 Tcl/SVA 编译、证明和反例验收须在目标机补做。
