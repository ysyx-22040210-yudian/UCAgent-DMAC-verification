
# dmac SBY 形式化验证总结

## 1. 结论

- 执行引擎：SBY / SMTBMC / Z3
- 验证结论：未决
- 模式：有界模型检查；深度参数：12
- 功能范围：独立双通道DMAC：mem为64位、device为16位；N=len+1，任意haddr逐mem握手加8，低16位先传，支持背压与复位中断。
- 验收说明：本轮已执行需求规划、FG/FC/CK分解、属性实现、实际SBY运行、环境和覆盖分析、启用的反例分支、缺陷报告与静态审查，使用原生门禁完成流程。主任务12FG/48FC/88CK，63条安全断言在depth12无反例但未获无界证明，覆盖75/82；主任务与联合prove均240秒超时。四组native具体参数安全证明、两个DMAC及三个FIFO覆盖运行、七项故障对照、19次Icarus回放作为独立辅助证据保留。当前原始DUT没有已确认缺陷，不能据此宣称所有要求已证明或无缺陷。COI不支持，完整空洞性和无界活性未建立，FormalMC/VCS尚未实测。内置Agent与工程师协作完成；长YAML输出和Agent上下文限制使工程师补齐环境及最终审查，不冒称全自主Agent验收。
- 阶段完成不代表设计通过；bmc 无反例不属于无界证明。

## 2. 属性与证据

| FG | FC | CK | 类型 | 属性 | 结论 | Manifest |
|---|---|---|---|---|---|---|
| FG-API | FC-API-RESET | CK-API-RESET-INITIAL | 环境假设 | M_CK_API_RESET_INITIAL | 环境假设 | 环境假设，非证明 |
| FG-API | FC-API-HOST-WAIT | CK-API-HOST-RD-WAIT | 环境假设 | M_CK_API_HOST_RD_WAIT | 环境假设 | 环境假设，非证明 |
| FG-API | FC-API-HOST-WAIT | CK-API-HOST-WR-WAIT | 环境假设 | M_CK_API_HOST_WR_WAIT | 环境假设 | 环境假设，非证明 |
| FG-API | FC-API-DEVICE-WAIT | CK-API-DEV-RD-WAIT | 环境假设 | M_CK_API_DEV_RD_WAIT | 环境假设 | 环境假设，非证明 |
| FG-API | FC-API-DEVICE-WAIT | CK-API-DEV-WR-WAIT-REQ | 环境假设 | M_CK_API_DEV_WR_WAIT_REQ | 环境假设 | 环境假设，非证明 |
| FG-API | FC-API-DEVICE-WAIT | CK-API-DEV-WR-WAIT-DATA | 环境假设 | M_CK_API_DEV_WR_WAIT_DATA | 环境假设 | 环境假设，非证明 |
| FG-HOST | FC-HOST-ACK | CK-HOST-RD-ACK-REQ | 安全断言 | A_CK_HOST_RD_ACK_REQ | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-HOST | FC-HOST-ACK | CK-HOST-RD-ACK-REQ | 触发可达见证 | G_A_CK_HOST_RD_ACK_REQ | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-HOST | FC-HOST-ACK | CK-HOST-WR-ACK-REQ | 安全断言 | A_CK_HOST_WR_ACK_REQ | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-HOST | FC-HOST-ACK | CK-HOST-WR-ACK-REQ | 触发可达见证 | G_A_CK_HOST_WR_ACK_REQ | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-HOST | FC-HOST-LATCH | CK-HOST-RD-LATCH-ADDRESS | 安全断言 | A_CK_HOST_RD_LATCH_ADDRESS | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-HOST | FC-HOST-LATCH | CK-HOST-RD-LATCH-ADDRESS | 触发可达见证 | G_A_CK_HOST_RD_LATCH_ADDRESS | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-HOST | FC-HOST-LATCH | CK-HOST-WR-LATCH-ADDRESS | 安全断言 | A_CK_HOST_WR_LATCH_ADDRESS | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-HOST | FC-HOST-LATCH | CK-HOST-WR-LATCH-ADDRESS | 触发可达见证 | G_A_CK_HOST_WR_LATCH_ADDRESS | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-HOST | FC-HOST-BUSY | CK-HOST-RD-NO-IMMEDIATE-REACK | 安全断言 | A_CK_HOST_RD_NO_IMMEDIATE_REACK | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-HOST | FC-HOST-BUSY | CK-HOST-RD-NO-IMMEDIATE-REACK | 触发可达见证 | G_A_CK_HOST_RD_NO_IMMEDIATE_REACK | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-HOST | FC-HOST-BUSY | CK-HOST-WR-NO-IMMEDIATE-REACK | 安全断言 | A_CK_HOST_WR_NO_IMMEDIATE_REACK | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-HOST | FC-HOST-BUSY | CK-HOST-WR-NO-IMMEDIATE-REACK | 触发可达见证 | G_A_CK_HOST_WR_NO_IMMEDIATE_REACK | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-HOST | FC-HOST-NEXT | CK-HOST-RD-DONE-NO-ACK | 安全断言 | A_CK_HOST_RD_DONE_NO_ACK | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-HOST | FC-HOST-NEXT | CK-HOST-RD-DONE-NO-ACK | 触发可达见证 | G_A_CK_HOST_RD_DONE_NO_ACK | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-HOST | FC-HOST-NEXT | CK-HOST-WR-DONE-NO-ACK | 安全断言 | A_CK_HOST_WR_DONE_NO_ACK | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-HOST | FC-HOST-NEXT | CK-HOST-WR-DONE-NO-ACK | 触发可达见证 | G_A_CK_HOST_WR_DONE_NO_ACK | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-HOST | FC-HOST-NEXT | CK-HOST-RD-PENDING-AFTER-DONE | 安全断言 | A_CK_HOST_RD_PENDING_AFTER_DONE | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-HOST | FC-HOST-NEXT | CK-HOST-RD-PENDING-AFTER-DONE | 触发可达见证 | G_A_CK_HOST_RD_PENDING_AFTER_DONE | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-HOST | FC-HOST-NEXT | CK-HOST-WR-PENDING-AFTER-DONE | 安全断言 | A_CK_HOST_WR_PENDING_AFTER_DONE | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-HOST | FC-HOST-NEXT | CK-HOST-WR-PENDING-AFTER-DONE | 触发可达见证 | G_A_CK_HOST_WR_PENDING_AFTER_DONE | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-READ | FC-READ-MEM-HANDSHAKE | CK-READ-MEM-FIRST-AFTER-ACCEPT | 安全断言 | A_CK_READ_MEM_FIRST_AFTER_ACCEPT | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-READ | FC-READ-MEM-HANDSHAKE | CK-READ-MEM-FIRST-AFTER-ACCEPT | 触发可达见证 | G_A_CK_READ_MEM_FIRST_AFTER_ACCEPT | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-READ | FC-READ-DEVICE-HANDSHAKE | CK-READ-DEV-ACK-REQ | 安全断言 | A_CK_READ_DEV_ACK_REQ | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-READ | FC-READ-DEVICE-HANDSHAKE | CK-READ-DEV-ACK-REQ | 触发可达见证 | G_A_CK_READ_DEV_ACK_REQ | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-READ | FC-READ-PIPELINE | CK-READ-NO-DEV-TRANSFER-WITHOUT-REQ | 安全断言 | A_CK_READ_NO_DEV_TRANSFER_WITHOUT_REQ | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-READ | FC-READ-PIPELINE | CK-READ-NO-DEV-TRANSFER-WITHOUT-REQ | 触发可达见证 | G_A_CK_READ_NO_DEV_TRANSFER_WITHOUT_REQ | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-READ | FC-READ-PIPELINE | CK-READ-DEV-FRAGMENT-HOLD | 安全断言 | A_CK_READ_DEV_FRAGMENT_HOLD | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-READ | FC-READ-PIPELINE | CK-READ-DEV-FRAGMENT-HOLD | 触发可达见证 | G_A_CK_READ_DEV_FRAGMENT_HOLD | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-WRITE | FC-WRITE-DEVICE-HANDSHAKE | CK-WRITE-DEV-ACK-REQ | 安全断言 | A_CK_WRITE_DEV_ACK_REQ | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-WRITE | FC-WRITE-DEVICE-HANDSHAKE | CK-WRITE-DEV-ACK-REQ | 触发可达见证 | G_A_CK_WRITE_DEV_ACK_REQ | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-WRITE | FC-WRITE-MEM-HANDSHAKE | CK-WRITE-MEM-VALID-AFTER-WORD | 安全断言 | A_CK_WRITE_MEM_VALID_AFTER_WORD | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-WRITE | FC-WRITE-MEM-HANDSHAKE | CK-WRITE-MEM-VALID-AFTER-WORD | 触发可达见证 | G_A_CK_WRITE_MEM_VALID_AFTER_WORD | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-WRITE | FC-WRITE-PIPELINE | CK-WRITE-NO-DEV-TRANSFER-WITHOUT-REQ | 安全断言 | A_CK_WRITE_NO_DEV_TRANSFER_WITHOUT_REQ | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-WRITE | FC-WRITE-PIPELINE | CK-WRITE-NO-DEV-TRANSFER-WITHOUT-REQ | 触发可达见证 | G_A_CK_WRITE_NO_DEV_TRANSFER_WITHOUT_REQ | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-WRITE | FC-WRITE-PIPELINE | CK-WRITE-STALLED-WORD-NOT-OVERWRITTEN | 安全断言 | A_CK_WRITE_STALLED_WORD_NOT_OVERWRITTEN | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-WRITE | FC-WRITE-PIPELINE | CK-WRITE-STALLED-WORD-NOT-OVERWRITTEN | 触发可达见证 | G_A_CK_WRITE_STALLED_WORD_NOT_OVERWRITTEN | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-ADDRESS | FC-ADDRESS-FIRST | CK-ADDRESS-RD-FIRST | 安全断言 | A_CK_ADDRESS_RD_FIRST | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-ADDRESS | FC-ADDRESS-FIRST | CK-ADDRESS-RD-FIRST | 触发可达见证 | G_A_CK_ADDRESS_RD_FIRST | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-ADDRESS | FC-ADDRESS-FIRST | CK-ADDRESS-WR-FIRST | 安全断言 | A_CK_ADDRESS_WR_FIRST | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-ADDRESS | FC-ADDRESS-FIRST | CK-ADDRESS-WR-FIRST | 触发可达见证 | G_A_CK_ADDRESS_WR_FIRST | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-ADDRESS | FC-ADDRESS-STEP | CK-ADDRESS-RD-STEP | 安全断言 | A_CK_ADDRESS_RD_STEP | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-ADDRESS | FC-ADDRESS-STEP | CK-ADDRESS-RD-STEP | 触发可达见证 | G_A_CK_ADDRESS_RD_STEP | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-ADDRESS | FC-ADDRESS-STEP | CK-ADDRESS-WR-STEP | 安全断言 | A_CK_ADDRESS_WR_STEP | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-ADDRESS | FC-ADDRESS-STEP | CK-ADDRESS-WR-STEP | 触发可达见证 | G_A_CK_ADDRESS_WR_STEP | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-ADDRESS | FC-ADDRESS-HOLD | CK-ADDRESS-RD-HOLD | 安全断言 | A_CK_ADDRESS_RD_HOLD | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-ADDRESS | FC-ADDRESS-HOLD | CK-ADDRESS-RD-HOLD | 触发可达见证 | G_A_CK_ADDRESS_RD_HOLD | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-ADDRESS | FC-ADDRESS-HOLD | CK-ADDRESS-WR-HOLD | 安全断言 | A_CK_ADDRESS_WR_HOLD | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-ADDRESS | FC-ADDRESS-HOLD | CK-ADDRESS-WR-HOLD | 触发可达见证 | G_A_CK_ADDRESS_WR_HOLD | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-ADDRESS | FC-ADDRESS-WRAP | CK-ADDRESS-RD-WRAP | 安全断言 | A_CK_ADDRESS_RD_WRAP | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-ADDRESS | FC-ADDRESS-WRAP | CK-ADDRESS-RD-WRAP | 触发可达见证 | G_A_CK_ADDRESS_RD_WRAP | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-ADDRESS | FC-ADDRESS-WRAP | CK-ADDRESS-WR-WRAP | 安全断言 | A_CK_ADDRESS_WR_WRAP | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-ADDRESS | FC-ADDRESS-WRAP | CK-ADDRESS-WR-WRAP | 触发可达见证 | G_A_CK_ADDRESS_WR_WRAP | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-QUOTA | FC-QUOTA-ENCODING | CK-QUOTA-ENCODING-BOUNDARY | 安全断言 | A_CK_QUOTA_ENCODING_BOUNDARY | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-QUOTA | FC-QUOTA-ENCODING | CK-QUOTA-ENCODING-BOUNDARY | 触发可达见证 | G_A_CK_QUOTA_ENCODING_BOUNDARY | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-QUOTA | FC-QUOTA-ZERO | CK-QUOTA-RD-ZERO | 安全断言 | A_CK_QUOTA_RD_ZERO | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-QUOTA | FC-QUOTA-ZERO | CK-QUOTA-RD-ZERO | 触发可达见证 | G_A_CK_QUOTA_RD_ZERO | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-QUOTA | FC-QUOTA-ZERO | CK-QUOTA-WR-ZERO | 安全断言 | A_CK_QUOTA_WR_ZERO | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-QUOTA | FC-QUOTA-ZERO | CK-QUOTA-WR-ZERO | 触发可达见证 | G_A_CK_QUOTA_WR_ZERO | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-QUOTA | FC-QUOTA-LONG | CK-QUOTA-RD-LEN1 | 安全断言 | A_CK_QUOTA_RD_LEN1 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-QUOTA | FC-QUOTA-LONG | CK-QUOTA-RD-LEN1 | 触发可达见证 | G_A_CK_QUOTA_RD_LEN1 | 未命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-QUOTA | FC-QUOTA-LONG | CK-QUOTA-WR-LEN1 | 安全断言 | A_CK_QUOTA_WR_LEN1 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-QUOTA | FC-QUOTA-LONG | CK-QUOTA-WR-LEN1 | 触发可达见证 | G_A_CK_QUOTA_WR_LEN1 | 未命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-DATA | FC-DATA-READ-FIRST | CK-DATA-RD-LOW-FIRST | 安全断言 | A_CK_DATA_RD_LOW_FIRST | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-DATA | FC-DATA-READ-FIRST | CK-DATA-RD-LOW-FIRST | 触发可达见证 | G_A_CK_DATA_RD_LOW_FIRST | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-DATA | FC-DATA-READ-LANES | CK-DATA-RD-FOUR-LANES | 安全断言 | A_CK_DATA_RD_FOUR_LANES | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-DATA | FC-DATA-READ-LANES | CK-DATA-RD-FOUR-LANES | 触发可达见证 | G_A_CK_DATA_RD_FOUR_LANES | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-DATA | FC-DATA-WRITE-PACK | CK-DATA-WR-FOUR-LANES | 安全断言 | A_CK_DATA_WR_FOUR_LANES | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-DATA | FC-DATA-WRITE-PACK | CK-DATA-WR-FOUR-LANES | 触发可达见证 | G_A_CK_DATA_WR_FOUR_LANES | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-DATA | FC-DATA-ORDER-BOUNDARY | CK-DATA-RD-TWO-WORD-LOCAL-ORDER | 安全断言 | A_CK_DATA_RD_TWO_WORD_LOCAL_ORDER | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-DATA | FC-DATA-ORDER-BOUNDARY | CK-DATA-RD-TWO-WORD-LOCAL-ORDER | 触发可达见证 | G_A_CK_DATA_RD_TWO_WORD_LOCAL_ORDER | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-DATA | FC-DATA-ORDER-BOUNDARY | CK-DATA-WR-TWO-WORD-LOCAL-ORDER | 安全断言 | A_CK_DATA_WR_TWO_WORD_LOCAL_ORDER | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-DATA | FC-DATA-ORDER-BOUNDARY | CK-DATA-WR-TWO-WORD-LOCAL-ORDER | 触发可达见证 | G_A_CK_DATA_WR_TWO_WORD_LOCAL_ORDER | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-FLOW | FC-FLOW-READ-STALL | CK-FLOW-RD-VALID-ADDRESS-HOLD | 安全断言 | A_CK_FLOW_RD_VALID_ADDRESS_HOLD | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-FLOW | FC-FLOW-READ-STALL | CK-FLOW-RD-VALID-ADDRESS-HOLD | 触发可达见证 | G_A_CK_FLOW_RD_VALID_ADDRESS_HOLD | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-FLOW | FC-FLOW-WRITE-STALL | CK-FLOW-WR-VALID-ADDRESS-DATA-HOLD | 安全断言 | A_CK_FLOW_WR_VALID_ADDRESS_DATA_HOLD | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-FLOW | FC-FLOW-WRITE-STALL | CK-FLOW-WR-VALID-ADDRESS-DATA-HOLD | 触发可达见证 | G_A_CK_FLOW_WR_VALID_ADDRESS_DATA_HOLD | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-FLOW | FC-FLOW-DEVICE-GATING | CK-FLOW-DEV-RD-ACK-GATED | 安全断言 | A_CK_FLOW_DEV_RD_ACK_GATED | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-FLOW | FC-FLOW-DEVICE-GATING | CK-FLOW-DEV-RD-ACK-GATED | 触发可达见证 | G_A_CK_FLOW_DEV_RD_ACK_GATED | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-FLOW | FC-FLOW-DEVICE-GATING | CK-FLOW-DEV-WR-ACK-GATED | 安全断言 | A_CK_FLOW_DEV_WR_ACK_GATED | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-FLOW | FC-FLOW-DEVICE-GATING | CK-FLOW-DEV-WR-ACK-GATED | 触发可达见证 | G_A_CK_FLOW_DEV_WR_ACK_GATED | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-FLOW | FC-FLOW-BUFFER-BOUNDARY | CK-FLOW-BUFFER-WR-VISIBLE-HOLD | 安全断言 | A_CK_FLOW_BUFFER_WR_VISIBLE_HOLD | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-FLOW | FC-FLOW-BUFFER-BOUNDARY | CK-FLOW-BUFFER-WR-VISIBLE-HOLD | 触发可达见证 | G_A_CK_FLOW_BUFFER_WR_VISIBLE_HOLD | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-FLOW | FC-FLOW-BUFFER-BOUNDARY | CK-FLOW-BUFFER-NO-SPURIOUS-DEV-ACK | 安全断言 | A_CK_FLOW_BUFFER_NO_SPURIOUS_DEV_ACK | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-FLOW | FC-FLOW-BUFFER-BOUNDARY | CK-FLOW-BUFFER-NO-SPURIOUS-DEV-ACK | 触发可达见证 | G_A_CK_FLOW_BUFFER_NO_SPURIOUS_DEV_ACK | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-RESET | FC-RESET-SILENCE | CK-RESET-HOST-SILENCE | 安全断言 | A_CK_RESET_HOST_SILENCE | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-RESET | FC-RESET-SILENCE | CK-RESET-HOST-SILENCE | 触发可达见证 | G_A_CK_RESET_HOST_SILENCE | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-RESET | FC-RESET-SILENCE | CK-RESET-DATA-CHANNEL-SILENCE | 安全断言 | A_CK_RESET_DATA_CHANNEL_SILENCE | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-RESET | FC-RESET-SILENCE | CK-RESET-DATA-CHANNEL-SILENCE | 触发可达见证 | G_A_CK_RESET_DATA_CHANNEL_SILENCE | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-RESET | FC-RESET-INTERRUPT | CK-RESET-INTERRUPT-RD-STALL | 安全断言 | A_CK_RESET_INTERRUPT_RD_STALL | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-RESET | FC-RESET-INTERRUPT | CK-RESET-INTERRUPT-RD-STALL | 触发可达见证 | G_A_CK_RESET_INTERRUPT_RD_STALL | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-RESET | FC-RESET-INTERRUPT | CK-RESET-INTERRUPT-WR-STALL | 安全断言 | A_CK_RESET_INTERRUPT_WR_STALL | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-RESET | FC-RESET-INTERRUPT | CK-RESET-INTERRUPT-WR-STALL | 触发可达见证 | G_A_CK_RESET_INTERRUPT_WR_STALL | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-RESET | FC-RESET-INTERRUPT | CK-RESET-INTERRUPT-DEVICE-PARTIAL | 安全断言 | A_CK_RESET_INTERRUPT_DEVICE_PARTIAL | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-RESET | FC-RESET-INTERRUPT | CK-RESET-INTERRUPT-DEVICE-PARTIAL | 触发可达见证 | G_A_CK_RESET_INTERRUPT_DEVICE_PARTIAL | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-RESET | FC-RESET-NO-DONE | CK-RESET-RD-DONE-CLEAR | 安全断言 | A_CK_RESET_RD_DONE_CLEAR | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-RESET | FC-RESET-NO-DONE | CK-RESET-RD-DONE-CLEAR | 触发可达见证 | G_A_CK_RESET_RD_DONE_CLEAR | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-RESET | FC-RESET-NO-DONE | CK-RESET-WR-DONE-CLEAR | 安全断言 | A_CK_RESET_WR_DONE_CLEAR | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-RESET | FC-RESET-NO-DONE | CK-RESET-WR-DONE-CLEAR | 触发可达见证 | G_A_CK_RESET_WR_DONE_CLEAR | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-RESET | FC-RESET-RESTART | CK-RESET-RD-RESTART-ADDRESS | 安全断言 | A_CK_RESET_RD_RESTART_ADDRESS | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-RESET | FC-RESET-RESTART | CK-RESET-RD-RESTART-ADDRESS | 触发可达见证 | G_A_CK_RESET_RD_RESTART_ADDRESS | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-RESET | FC-RESET-RESTART | CK-RESET-WR-RESTART-ADDRESS | 安全断言 | A_CK_RESET_WR_RESTART_ADDRESS | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-RESET | FC-RESET-RESTART | CK-RESET-WR-RESTART-ADDRESS | 触发可达见证 | G_A_CK_RESET_WR_RESTART_ADDRESS | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-CONCURRENT | FC-CONCURRENT-ACCEPT | CK-CONCURRENT-ACCEPT-AFTER-RESET | 安全断言 | A_CK_CONCURRENT_ACCEPT_AFTER_RESET | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-CONCURRENT | FC-CONCURRENT-ACCEPT | CK-CONCURRENT-ACCEPT-AFTER-RESET | 触发可达见证 | G_A_CK_CONCURRENT_ACCEPT_AFTER_RESET | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-CONCURRENT | FC-CONCURRENT-TRANSFER | CK-CONCURRENT-MEM-TRANSFER | 业务覆盖 | C_CK_CONCURRENT_MEM_TRANSFER | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-CONCURRENT | FC-CONCURRENT-TRANSFER | CK-CONCURRENT-DEVICE-TRANSFER | 业务覆盖 | C_CK_CONCURRENT_DEVICE_TRANSFER | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-CONCURRENT | FC-CONCURRENT-STALL | CK-CONCURRENT-RD-STALL-WR-HANDSHAKE | 安全断言 | A_CK_CONCURRENT_RD_STALL_WR_HANDSHAKE | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-CONCURRENT | FC-CONCURRENT-STALL | CK-CONCURRENT-RD-STALL-WR-HANDSHAKE | 触发可达见证 | G_A_CK_CONCURRENT_RD_STALL_WR_HANDSHAKE | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-CONCURRENT | FC-CONCURRENT-STALL | CK-CONCURRENT-WR-STALL-RD-HANDSHAKE | 安全断言 | A_CK_CONCURRENT_WR_STALL_RD_HANDSHAKE | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-CONCURRENT | FC-CONCURRENT-STALL | CK-CONCURRENT-WR-STALL-RD-HANDSHAKE | 触发可达见证 | G_A_CK_CONCURRENT_WR_STALL_RD_HANDSHAKE | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-CONCURRENT | FC-CONCURRENT-DONE | CK-CONCURRENT-SIMULTANEOUS-DONE | 安全断言 | A_CK_CONCURRENT_SIMULTANEOUS_DONE | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-CONCURRENT | FC-CONCURRENT-DONE | CK-CONCURRENT-SIMULTANEOUS-DONE | 触发可达见证 | G_A_CK_CONCURRENT_SIMULTANEOUS_DONE | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-DONE | FC-DONE-PULSE | CK-DONE-RD-ONE-CYCLE | 安全断言 | A_CK_DONE_RD_ONE_CYCLE | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-DONE | FC-DONE-PULSE | CK-DONE-RD-ONE-CYCLE | 触发可达见证 | G_A_CK_DONE_RD_ONE_CYCLE | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-DONE | FC-DONE-PULSE | CK-DONE-WR-ONE-CYCLE | 安全断言 | A_CK_DONE_WR_ONE_CYCLE | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-DONE | FC-DONE-PULSE | CK-DONE-WR-ONE-CYCLE | 触发可达见证 | G_A_CK_DONE_WR_ONE_CYCLE | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-DONE | FC-DONE-READ-CAUSE | CK-DONE-RD-PREV-DEV-HANDSHAKE | 安全断言 | A_CK_DONE_RD_PREV_DEV_HANDSHAKE | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-DONE | FC-DONE-READ-CAUSE | CK-DONE-RD-PREV-DEV-HANDSHAKE | 触发可达见证 | G_A_CK_DONE_RD_PREV_DEV_HANDSHAKE | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-DONE | FC-DONE-WRITE-CAUSE | CK-DONE-WR-PREV-MEM-HANDSHAKE | 安全断言 | A_CK_DONE_WR_PREV_MEM_HANDSHAKE | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-DONE | FC-DONE-WRITE-CAUSE | CK-DONE-WR-PREV-MEM-HANDSHAKE | 触发可达见证 | G_A_CK_DONE_WR_PREV_MEM_HANDSHAKE | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-DONE | FC-DONE-ACK-GAP | CK-DONE-RD-NO-ACK | 安全断言 | A_CK_DONE_RD_NO_ACK | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-DONE | FC-DONE-ACK-GAP | CK-DONE-RD-NO-ACK | 触发可达见证 | G_A_CK_DONE_RD_NO_ACK | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-DONE | FC-DONE-ACK-GAP | CK-DONE-WR-NO-ACK | 安全断言 | A_CK_DONE_WR_NO_ACK | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-DONE | FC-DONE-ACK-GAP | CK-DONE-WR-NO-ACK | 触发可达见证 | G_A_CK_DONE_WR_NO_ACK | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-DONE | FC-DONE-ACK-GAP | CK-DONE-RD-NEXT-ACK | 安全断言 | A_CK_DONE_RD_NEXT_ACK | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-DONE | FC-DONE-ACK-GAP | CK-DONE-RD-NEXT-ACK | 触发可达见证 | G_A_CK_DONE_RD_NEXT_ACK | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-DONE | FC-DONE-ACK-GAP | CK-DONE-WR-NEXT-ACK | 安全断言 | A_CK_DONE_WR_NEXT_ACK | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| FG-DONE | FC-DONE-ACK-GAP | CK-DONE-WR-NEXT-ACK | 触发可达见证 | G_A_CK_DONE_WR_NEXT_ACK | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-COVERAGE | FC-COVER-NONALIGNED | CK-COVER-RD-NONALIGNED | 业务覆盖 | C_CK_COVER_RD_NONALIGNED | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-COVERAGE | FC-COVER-NONALIGNED | CK-COVER-WR-NONALIGNED | 业务覆盖 | C_CK_COVER_WR_NONALIGNED | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-COVERAGE | FC-COVER-ZERO | CK-COVER-RD-LEN0-COMPLETE | 业务覆盖 | C_CK_COVER_RD_LEN0_COMPLETE | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-COVERAGE | FC-COVER-ZERO | CK-COVER-WR-LEN0-COMPLETE | 业务覆盖 | C_CK_COVER_WR_LEN0_COMPLETE | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-COVERAGE | FC-COVER-LONG | CK-COVER-RD-LEN1 | 业务覆盖 | C_CK_COVER_RD_LEN1 | 未命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-COVERAGE | FC-COVER-LONG | CK-COVER-WR-LEN1 | 业务覆盖 | C_CK_COVER_WR_LEN1 | 未命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-COVERAGE | FC-COVER-LONG | CK-COVER-RD-LONGER-PROGRESS | 业务覆盖 | C_CK_COVER_RD_LONGER_PROGRESS | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-COVERAGE | FC-COVER-LONG | CK-COVER-WR-LONGER-PROGRESS | 业务覆盖 | C_CK_COVER_WR_LONGER_PROGRESS | 未命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-COVERAGE | FC-COVER-THREE-COMMANDS | CK-COVER-RD-THREE-COMMANDS | 业务覆盖 | C_CK_COVER_RD_THREE_COMMANDS | 未命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-COVERAGE | FC-COVER-THREE-COMMANDS | CK-COVER-WR-THREE-COMMANDS | 业务覆盖 | C_CK_COVER_WR_THREE_COMMANDS | 未命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-COVERAGE | FC-COVER-PENDING | CK-COVER-RD-PENDING-NEXT | 业务覆盖 | C_CK_COVER_RD_PENDING_NEXT | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-COVERAGE | FC-COVER-PENDING | CK-COVER-WR-PENDING-NEXT | 业务覆盖 | C_CK_COVER_WR_PENDING_NEXT | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-COVERAGE | FC-COVER-RESET-REENTRY | CK-COVER-RESET-RD-STALL | 业务覆盖 | C_CK_COVER_RESET_RD_STALL | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-COVERAGE | FC-COVER-RESET-REENTRY | CK-COVER-RESET-WR-STALL | 业务覆盖 | C_CK_COVER_RESET_WR_STALL | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-COVERAGE | FC-COVER-RESET-REENTRY | CK-COVER-RESET-PARTIAL-FRAGMENT | 业务覆盖 | C_CK_COVER_RESET_PARTIAL_FRAGMENT | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-COVERAGE | FC-COVER-DUPLEX | CK-COVER-DUPLEX-OVERLAP | 业务覆盖 | C_CK_COVER_DUPLEX_OVERLAP | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| FG-COVERAGE | FC-COVER-SIMULTANEOUS-DONE | CK-COVER-SIMULTANEOUS-DONE | 业务覆盖 | C_CK_COVER_SIMULTANEOUS_DONE | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |


## 3. 覆盖与限制

- Cover 与 guard witness：75 / 82。
- COI：不支持；不计算 FormalMC 的 nets/dffs 覆盖百分比。
- 空洞性：未建立。guard witness 仅说明所写使能和探针可达，不是完整空洞性证明。
- 无界活性：未建立；本路径只运行安全属性和有界可达性。
- 未命中不等于不可达，不更改覆盖分母。
- 动态反例复现：仅以独立的 counterexample_replay_evidence.json 校验结果为准，本总结不自动认定已复现。
