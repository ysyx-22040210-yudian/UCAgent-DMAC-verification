# 本轮原生辅助工程实际结果

每个结果来自本轮新建目录，已核验运行清单签名、输入与产物哈希。此前运行结论未继承。

| case | 参数 | 模式 | 断言数 | Cover 数 | 实际结论 | 运行 ID |
| --- | --- | --- | --- | --- | --- | --- |
| accepted_cover_a32_l1_f1 | [32, 1, 1] | cover | 56 | 17 | passed | 771482a2f50b4eeaad0a42b735af37f6 |
| accepted_cover_a32_l32_f2 | [32, 32, 2] | cover | 58 | 17 | passed | 6bd1ef7edf434402ae0cff36679bdc70 |
| accepted_prove_a16_l8_f3 | [16, 8, 3] | prove | 60 | 17 | passed | 002c3b05dd484c44b0f87d05f6bdad1e |
| accepted_prove_a32_l1_f4 | [32, 1, 4] | prove | 62 | 17 | passed | 189ae4514756471e80a9c740c35920f5 |
| accepted_prove_a32_l32_f2 | [32, 32, 2] | prove | 58 | 17 | passed | da585410434c4cf889b18eba50cec087 |
| accepted_prove_a32_l8_f1 | [32, 8, 1] | prove | 56 | 17 | passed | 04fd27d2cd08450d803dcd78a17be70a |
| fault_address_step | [16, 2, 2] | bmc | 58 | 17 | failed | d59c7d3dd3204f01be461e91f436ded1 |
| fault_early_done | [16, 2, 2] | bmc | 58 | 17 | failed | f8e23590e32241bda34650aee357a63f |
| fault_fifo_pop | [16, 2, 2] | bmc | 58 | 17 | failed | 2475baf0201845afb6084971f2a4a6ee |
| fault_length_encoding | [16, 2, 2] | bmc | 58 | 17 | failed | 1531039948d84f03885f2c3c9287b9e8 |
| fault_read_lane | [16, 2, 2] | bmc | 58 | 17 | failed | 06d87e8edb7a487d910a21177c46ed75 |
| fault_reset_lane | [16, 2, 2] | bmc | 58 | 17 | failed | 28a15a4880044065afb58a618c16ea1d |
| fault_write_lane | [16, 2, 2] | bmc | 58 | 17 | failed | 993f857b1cfe46529ace5d520d7a6622 |
| fifo_cover_f1 | [32, 32, 1] | cover | 7 | 3 | passed | 8bfc22f0ac7249fcb620f88a1cfad99e |
| fifo_cover_f3 | [32, 32, 3] | cover | 9 | 3 | passed | 40e9409f1a20473a96f426b594bc4b0f |
| fifo_cover_f4 | [32, 32, 4] | cover | 10 | 3 | passed | e8c5b9732679472b9538ffa119cf8313 |
| joint_guided_prove_a32_l32_f2_4a047b61 | [32, 32, 2] | prove | 0 | 0 | unknown | 6fe692e2e61d49f78a3caf1103bab687 |

故障注入的 failed 是修改版真实反例，不是原始 DUT 的缺陷。