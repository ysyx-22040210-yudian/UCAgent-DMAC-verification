---
name: formal-sby
description: 在原始形式化阶段中维护 FG/FC/CK 和原生 SBY 表达式，以 Check/Complete 执行并审查签名证据。
---

# 原始形式化流程的 SBY 路径

先读取 `Guide_Doc/sby_workflow.md` 的完整记录示例，然后按 CurrentTips 只修改当前阶段的 YAML 子树。

- 操作仍为规划、理解、FG/FC/CK、属性、脚本、环境、覆盖、反例、Bug、静态关联和总结。
- `sva_body` 为 Yosys 原生即时断言的表达式，不自动翻译并发 SVA。
- `sby_guard` 控制采样使能；`sby_trigger` 只声明可达性探针。不要自动添加 reset disable 或协议约束。
- 使用普通文本工具维护 `.formal_records.yaml`，不编辑派生 SV、.sby 或报告。没有技能目录也能完成相同工作。
- 在属性阶段调用 Check 生成环境，在脚本/环境/覆盖阶段调用 Check 运行或验证现有签名证据。
- 阅读 `tests/sby_coverage.json` 的精确 FG/FC/CK 对应结果；`sby_evidence.json` 只是索引，可信源为其指向并通过校验的 manifest。
- `bmc` 未发现反例仍是 inconclusive；Cover 未命中不是不可达。COI、完整空洞性与无界活性不得声称已完成。
- 真实 RTL 缺陷保留失败并填写分析，不能削弱断言或加强 Assume 来获得绿色结果。
- 最终通过 Complete 仅表示阶段工作完成；DUT 结论单独保留。动态反例必须通过实际 DUT 执行证据检查。
