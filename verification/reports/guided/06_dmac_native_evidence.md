# 本轮原生辅助工程实际结果

每个结果来自本轮新建目录，已核验运行清单签名、输入与产物哈希。此前运行结论未继承。

| case | 参数 | 模式 | 断言数 | Cover 数 | 实际结论 | 运行 ID |
| --- | --- | --- | --- | --- | --- | --- |
| accepted_cover_a32_l1_f1 | [32, 1, 1] | 业务覆盖 | 56 | 17 | 通过 | 771482a2f50b4eeaad0a42b735af37f6 |
| accepted_cover_a32_l32_f2 | [32, 32, 2] | 业务覆盖 | 58 | 17 | 通过 | 6bd1ef7edf434402ae0cff36679bdc70 |
| accepted_prove_a16_l8_f3 | [16, 8, 3] | prove | 60 | 17 | 通过 | 002c3b05dd484c44b0f87d05f6bdad1e |
| accepted_prove_a32_l1_f4 | [32, 1, 4] | prove | 62 | 17 | 通过 | 189ae4514756471e80a9c740c35920f5 |
| accepted_prove_a32_l32_f2 | [32, 32, 2] | prove | 58 | 17 | 通过 | da585410434c4cf889b18eba50cec087 |
| accepted_prove_a32_l8_f1 | [32, 8, 1] | prove | 56 | 17 | 通过 | 04fd27d2cd08450d803dcd78a17be70a |
| fault_address_step | [16, 2, 2] | bmc | 58 | 17 | 失败 | d59c7d3dd3204f01be461e91f436ded1 |
| fault_early_done | [16, 2, 2] | bmc | 58 | 17 | 失败 | f8e23590e32241bda34650aee357a63f |
| fault_fifo_pop | [16, 2, 2] | bmc | 58 | 17 | 失败 | 2475baf0201845afb6084971f2a4a6ee |
| fault_length_encoding | [16, 2, 2] | bmc | 58 | 17 | 失败 | 1531039948d84f03885f2c3c9287b9e8 |
| fault_read_lane | [16, 2, 2] | bmc | 58 | 17 | 失败 | 06d87e8edb7a487d910a21177c46ed75 |
| fault_reset_lane | [16, 2, 2] | bmc | 58 | 17 | 失败 | 28a15a4880044065afb58a618c16ea1d |
| fault_write_lane | [16, 2, 2] | bmc | 58 | 17 | 失败 | 993f857b1cfe46529ace5d520d7a6622 |
| fifo_cover_f1 | [32, 32, 1] | 业务覆盖 | 7 | 3 | 通过 | 8bfc22f0ac7249fcb620f88a1cfad99e |
| fifo_cover_f3 | [32, 32, 3] | 业务覆盖 | 9 | 3 | 通过 | 40e9409f1a20473a96f426b594bc4b0f |
| fifo_cover_f4 | [32, 32, 4] | 业务覆盖 | 10 | 3 | 通过 | e8c5b9732679472b9538ffa119cf8313 |

故障注入的 failed 是修改版真实反例，不是原始 DUT 的缺陷。

## 原生义务对应关系

以下仅解释已经运行的属性，不能把辅助证明写入主任务 run_results，也不能覆盖 guided 的未决状态。

| 规划义务 | 实际属性族 | 范围 |
| --- | --- | --- |
| NCK-R04-COUNT | A_CK_RD_FETCH_LEFT / RD_DELIVER_LEFT / WR_COLLECT_LEFT / WR_COMMIT_LEFT / RD_QUOTA / WR_QUOTA / *_NO_EXTRA / *_BUSY_QUOTA | 以外部握手独立计数，N=len+1，device=4N；默认 LEN_W=32 不限制 len 输入 |
| NCK-R06-RD-DATA | A_CK_RD_LANE / RD_DATA / RD_OCCUPANCY / RD_HEAD_VALID 及每个 FIFO 存储槽次序不变式 | 任意 64 位输入、任意背压、低16位先传，读端交付与独立队列模型一致 |
| NCK-R07-WR-DATA | A_CK_WR_LANE / WR_PACK / WR_PACK_UNUSED_ZERO / WR_ASSEMBLY / WR_DATA / WR_OCCUPANCY 及 FIFO 槽次序不变式 | 任意16位输入、四片段拼接、写端提交与独立队列模型一致 |
| NCK-R08-FIFO-D2/D1/D3 | A_CK_FIFO_COUNT / RANGE / POINTERS / VALID / READY / HEAD / 各实例槽位顺序属性 | 默认深度2，加深度1、3、4的具体参数证明；不声称全部任意深度参数归纳 |
| NCK-R09-DONE | A_CK_RD_DONE / WR_DONE / RD_COMPLETE_COUNTS / WR_COMPLETE_COUNTS / *_ACK_ADMISSION | 最终目标握手、准确完成配额、单周期 done、完成边界不重接收 |
| NCK-R10-RESET | 全部 oracle 和 FIFO 复位不变式，C_CK_RESET_ABORT_RD / WR；reset_lane 故障反例 | 初始一个复位样本，其后允许任意再次复位；采样模型，不是模拟电路亚周期毛刺证明 |
| NCK-R11-DUPLEX | 独立双通道 oracle，A_CK_RD_PROGRESS / WR_PROGRESS，C_CK_DUPLEX_DONE | 两方向输入和背压互不约束；局部前进证明和双向完成可达，未建立无公平性最终完成 |

## 本轮真实回放

replay/results.json 保存 19 个实际 Icarus 编译/运行结果：7 条故障修改版与反例逐周期匹配、7 条同输入在原始 RTL 上产生预期不匹配、5 条原始业务轨迹匹配（连续三条读/写、双向同时完成、读/写中途复位）。它们是辅助原生工程故障对照，不是主任务确认的 RTL_BUG，不能据此虚构 bugs 条目。

## 未建立的能力

逻辑影响范围分析：不支持；完整空洞性：未建立；无界活性：未建立。guard witness 命中只表示 guard/trigger 可达。未证明所有参数组合、LEN_W=32最大长度实际完成轨迹、模拟电路毛刺或地址混叠内存一致性；没有真实 FormalMC/VCS 工具验收。native工程仅增加可移除 FORMAL 观察/断言，移除后与原始 RTL 字节一致；原始 RTL 未修改。

回放明细摘要：

```json
[
  {
    "case": "fault_address_step_mutant",
    "source": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-fault-address_step-20261005",
    "trace": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-fault-address_step-20261005/.ucagent/platform-runs/d59c7d3dd3204f01be461e91f436ded1/formal/proof/engine_0/trace.vcd",
    "trace_sha256": "84ccd8c226c830a35fca1ebd1109ce9c220e3d33d07ba7bc4d7adccb7815df71",
    "vectors": 5,
    "compile_code": 0,
    "run_code": 0
  },
  {
    "case": "fault_address_step_baseline",
    "source": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-20261005",
    "trace": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-fault-address_step-20261005/.ucagent/platform-runs/d59c7d3dd3204f01be461e91f436ded1/formal/proof/engine_0/trace.vcd",
    "trace_sha256": "84ccd8c226c830a35fca1ebd1109ce9c220e3d33d07ba7bc4d7adccb7815df71",
    "vectors": 5,
    "compile_code": 0,
    "run_code": 1
  },
  {
    "case": "fault_early_done_mutant",
    "source": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-fault-early_done-20261005",
    "trace": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-fault-early_done-20261005/.ucagent/platform-runs/f8e23590e32241bda34650aee357a63f/formal/proof/engine_0/trace.vcd",
    "trace_sha256": "33c04eefe74eb19848cedd3d34387249cb2da1db6d23860e0720dcc9ccb61fba",
    "vectors": 9,
    "compile_code": 0,
    "run_code": 0
  },
  {
    "case": "fault_early_done_baseline",
    "source": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-20261005",
    "trace": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-fault-early_done-20261005/.ucagent/platform-runs/f8e23590e32241bda34650aee357a63f/formal/proof/engine_0/trace.vcd",
    "trace_sha256": "33c04eefe74eb19848cedd3d34387249cb2da1db6d23860e0720dcc9ccb61fba",
    "vectors": 9,
    "compile_code": 0,
    "run_code": 1
  },
  {
    "case": "fault_fifo_pop_mutant",
    "source": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-fault-fifo_pop-20261005",
    "trace": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-fault-fifo_pop-20261005/.ucagent/platform-runs/2475baf0201845afb6084971f2a4a6ee/formal/proof/engine_0/trace.vcd",
    "trace_sha256": "5c4cfcd209e1e0a17fae2b7573dfc051044abbab59ec774fd4e93ceef1f59bd1",
    "vectors": 9,
    "compile_code": 0,
    "run_code": 0
  },
  {
    "case": "fault_fifo_pop_baseline",
    "source": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-20261005",
    "trace": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-fault-fifo_pop-20261005/.ucagent/platform-runs/2475baf0201845afb6084971f2a4a6ee/formal/proof/engine_0/trace.vcd",
    "trace_sha256": "5c4cfcd209e1e0a17fae2b7573dfc051044abbab59ec774fd4e93ceef1f59bd1",
    "vectors": 9,
    "compile_code": 0,
    "run_code": 1
  },
  {
    "case": "fault_length_encoding_mutant",
    "source": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-fault-length_encoding-20261005",
    "trace": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-fault-length_encoding-20261005/.ucagent/platform-runs/1531039948d84f03885f2c3c9287b9e8/formal/proof/engine_0/trace.vcd",
    "trace_sha256": "d4ae4baeefc9903be078a6fdc04aaab7b019f0433bd32d124db179e0e353d832",
    "vectors": 4,
    "compile_code": 0,
    "run_code": 0
  },
  {
    "case": "fault_length_encoding_baseline",
    "source": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-20261005",
    "trace": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-fault-length_encoding-20261005/.ucagent/platform-runs/1531039948d84f03885f2c3c9287b9e8/formal/proof/engine_0/trace.vcd",
    "trace_sha256": "d4ae4baeefc9903be078a6fdc04aaab7b019f0433bd32d124db179e0e353d832",
    "vectors": 4,
    "compile_code": 0,
    "run_code": 1
  },
  {
    "case": "fault_read_lane_mutant",
    "source": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-fault-read_lane-20261005",
    "trace": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-fault-read_lane-20261005/.ucagent/platform-runs/06d87e8edb7a487d910a21177c46ed75/formal/proof/engine_0/trace.vcd",
    "trace_sha256": "65b0732e7524e9af05e2ba4305c8575b9ed886c9887f8e4a6827caae8b9178cc",
    "vectors": 5,
    "compile_code": 0,
    "run_code": 0
  },
  {
    "case": "fault_read_lane_baseline",
    "source": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-20261005",
    "trace": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-fault-read_lane-20261005/.ucagent/platform-runs/06d87e8edb7a487d910a21177c46ed75/formal/proof/engine_0/trace.vcd",
    "trace_sha256": "65b0732e7524e9af05e2ba4305c8575b9ed886c9887f8e4a6827caae8b9178cc",
    "vectors": 5,
    "compile_code": 0,
    "run_code": 1
  },
  {
    "case": "fault_reset_lane_mutant",
    "source": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-fault-reset_lane-20261005",
    "trace": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-fault-reset_lane-20261005/.ucagent/platform-runs/28a15a4880044065afb58a618c16ea1d/formal/proof/engine_0/trace.vcd",
    "trace_sha256": "afb49fbe57ee89c373a04eb76f3887c589487678da078b3c84939014b1177020",
    "vectors": 3,
    "compile_code": 0,
    "run_code": 0
  },
  {
    "case": "fault_reset_lane_baseline",
    "source": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-20261005",
    "trace": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-fault-reset_lane-20261005/.ucagent/platform-runs/28a15a4880044065afb58a618c16ea1d/formal/proof/engine_0/trace.vcd",
    "trace_sha256": "afb49fbe57ee89c373a04eb76f3887c589487678da078b3c84939014b1177020",
    "vectors": 3,
    "compile_code": 0,
    "run_code": 1
  },
  {
    "case": "fault_write_lane_mutant",
    "source": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-fault-write_lane-20261005",
    "trace": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-fault-write_lane-20261005/.ucagent/platform-runs/993f857b1cfe46529ace5d520d7a6622/formal/proof/engine_0/trace.vcd",
    "trace_sha256": "2fe8992815932ecc1856940fe3c083fc4cedfa10cb8fb33a336f834fb22e71d2",
    "vectors": 4,
    "compile_code": 0,
    "run_code": 0
  },
  {
    "case": "fault_write_lane_baseline",
    "source": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-20261005",
    "trace": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-fault-write_lane-20261005/.ucagent/platform-runs/993f857b1cfe46529ace5d520d7a6622/formal/proof/engine_0/trace.vcd",
    "trace_sha256": "2fe8992815932ecc1856940fe3c083fc4cedfa10cb8fb33a336f834fb22e71d2",
    "vectors": 4,
    "compile_code": 0,
    "run_code": 1
  },
  {
    "case": "C_CK_RESET_ABORT_RD",
    "source": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-20261005",
    "trace": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-native-20261005/.ucagent/platform-runs/6bd1ef7edf434402ae0cff36679bdc70/formal/proof/engine_0/trace3.vcd",
    "trace_sha256": "52d6625527282daa8c4dddedd33a33ec973b4933ed7857c05d5a2ed41aa0a4be",
    "vectors": 5,
    "compile_code": 0,
    "run_code": 0
  },
  {
    "case": "C_CK_RESET_ABORT_WR",
    "source": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-20261005",
    "trace": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-native-20261005/.ucagent/platform-runs/6bd1ef7edf434402ae0cff36679bdc70/formal/proof/engine_0/trace10.vcd",
    "trace_sha256": "d2d2d11a8080545981a1036aadae8c0921dabe69f79f6f94be32e2ba13a1d06d",
    "vectors": 9,
    "compile_code": 0,
    "run_code": 0
  },
  {
    "case": "C_CK_DUPLEX_DONE",
    "source": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-20261005",
    "trace": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-native-20261005/.ucagent/platform-runs/6bd1ef7edf434402ae0cff36679bdc70/formal/proof/engine_0/trace11.vcd",
    "trace_sha256": "2d0b1ef2b64b74c9529b317c4fd0215d8010f85fab1c9c5328120cd4d18bbe2b",
    "vectors": 9,
    "compile_code": 0,
    "run_code": 0
  },
  {
    "case": "C_CK_THREE_RD",
    "source": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-20261005",
    "trace": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-native-20261005/.ucagent/platform-runs/6bd1ef7edf434402ae0cff36679bdc70/formal/proof/engine_0/trace14.vcd",
    "trace_sha256": "2fb36d54962d5f679362c66bc0d41a9966dda3aed168075ec583ad89f517adcf",
    "vectors": 23,
    "compile_code": 0,
    "run_code": 0
  },
  {
    "case": "C_CK_THREE_WR",
    "source": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-20261005",
    "trace": "/home/ucagent-lab/development/20261004-formalmc-migration/acceptance/DMAC-fullflow-native-20261005/.ucagent/platform-runs/6bd1ef7edf434402ae0cff36679bdc70/formal/proof/engine_0/trace15.vcd",
    "trace_sha256": "0671c141f536f3d28cb444098974b66cf3ac3d0776a624fcbcb1c6f1a950ba2a",
    "vectors": 23,
    "compile_code": 0,
    "run_code": 0
  }
]
```

证据文件 SHA-256：

- verified-evidence.json: b578a7b5ce13e4b2e3779fa1c1cd3603b916866cb596f2db842ef8bc5dbde19a
- property-map.json: e255164ad37bd930fe6ef6123ab8ec16278fd139f1d88e18af83b3a101d0b72f
- replay/results.json: 1ef9118b611a1cfd415d4d2fcc7a571bb4d7516fd32c7cffc6275b249b2ed774
- native-project.json: 3d57ceb33ef25c038f1c6d78d01bdce1479d354eb5aebe8026e0edba70321091
