
# SBY 内部迁移到 FormalMC

完成当前输入的真实 SBY prove/bmc、cover 编译与执行，保存全部草稿，在任务页点击“迁移到 FormalMC”。工具生成关联的固定版本工程并打开目标工程页；通过现有“新建运行”入口选择目标设备已配置许可证的 FormalMC 工具链。

## 检查合同

Assert/Assume 保持同沿 guard |-> body，业务 Cover 保持 guard && body，guard witness 独立保留。组合检查不增加时钟。保留历史有效条件和复位规则，不添加默认 disable iff 或额外复位约束。参数、宏、文件顺序、include 顺序和内存初始化均绑定已执行的源输入。

## 证据

conversion_report.json 保存逐 FG/FC/CK 对应表；conversion_inputs.json 校验固定输入。source_records.json 是来源规格，不能替换原生 FormalMC 工作流记录。源审批与通过状态不迁移；目标初始为尚未运行。每次目标运行独立保存结果，缺失属性结果、超时、编译或许可证错误均不能显示通过。

## 当前范围

仅接受本套 guided SBY 单时钟或组合设计。未知依赖、工具扩展或自定义验证代码须先建立经过审查的明确模型。转换器不调用模型。guard witness 命中不代表完整空洞性或 COI 覆盖，输入哈希不代表证明结论。真实 FormalMC 编译、证明和反例验收仍待目标设备执行。
