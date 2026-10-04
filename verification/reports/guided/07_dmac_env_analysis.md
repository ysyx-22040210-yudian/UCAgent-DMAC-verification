
# dmac SBY 形式化验证环境分析报告

## 1. 当前工具结论

- 验证结论：未决
- 执行模式：bmc，深度 12
- COI：不支持；空洞性与无界活性：未建立。
- 业务 Cover 与 guard witness 缺口不归为 RTL 缺陷。

## 2. 属性分类与证据

| 属性 | 类型 | 结果 | Manifest |
|---|---|---|---|
| M_CK_API_RESET_INITIAL | 环境假设 | 环境假设 | 假设，非证明 |
| M_CK_API_HOST_RD_WAIT | 环境假设 | 环境假设 | 假设，非证明 |
| M_CK_API_HOST_WR_WAIT | 环境假设 | 环境假设 | 假设，非证明 |
| M_CK_API_DEV_RD_WAIT | 环境假设 | 环境假设 | 假设，非证明 |
| M_CK_API_DEV_WR_WAIT_REQ | 环境假设 | 环境假设 | 假设，非证明 |
| M_CK_API_DEV_WR_WAIT_DATA | 环境假设 | 环境假设 | 假设，非证明 |
| A_CK_HOST_RD_ACK_REQ | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_HOST_RD_ACK_REQ | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_HOST_WR_ACK_REQ | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_HOST_WR_ACK_REQ | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_HOST_RD_LATCH_ADDRESS | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_HOST_RD_LATCH_ADDRESS | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_HOST_WR_LATCH_ADDRESS | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_HOST_WR_LATCH_ADDRESS | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_HOST_RD_NO_IMMEDIATE_REACK | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_HOST_RD_NO_IMMEDIATE_REACK | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_HOST_WR_NO_IMMEDIATE_REACK | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_HOST_WR_NO_IMMEDIATE_REACK | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_HOST_RD_DONE_NO_ACK | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_HOST_RD_DONE_NO_ACK | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_HOST_WR_DONE_NO_ACK | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_HOST_WR_DONE_NO_ACK | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_HOST_RD_PENDING_AFTER_DONE | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_HOST_RD_PENDING_AFTER_DONE | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_HOST_WR_PENDING_AFTER_DONE | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_HOST_WR_PENDING_AFTER_DONE | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_READ_MEM_FIRST_AFTER_ACCEPT | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_READ_MEM_FIRST_AFTER_ACCEPT | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_READ_DEV_ACK_REQ | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_READ_DEV_ACK_REQ | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_READ_NO_DEV_TRANSFER_WITHOUT_REQ | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_READ_NO_DEV_TRANSFER_WITHOUT_REQ | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_READ_DEV_FRAGMENT_HOLD | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_READ_DEV_FRAGMENT_HOLD | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_WRITE_DEV_ACK_REQ | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_WRITE_DEV_ACK_REQ | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_WRITE_MEM_VALID_AFTER_WORD | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_WRITE_MEM_VALID_AFTER_WORD | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_WRITE_NO_DEV_TRANSFER_WITHOUT_REQ | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_WRITE_NO_DEV_TRANSFER_WITHOUT_REQ | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_WRITE_STALLED_WORD_NOT_OVERWRITTEN | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_WRITE_STALLED_WORD_NOT_OVERWRITTEN | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_ADDRESS_RD_FIRST | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_ADDRESS_RD_FIRST | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_ADDRESS_WR_FIRST | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_ADDRESS_WR_FIRST | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_ADDRESS_RD_STEP | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_ADDRESS_RD_STEP | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_ADDRESS_WR_STEP | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_ADDRESS_WR_STEP | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_ADDRESS_RD_HOLD | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_ADDRESS_RD_HOLD | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_ADDRESS_WR_HOLD | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_ADDRESS_WR_HOLD | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_ADDRESS_RD_WRAP | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_ADDRESS_RD_WRAP | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_ADDRESS_WR_WRAP | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_ADDRESS_WR_WRAP | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_QUOTA_ENCODING_BOUNDARY | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_QUOTA_ENCODING_BOUNDARY | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_QUOTA_RD_ZERO | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_QUOTA_RD_ZERO | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_QUOTA_WR_ZERO | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_QUOTA_WR_ZERO | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_QUOTA_RD_LEN1 | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_QUOTA_RD_LEN1 | 触发可达见证 | 未命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_QUOTA_WR_LEN1 | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_QUOTA_WR_LEN1 | 触发可达见证 | 未命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_DATA_RD_LOW_FIRST | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_DATA_RD_LOW_FIRST | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_DATA_RD_FOUR_LANES | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_DATA_RD_FOUR_LANES | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_DATA_WR_FOUR_LANES | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_DATA_WR_FOUR_LANES | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_DATA_RD_TWO_WORD_LOCAL_ORDER | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_DATA_RD_TWO_WORD_LOCAL_ORDER | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_DATA_WR_TWO_WORD_LOCAL_ORDER | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_DATA_WR_TWO_WORD_LOCAL_ORDER | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_FLOW_RD_VALID_ADDRESS_HOLD | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_FLOW_RD_VALID_ADDRESS_HOLD | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_FLOW_WR_VALID_ADDRESS_DATA_HOLD | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_FLOW_WR_VALID_ADDRESS_DATA_HOLD | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_FLOW_DEV_RD_ACK_GATED | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_FLOW_DEV_RD_ACK_GATED | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_FLOW_DEV_WR_ACK_GATED | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_FLOW_DEV_WR_ACK_GATED | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_FLOW_BUFFER_WR_VISIBLE_HOLD | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_FLOW_BUFFER_WR_VISIBLE_HOLD | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_FLOW_BUFFER_NO_SPURIOUS_DEV_ACK | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_FLOW_BUFFER_NO_SPURIOUS_DEV_ACK | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_RESET_HOST_SILENCE | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_RESET_HOST_SILENCE | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_RESET_DATA_CHANNEL_SILENCE | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_RESET_DATA_CHANNEL_SILENCE | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_RESET_INTERRUPT_RD_STALL | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_RESET_INTERRUPT_RD_STALL | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_RESET_INTERRUPT_WR_STALL | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_RESET_INTERRUPT_WR_STALL | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_RESET_INTERRUPT_DEVICE_PARTIAL | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_RESET_INTERRUPT_DEVICE_PARTIAL | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_RESET_RD_DONE_CLEAR | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_RESET_RD_DONE_CLEAR | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_RESET_WR_DONE_CLEAR | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_RESET_WR_DONE_CLEAR | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_RESET_RD_RESTART_ADDRESS | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_RESET_RD_RESTART_ADDRESS | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_RESET_WR_RESTART_ADDRESS | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_RESET_WR_RESTART_ADDRESS | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_CONCURRENT_ACCEPT_AFTER_RESET | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_CONCURRENT_ACCEPT_AFTER_RESET | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| C_CK_CONCURRENT_MEM_TRANSFER | 业务覆盖 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| C_CK_CONCURRENT_DEVICE_TRANSFER | 业务覆盖 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_CONCURRENT_RD_STALL_WR_HANDSHAKE | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_CONCURRENT_RD_STALL_WR_HANDSHAKE | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_CONCURRENT_WR_STALL_RD_HANDSHAKE | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_CONCURRENT_WR_STALL_RD_HANDSHAKE | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_CONCURRENT_SIMULTANEOUS_DONE | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_CONCURRENT_SIMULTANEOUS_DONE | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_DONE_RD_ONE_CYCLE | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_DONE_RD_ONE_CYCLE | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_DONE_WR_ONE_CYCLE | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_DONE_WR_ONE_CYCLE | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_DONE_RD_PREV_DEV_HANDSHAKE | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_DONE_RD_PREV_DEV_HANDSHAKE | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_DONE_WR_PREV_MEM_HANDSHAKE | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_DONE_WR_PREV_MEM_HANDSHAKE | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_DONE_RD_NO_ACK | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_DONE_RD_NO_ACK | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_DONE_WR_NO_ACK | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_DONE_WR_NO_ACK | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_DONE_RD_NEXT_ACK | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_DONE_RD_NEXT_ACK | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| A_CK_DONE_WR_NEXT_ACK | 安全断言 | 未决 | formal_out/tests/sby_runs/sby-872c6e8dd8bc4642988787232188507c/manifest.json |
| G_A_CK_DONE_WR_NEXT_ACK | 触发可达见证 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| C_CK_COVER_RD_NONALIGNED | 业务覆盖 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| C_CK_COVER_WR_NONALIGNED | 业务覆盖 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| C_CK_COVER_RD_LEN0_COMPLETE | 业务覆盖 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| C_CK_COVER_WR_LEN0_COMPLETE | 业务覆盖 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| C_CK_COVER_RD_LEN1 | 业务覆盖 | 未命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| C_CK_COVER_WR_LEN1 | 业务覆盖 | 未命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| C_CK_COVER_RD_LONGER_PROGRESS | 业务覆盖 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| C_CK_COVER_WR_LONGER_PROGRESS | 业务覆盖 | 未命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| C_CK_COVER_RD_THREE_COMMANDS | 业务覆盖 | 未命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| C_CK_COVER_WR_THREE_COMMANDS | 业务覆盖 | 未命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| C_CK_COVER_RD_PENDING_NEXT | 业务覆盖 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| C_CK_COVER_WR_PENDING_NEXT | 业务覆盖 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| C_CK_COVER_RESET_RD_STALL | 业务覆盖 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| C_CK_COVER_RESET_WR_STALL | 业务覆盖 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| C_CK_COVER_RESET_PARTIAL_FRAGMENT | 业务覆盖 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| C_CK_COVER_DUPLEX_OVERLAP | 业务覆盖 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |
| C_CK_COVER_SIMULTANEOUS_DONE | 业务覆盖 | 已命中 | formal_out/tests/sby_runs/sby-36b62d07a5ac4849952f6b3aca922448/manifest.json |


## 3. 问题审查



### FA-A_CK_HOST_RD_ACK_REQ — A_CK_HOST_RD_ACK_REQ

- 分类：INCONCLUSIVE
- 分析：对应 R02；当 host_rd_ack 为高时触发，期望同拍 host_rd_req 与 rst_n 均为高，禁止无请求或复位中确认读命令。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_HOST_WR_ACK_REQ — A_CK_HOST_WR_ACK_REQ

- 分类：INCONCLUSIVE
- 分析：对应 R02；当 host_wr_ack 为高时触发，期望同拍 host_wr_req 与 rst_n 均为高，禁止无请求或复位中确认写命令。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_HOST_RD_LATCH_ADDRESS — A_CK_HOST_RD_LATCH_ADDRESS

- 分类：INCONCLUSIVE
- 分析：对应 R02、R03；读命令接受后的紧邻周期出现首个 mem_rd_valid 且两拍 rst_n 均高时，期望 mem_rd_addr 等于接受沿 host_rd_haddr；只检查无等待的一拍固定窗口。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_HOST_WR_LATCH_ADDRESS — A_CK_HOST_WR_LATCH_ADDRESS

- 分类：INCONCLUSIVE
- 分析：对应 R02、R03；写命令接受后紧接四拍连续 device 写握手，并在再下一拍首次出现 mem_wr_valid 的固定窗口中，期望 mem_wr_addr 等于接受沿 host_wr_haddr；任意等待下的锁存归 native 模型。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_HOST_RD_NO_IMMEDIATE_REACK — A_CK_HOST_RD_NO_IMMEDIATE_REACK

- 分类：INCONCLUSIVE
- 分析：对应 R02；当前一采样沿接受读命令、本采样尚未复位且不可能已完成时触发，期望 host_rd_ack 为低，即使 host_rd_req 继续为高也不重复接受。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_HOST_WR_NO_IMMEDIATE_REACK — A_CK_HOST_WR_NO_IMMEDIATE_REACK

- 分类：INCONCLUSIVE
- 分析：对应 R02；当前一采样沿接受写命令、本采样尚未复位且不可能已完成时触发，期望 host_wr_ack 为低，即使 host_wr_req 继续为高也不重复接受。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_HOST_RD_DONE_NO_ACK — A_CK_HOST_RD_DONE_NO_ACK

- 分类：INCONCLUSIVE
- 分析：对应 R02；当 host_rd_done 为高时触发，期望 host_rd_ack 同拍为低，完成报告周期不得接受下一读命令。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_HOST_WR_DONE_NO_ACK — A_CK_HOST_WR_DONE_NO_ACK

- 分类：INCONCLUSIVE
- 分析：对应 R02；当 host_wr_done 为高时触发，期望 host_wr_ack 同拍为低，完成报告周期不得接受下一写命令。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_HOST_RD_PENDING_AFTER_DONE — A_CK_HOST_RD_PENDING_AFTER_DONE

- 分类：INCONCLUSIVE
- 分析：对应 R02、R12；当读 req 按协议保持跨越前一拍 host_rd_done、前后两拍 rst_n 均高时，期望当前空闲拍 host_rd_ack 为高并接受等待命令。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_HOST_WR_PENDING_AFTER_DONE — A_CK_HOST_WR_PENDING_AFTER_DONE

- 分类：INCONCLUSIVE
- 分析：对应 R02、R12；当写 req 按协议保持跨越前一拍 host_wr_done、前后两拍 rst_n 均高时，期望当前空闲拍 host_wr_ack 为高并接受等待命令。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_READ_MEM_FIRST_AFTER_ACCEPT — A_CK_READ_MEM_FIRST_AFTER_ACCEPT

- 分类：INCONCLUSIVE
- 分析：对应 R01、R03；读命令在前一拍接受且当前未复位时，期望当前拍呈现以接受地址为首地址的 mem_rd_valid；若当前 ready 为高则同沿接收 mem_rd_data。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_READ_DEV_ACK_REQ — A_CK_READ_DEV_ACK_REQ

- 分类：INCONCLUSIVE
- 分析：对应 R01、R06；当 dev_rd_ack 为高时触发，期望同拍 dev_rd_req 与 rst_n 为高；该沿的 dev_rd_data 才解释为一个有效 16 位交付。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_READ_NO_DEV_TRANSFER_WITHOUT_REQ — A_CK_READ_NO_DEV_TRANSFER_WITHOUT_REQ

- 分类：INCONCLUSIVE
- 分析：对应 R01、R08；当 dev_rd_req 为低时触发，期望 dev_rd_ack 为低，无论 memory 是否正在预取，禁止无 device 请求交付。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_READ_DEV_FRAGMENT_HOLD — A_CK_READ_DEV_FRAGMENT_HOLD

- 分类：INCONCLUSIVE
- 分析：对应 R06；当无积压歧义的 len=0 读命令接受、下一拍完成唯一 mem 读，并在再下一拍发生首个 device 交付的固定三拍窗口中，期望首片段等于该 mem 字的低 16 位；完整读数据顺序仍由 NCK-R06-RD-DATA 负责。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_WRITE_DEV_ACK_REQ — A_CK_WRITE_DEV_ACK_REQ

- 分类：INCONCLUSIVE
- 分析：对应 R01、R07；当 dev_wr_ack 为高时触发，期望同拍 dev_wr_req 与 rst_n 为高；仅该沿采样 dev_wr_data。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_WRITE_MEM_VALID_AFTER_WORD — A_CK_WRITE_MEM_VALID_AFTER_WORD

- 分类：INCONCLUSIVE
- 分析：对应 R01、R07；写命令接受后紧接四拍连续 dev_wr_req&&dev_wr_ack，在再下一拍的固定窗口中期望 mem_wr_valid 呈现所拼完整字；只判定该连续窗口，不要求环境总是连续请求。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_WRITE_NO_DEV_TRANSFER_WITHOUT_REQ — A_CK_WRITE_NO_DEV_TRANSFER_WITHOUT_REQ

- 分类：INCONCLUSIVE
- 分析：对应 R01、R08；当 dev_wr_req 为低时触发，期望 dev_wr_ack 为低，禁止无 device 请求采样写片段。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_WRITE_STALLED_WORD_NOT_OVERWRITTEN — A_CK_WRITE_STALLED_WORD_NOT_OVERWRITTEN

- 分类：INCONCLUSIVE
- 分析：对应 R05、R08；当前一采样 mem_wr_valid 高且 mem_wr_ready 低、期间未复位时触发，期望本采样仍呈现同一 mem_wr_valid、地址和数据，即使 device 侧继续具备局部收集条件。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_ADDRESS_RD_FIRST — A_CK_ADDRESS_RD_FIRST

- 分类：INCONCLUSIVE
- 分析：对应 R03；读命令接受后的紧邻周期出现首个 mem_rd_valid 且两拍 rst_n 均高时，期望 mem_rd_addr 等于接受沿 host_rd_haddr，包括低三位非零值。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_ADDRESS_WR_FIRST — A_CK_ADDRESS_WR_FIRST

- 分类：INCONCLUSIVE
- 分析：对应 R03；写命令接受后紧接四拍连续 device 写握手，并在再下一拍出现首个 mem_wr_valid 时，期望 mem_wr_addr 等于接受沿 host_wr_haddr，包括低三位非零值。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_ADDRESS_RD_STEP — A_CK_ADDRESS_RD_STEP

- 分类：INCONCLUSIVE
- 分析：对应 R03；当前一采样沿 mem_rd_valid&&mem_rd_ready 且下一读拍仍有效、期间未复位时触发，期望 mem_rd_addr 等于前一地址按 32 位加 8。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_ADDRESS_WR_STEP — A_CK_ADDRESS_WR_STEP

- 分类：INCONCLUSIVE
- 分析：对应 R03；当前一采样沿 mem_wr_valid&&mem_wr_ready 且下一写拍仍有效、期间未复位时触发，期望 mem_wr_addr 等于前一地址按 32 位加 8。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_ADDRESS_RD_HOLD — A_CK_ADDRESS_RD_HOLD

- 分类：INCONCLUSIVE
- 分析：对应 R03、R05；当前一采样 mem_rd_valid 高且 mem_rd_ready 低、期间未复位时触发，期望 mem_rd_valid 继续为高且 mem_rd_addr 不变。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_ADDRESS_WR_HOLD — A_CK_ADDRESS_WR_HOLD

- 分类：INCONCLUSIVE
- 分析：对应 R03、R05；当前一采样 mem_wr_valid 高且 mem_wr_ready 低、期间未复位时触发，期望 mem_wr_valid 继续为高且 mem_wr_addr 不变。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_ADDRESS_RD_WRAP — A_CK_ADDRESS_RD_WRAP

- 分类：INCONCLUSIVE
- 分析：对应 R03；当前一读地址位于 32 位上界附近并完成握手、下一读拍有效时触发，期望下一 mem_rd_addr 为前值加 8 的低 32 位。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_ADDRESS_WR_WRAP — A_CK_ADDRESS_WR_WRAP

- 分类：INCONCLUSIVE
- 分析：对应 R03；当前一写地址位于 32 位上界附近并完成握手、下一写拍有效时触发，期望下一 mem_wr_addr 为前值加 8 的低 32 位。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_QUOTA_ENCODING_BOUNDARY — A_CK_QUOTA_ENCODING_BOUNDARY

- 分类：INCONCLUSIVE
- 分析：对应 R04；当固定窗口内可由过去的 host req&&ack 明确归属 len=0 或 len=1 命令时，检查窗口中的 mem/device 拍数按 1:4 编码；不使用完成时当前 host_len，任意等待和全长度由 NCK-R04-COUNT 证明。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_QUOTA_RD_ZERO — A_CK_QUOTA_RD_ZERO

- 分类：INCONCLUSIVE
- 分析：对应 R04、R09；固定窗口为过去接受 host_rd_len=0、下一拍唯一 mem 读、随后四拍连续 device 读，当前期望 done；该局部窗口不声称覆盖任意等待。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_QUOTA_WR_ZERO — A_CK_QUOTA_WR_ZERO

- 分类：INCONCLUSIVE
- 分析：对应 R04、R09；固定窗口为过去接受 host_wr_len=0、随后四拍连续 device 写、再下一拍唯一 mem 写握手，当前期望 done；该局部窗口不声称覆盖任意等待。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_QUOTA_RD_LEN1 — A_CK_QUOTA_RD_LEN1

- 分类：INCONCLUSIVE
- 分析：对应 R04、R09；以过去接受沿 host_rd_len=1 关联两拍连续 mem 读和随后八拍连续 device 读的固定窗口，检查首字边界无 done、第二字边界后 done；不约束环境必须形成该窗口。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为uncovered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_QUOTA_WR_LEN1 — A_CK_QUOTA_WR_LEN1

- 分类：INCONCLUSIVE
- 分析：对应 R04、R09；以过去接受沿 host_wr_len=1 关联八拍连续 device 写及两个固定位置 mem 写握手的有限窗口，检查首字提交无 done、第二字提交后 done；任意等待由 native 模型负责。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为uncovered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_DATA_RD_LOW_FIRST — A_CK_DATA_RD_LOW_FIRST

- 分类：INCONCLUSIVE
- 分析：对应 R06；固定三拍窗口由过去 host_rd_req&&host_rd_ack 且 host_rd_len=0、下一拍 mem_rd_valid&&mem_rd_ready、当前首个 dev_rd_req&&dev_rd_ack 组成，期望当前 dev_rd_data 等于该 mem 字 [15:0]。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_DATA_RD_FOUR_LANES — A_CK_DATA_RD_FOUR_LANES

- 分类：INCONCLUSIVE
- 分析：对应 R06；固定窗口由过去接受 len=0、唯一 mem 读及随后四拍连续 dev_rd_req&&dev_rd_ack 构成，期望四拍数据依次为该 mem 字 [15:0]、[31:16]、[47:32]、[63:48]；深历史须充分有效。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_DATA_WR_FOUR_LANES — A_CK_DATA_WR_FOUR_LANES

- 分类：INCONCLUSIVE
- 分析：对应 R07；固定窗口由过去 host_wr_req&&host_wr_ack 且 len=0、随后四拍连续 dev_wr_req&&dev_wr_ack、当前首个 mem_wr_valid 构成，期望 mem_wr_data 四个片段按四次接收先后映射。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_DATA_RD_TWO_WORD_LOCAL_ORDER — A_CK_DATA_RD_TWO_WORD_LOCAL_ORDER

- 分类：INCONCLUSIVE
- 分析：对应 R06；固定窗口由过去接受 len=1、两拍连续 mem 读及随后八拍连续 device 读构成，期望前四片段来自先接收字、后四片段来自后接收字；不覆盖任意 FIFO 积压。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_DATA_WR_TWO_WORD_LOCAL_ORDER — A_CK_DATA_WR_TWO_WORD_LOCAL_ORDER

- 分类：INCONCLUSIVE
- 分析：对应 R07；固定窗口由过去接受 len=1、八拍连续 device 写及两个固定位置 mem 写字构成，期望第一组四片段字先提交、第二组后提交；任意积压由 NCK-R07-WR-DATA 负责。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_FLOW_RD_VALID_ADDRESS_HOLD — A_CK_FLOW_RD_VALID_ADDRESS_HOLD

- 分类：INCONCLUSIVE
- 分析：对应 R05；当前一采样 mem_rd_valid 高且 mem_rd_ready 低、期间未复位时触发，期望本采样 mem_rd_valid 仍高且 mem_rd_addr 稳定；任意长背压逐拍适用。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_FLOW_WR_VALID_ADDRESS_DATA_HOLD — A_CK_FLOW_WR_VALID_ADDRESS_DATA_HOLD

- 分类：INCONCLUSIVE
- 分析：对应 R05；当前一采样 mem_wr_valid 高且 mem_wr_ready 低、期间未复位时触发，期望本采样 mem_wr_valid 仍高，mem_wr_addr 与 mem_wr_data 均稳定；不限制背压持续时间。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_FLOW_DEV_RD_ACK_GATED — A_CK_FLOW_DEV_RD_ACK_GATED

- 分类：INCONCLUSIVE
- 分析：对应 R01、R08；当 dev_rd_req 为低或 rst_n 为低时触发，期望 dev_rd_ack 为低；不以内层 FIFO valid 作为前提。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_FLOW_DEV_WR_ACK_GATED — A_CK_FLOW_DEV_WR_ACK_GATED

- 分类：INCONCLUSIVE
- 分析：对应 R01、R08；当 dev_wr_req 为低或 rst_n 为低时触发，期望 dev_wr_ack 为低；不以内层配额或 FIFO ready 作为前提。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_FLOW_BUFFER_WR_VISIBLE_HOLD — A_CK_FLOW_BUFFER_WR_VISIBLE_HOLD

- 分类：INCONCLUSIVE
- 分析：对应 R08；当外部可见 mem 写队首遭遇背压时触发，期望地址和数据保持而不被后续 device 片段覆盖；只判定顶层后果。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_FLOW_BUFFER_NO_SPURIOUS_DEV_ACK — A_CK_FLOW_BUFFER_NO_SPURIOUS_DEV_ACK

- 分类：INCONCLUSIVE
- 分析：对应 R08；当任一 device req 无效时触发，期望其 ack 无效，不因内部同拍 FIFO 入出队或替换产生可见伪传输；内部 FIFO 行为由 NCK-R08 系列另证。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_RESET_HOST_SILENCE — A_CK_RESET_HOST_SILENCE

- 分类：INCONCLUSIVE
- 分析：对应 R10；任一采样或组合观察中 rst_n 为低时触发，期望 host_rd_ack、host_wr_ack、host_rd_done、host_wr_done 全部为低。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_RESET_DATA_CHANNEL_SILENCE — A_CK_RESET_DATA_CHANNEL_SILENCE

- 分类：INCONCLUSIVE
- 分析：对应 R10；任一采样或组合观察中 rst_n 为低时触发，期望 mem_rd_valid、mem_wr_valid、dev_rd_ack、dev_wr_ack 全部为低。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_RESET_INTERRUPT_RD_STALL — A_CK_RESET_INTERRUPT_RD_STALL

- 分类：INCONCLUSIVE
- 分析：对应 R10；当前一采样 mem_rd_valid 高且被背压、随后 rst_n 拉低时触发，期望复位采样的 mem_rd_valid 与读侧 ack/done 均为低。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_RESET_INTERRUPT_WR_STALL — A_CK_RESET_INTERRUPT_WR_STALL

- 分类：INCONCLUSIVE
- 分析：对应 R10；当前一采样 mem_wr_valid 高且被背压、随后 rst_n 拉低时触发，期望复位采样的 mem_wr_valid 与写侧 ack/done 均为低。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_RESET_INTERRUPT_DEVICE_PARTIAL — A_CK_RESET_INTERRUPT_DEVICE_PARTIAL

- 分类：INCONCLUSIVE
- 分析：对应 R10；固定两拍窗口中前一拍发生任一 device 握手而当前 rst_n 拉低时，期望当前两个 device ack 和两个 done 均为低；内部 lane 与部分拼接清除留给 NCK-R10-RESET。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_RESET_RD_DONE_CLEAR — A_CK_RESET_RD_DONE_CLEAR

- 分类：INCONCLUSIVE
- 分析：对应 R09、R10；当当前 rst_n 低，或前一拍 rst_n 低而当前已释放且尚未接受新读命令时，期望 host_rd_done 为低；旧命令不得在释放后一拍补发完成。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_RESET_WR_DONE_CLEAR — A_CK_RESET_WR_DONE_CLEAR

- 分类：INCONCLUSIVE
- 分析：对应 R09、R10；当当前 rst_n 低，或前一拍 rst_n 低而当前已释放且尚未接受新写命令时，期望 host_wr_done 为低；旧命令不得在释放后一拍补发完成。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_RESET_RD_RESTART_ADDRESS — A_CK_RESET_RD_RESTART_ADDRESS

- 分类：INCONCLUSIVE
- 分析：对应 R10；过去两拍依次为复位低、接受新读命令，当前紧邻出现 mem_rd_valid 时，期望 mem_rd_addr 使用该接受沿的新 host_rd_haddr 且旧 host_rd_done 未出现。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_RESET_WR_RESTART_ADDRESS — A_CK_RESET_WR_RESTART_ADDRESS

- 分类：INCONCLUSIVE
- 分析：对应 R10；复位释放后接受新写命令，紧接四拍连续 device 写并在下一拍出现 mem_wr_valid 的固定窗口中，期望 mem_wr_addr 使用接受沿的新 host_wr_haddr 且旧 done 未出现。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_CONCURRENT_ACCEPT_AFTER_RESET — A_CK_CONCURRENT_ACCEPT_AFTER_RESET

- 分类：INCONCLUSIVE
- 分析：对应 R01、R11；当前一采样处于复位、释放后读写 req 同时有效且两个 done 均低时触发，期望 host_rd_ack 与 host_wr_ack 同拍均为高，检查接受路径不互斥。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_CONCURRENT_RD_STALL_WR_HANDSHAKE — A_CK_CONCURRENT_RD_STALL_WR_HANDSHAKE

- 分类：INCONCLUSIVE
- 分析：对应 R01、R11；当前拍写 mem 握手成立且前一拍读 mem valid 被 ready 低阻塞、两拍未复位时，期望读 valid 和地址保持；写握手本身只作为观察条件，不作同义后件。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_CONCURRENT_WR_STALL_RD_HANDSHAKE — A_CK_CONCURRENT_WR_STALL_RD_HANDSHAKE

- 分类：INCONCLUSIVE
- 分析：对应 R01、R11；当前拍读 mem 握手成立且前一拍写 mem valid 被 ready 低阻塞、两拍未复位时，期望写 valid、地址和数据保持；读握手本身只作为观察条件。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_CONCURRENT_SIMULTANEOUS_DONE — A_CK_CONCURRENT_SIMULTANEOUS_DONE

- 分类：INCONCLUSIVE
- 分析：对应 R09、R11；当前两个 done 同时为高时检查前一拍读 dev 与写 mem 目标握手均成立；并发完成的固定窗口可达性另由 Cover 检查，任意长度最终身份由 native 双模型补足。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_DONE_RD_ONE_CYCLE — A_CK_DONE_RD_ONE_CYCLE

- 分类：INCONCLUSIVE
- 分析：对应 R09；当前一采样 host_rd_done 为高且本采样未复位时触发，期望 host_rd_done 已回落，禁止连续两个周期保持读完成。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_DONE_WR_ONE_CYCLE — A_CK_DONE_WR_ONE_CYCLE

- 分类：INCONCLUSIVE
- 分析：对应 R09；当前一采样 host_wr_done 为高且本采样未复位时触发，期望 host_wr_done 已回落，禁止连续两个周期保持写完成。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_DONE_RD_PREV_DEV_HANDSHAKE — A_CK_DONE_RD_PREV_DEV_HANDSHAKE

- 分类：INCONCLUSIVE
- 分析：对应 R09；当 host_rd_done 为高时触发，期望前一采样沿 dev_rd_req&&dev_rd_ack 成立且 rst_n 为高；不把后件直接用作 guard，最终配额身份由 NCK-R09-DONE 证明。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_DONE_WR_PREV_MEM_HANDSHAKE — A_CK_DONE_WR_PREV_MEM_HANDSHAKE

- 分类：INCONCLUSIVE
- 分析：对应 R09；当 host_wr_done 为高时触发，期望前一采样沿 mem_wr_valid&&mem_wr_ready 成立且 rst_n 为高；不把后件直接用作 guard，最终配额身份由 NCK-R09-DONE 证明。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_DONE_RD_NO_ACK — A_CK_DONE_RD_NO_ACK

- 分类：INCONCLUSIVE
- 分析：对应 R02、R09；当 host_rd_done 为高时触发，期望 host_rd_ack 为低，无论 host_rd_req 是否等待。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_DONE_WR_NO_ACK — A_CK_DONE_WR_NO_ACK

- 分类：INCONCLUSIVE
- 分析：对应 R02、R09；当 host_wr_done 为高时触发，期望 host_wr_ack 为低，无论 host_wr_req 是否等待。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_DONE_RD_NEXT_ACK — A_CK_DONE_RD_NEXT_ACK

- 分类：INCONCLUSIVE
- 分析：对应 R02、R09；当读 req 按协议跨越前一拍 done 保持且当前未复位时，期望当前 host_rd_done 已低并由 host_rd_ack 接受新命令。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-A_CK_DONE_WR_NEXT_ACK — A_CK_DONE_WR_NEXT_ACK

- 分类：INCONCLUSIVE
- 分析：对应 R02、R09；当写 req 按协议跨越前一拍 done 保持且当前未复位时，期望当前 host_wr_done 已低并由 host_wr_ack 接受新命令。 当前证据：此安全属性在depth12的实际BMC运行未发现反例，但状态是inconclusive；主任务prove和联合prove均240秒超时，无逐属性证明。对应guard witness实际为covered，可达不等于该断言已被无界证明。采样历史及复位连续条件以当前生成checker为准；固定历史窗口不能扩张为所有命令或任意积压情形。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-G_A_CK_QUOTA_RD_LEN1 — G_A_CK_QUOTA_RD_LEN1

- 分类：INCONCLUSIVE
- 分析：对应 R04、R09；以过去接受沿 host_rd_len=1 关联两拍连续 mem 读和随后八拍连续 device 读的固定窗口，检查首字边界无 done、第二字边界后 done；不约束环境必须形成该窗口。 当前证据：该guard_witness在当前depth12 Cover运行未命中，只报告uncovered；没有不可达证明，不能登记为RTL_BUG。需要独立增加覆盖深度或检查触发轨迹；不增加公平性、长度限制或默认disable iff来取得命中。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-G_A_CK_QUOTA_WR_LEN1 — G_A_CK_QUOTA_WR_LEN1

- 分类：INCONCLUSIVE
- 分析：对应 R04、R09；以过去接受沿 host_wr_len=1 关联八拍连续 device 写及两个固定位置 mem 写握手的有限窗口，检查首字提交无 done、第二字提交后 done；任意等待由 native 模型负责。 当前证据：该guard_witness在当前depth12 Cover运行未命中，只报告uncovered；没有不可达证明，不能登记为RTL_BUG。需要独立增加覆盖深度或检查触发轨迹；不增加公平性、长度限制或默认disable iff来取得命中。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-C_CK_COVER_RD_LEN1 — C_CK_COVER_RD_LEN1

- 分类：INCONCLUSIVE
- 分析：对应 R04、R12；固定窗口中由过去接受沿 host_rd_len=1 关联两拍连续 mem 读、八拍连续 device 读及当前完成，期望获得两字读见证。 当前证据：该cover在当前depth12 Cover运行未命中，只报告uncovered；没有不可达证明，不能登记为RTL_BUG。需要独立增加覆盖深度或检查触发轨迹；不增加公平性、长度限制或默认disable iff来取得命中。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-C_CK_COVER_WR_LEN1 — C_CK_COVER_WR_LEN1

- 分类：INCONCLUSIVE
- 分析：对应 R04、R12；固定窗口中由过去接受沿 host_wr_len=1 关联八拍连续 device 写、两个固定位置 mem 写及当前完成，期望获得两字写见证。 当前证据：该cover在当前depth12 Cover运行未命中，只报告uncovered；没有不可达证明，不能登记为RTL_BUG。需要独立增加覆盖深度或检查触发轨迹；不增加公平性、长度限制或默认disable iff来取得命中。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-C_CK_COVER_WR_LONGER_PROGRESS — C_CK_COVER_WR_LONGER_PROGRESS

- 分类：INCONCLUSIVE
- 分析：对应 R04、R12；固定窗口中接受沿 host_wr_len>1 后出现十二拍连续 device 写及三个固定位置 mem 写，期望展示更长写事务局部进度；不要求完成任意 len。 当前证据：该cover在当前depth12 Cover运行未命中，只报告uncovered；没有不可达证明，不能登记为RTL_BUG。需要独立增加覆盖深度或检查触发轨迹；不增加公平性、长度限制或默认disable iff来取得命中。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-C_CK_COVER_RD_THREE_COMMANDS — C_CK_COVER_RD_THREE_COMMANDS

- 分类：INCONCLUSIVE
- 分析：对应 R02、R12；固定 21 拍窗口中三次接受沿均携带 host_rd_len=0，且按接受、唯一 mem 读、四拍 device 读、done、下一拍接受的节奏连续出现，期望获得三读命令见证。 当前证据：该cover在当前depth12 Cover运行未命中，只报告uncovered；没有不可达证明，不能登记为RTL_BUG。需要独立增加覆盖深度或检查触发轨迹；不增加公平性、长度限制或默认disable iff来取得命中。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：


### FA-C_CK_COVER_WR_THREE_COMMANDS — C_CK_COVER_WR_THREE_COMMANDS

- 分类：INCONCLUSIVE
- 分析：对应 R02、R12；固定 21 拍窗口中三次接受沿均携带 host_wr_len=0，且按接受、四拍 device 写、唯一 mem 写、done、下一拍接受的节奏连续出现，期望获得三写命令见证。 当前证据：该cover在当前depth12 Cover运行未命中，只报告uncovered；没有不可达证明，不能登记为RTL_BUG。需要独立增加覆盖深度或检查触发轨迹；不增加公平性、长度限制或默认disable iff来取得命中。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。
- 后续处理：

