# 工程师环境审查记录与内置 Agent 复核入口

长 YAML 全文超过模型单次工具输出限制；工程师通过原始 public save、当前revision和文件SHA补齐审查字段。只修改extra_config.sby.review和analysis.fa_entries的分析字段，没有改变spec、bugs或run_results。内置Agent继续阅读并使用实际门禁，不能声称这些记录为Agent独立撰写。

当前输入：`fce2c3069ac3096abbfa9e4340c84b40bf787a604d067f46695d02a6bbb8b51c`。

## Assume 规格依据

`M_CK_API_RESET_INITIAL`：对应 R10、R13；仅在形式时间零的首个采样点触发，要求 rst_n 为低以建立确定初态；此 Assume 不约束后续采样，必须允许运行中再次复位。 实际表达式：!rst_n；不限制地址、len、数据取值或背压持续时间。

`M_CK_API_HOST_RD_WAIT`：对应 R02、R13；当前一采样沿 host_rd_req 有效且 host_rd_ack 无效、期间未复位时触发，要求本采样沿 host_rd_req、host_rd_haddr、host_rd_len 保持；不限制其数值或等待周期数。 实际表达式：host_rd_req && $stable(host_rd_haddr) && $stable(host_rd_len)；不限制地址、len、数据取值或背压持续时间。

`M_CK_API_HOST_WR_WAIT`：对应 R02、R13；当前一采样沿 host_wr_req 有效且 host_wr_ack 无效、期间未复位时触发，要求本采样沿 host_wr_req、host_wr_haddr、host_wr_len 保持；不限制其数值或等待周期数。 实际表达式：host_wr_req && $stable(host_wr_haddr) && $stable(host_wr_len)；不限制地址、len、数据取值或背压持续时间。

`M_CK_API_DEV_RD_WAIT`：对应 R01、R13；当前一采样沿 dev_rd_req 有效且 dev_rd_ack 无效、期间未复位时触发，要求本采样沿 dev_rd_req 保持；不要求 device 在空闲时发起请求。 实际表达式：dev_rd_req；不限制地址、len、数据取值或背压持续时间。

`M_CK_API_DEV_WR_WAIT_REQ`：对应 R01、R13；当前一采样沿 dev_wr_req 有效且 dev_wr_ack 无效、期间未复位时触发，要求本采样沿 dev_wr_req 保持。 实际表达式：dev_wr_req；不限制地址、len、数据取值或背压持续时间。

`M_CK_API_DEV_WR_WAIT_DATA`：对应 R01、R13；当前一采样沿 dev_wr_req 有效且 dev_wr_ack 无效、期间未复位时触发，要求本采样沿 dev_wr_data 保持；不限制数据内容。 实际表达式：dev_wr_req && $stable(dev_wr_data)；不限制地址、len、数据取值或背压持续时间。

## 能力限制

逻辑影响范围分析：不支持；完整空洞性：未建立；无界活性：未建立。主任务默认ADDR_W/LEN_W/FIFO_DEPTH=32/32/2，BMC深度12；63条安全断言未获无界证明，主任务prove与联合prove均240秒超时。固定连续窗口只检查所列len0/len1局部行为，不替代任意长度、任意积压的完整模型。guard witness只表明触发可达；7个未命中目标仍未决，不声称不可达。永久背压合法，无公平性约束或最终完成结论。native独立证明仅涵盖32/32/2、32/8/1、16/8/3、32/1/4四个实际参数实例，不是全部参数量化。reset_policy=unconstrained，仅M_CK_API_RESET_INITIAL约束首采样rst_n=0，后续复位自由；深历史需有效历史与逐拍复位边界。复位结论限数字采样RTL模型，未验证模拟毛刺、恢复/移除时序。没有真实FormalMC/VCS运行。

## 未决分析记录

63条安全断言与7个未命中Cover/guard已逐项填入原始analysis.fa_entries；均是当前工具报告的INCONCLUSIVE，没有改写运行结果。每条分析保留对应CK需求、实际有界结果与guard witness状态，固定窗口和native辅助证据限制。完整工程师撰写记录另存review-authorship.json。

`G_A_CK_QUOTA_RD_LEN1` [uncovered]：对应 R04、R09；以过去接受沿 host_rd_len=1 关联两拍连续 mem 读和随后八拍连续 device 读的固定窗口，检查首字边界无 done、第二字边界后 done；不约束环境必须形成该窗口。 当前证据：该guard_witness在当前depth12 Cover运行未命中，只报告uncovered；没有不可达证明，不能登记为RTL_BUG。需要独立增加覆盖深度或检查触发轨迹；不增加公平性、长度限制或默认disable iff来取得命中。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。

`G_A_CK_QUOTA_WR_LEN1` [uncovered]：对应 R04、R09；以过去接受沿 host_wr_len=1 关联八拍连续 device 写及两个固定位置 mem 写握手的有限窗口，检查首字提交无 done、第二字提交后 done；任意等待由 native 模型负责。 当前证据：该guard_witness在当前depth12 Cover运行未命中，只报告uncovered；没有不可达证明，不能登记为RTL_BUG。需要独立增加覆盖深度或检查触发轨迹；不增加公平性、长度限制或默认disable iff来取得命中。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。

`C_CK_COVER_RD_LEN1` [uncovered]：对应 R04、R12；固定窗口中由过去接受沿 host_rd_len=1 关联两拍连续 mem 读、八拍连续 device 读及当前完成，期望获得两字读见证。 当前证据：该cover在当前depth12 Cover运行未命中，只报告uncovered；没有不可达证明，不能登记为RTL_BUG。需要独立增加覆盖深度或检查触发轨迹；不增加公平性、长度限制或默认disable iff来取得命中。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。

`C_CK_COVER_WR_LEN1` [uncovered]：对应 R04、R12；固定窗口中由过去接受沿 host_wr_len=1 关联八拍连续 device 写、两个固定位置 mem 写及当前完成，期望获得两字写见证。 当前证据：该cover在当前depth12 Cover运行未命中，只报告uncovered；没有不可达证明，不能登记为RTL_BUG。需要独立增加覆盖深度或检查触发轨迹；不增加公平性、长度限制或默认disable iff来取得命中。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。

`C_CK_COVER_WR_LONGER_PROGRESS` [uncovered]：对应 R04、R12；固定窗口中接受沿 host_wr_len>1 后出现十二拍连续 device 写及三个固定位置 mem 写，期望展示更长写事务局部进度；不要求完成任意 len。 当前证据：该cover在当前depth12 Cover运行未命中，只报告uncovered；没有不可达证明，不能登记为RTL_BUG。需要独立增加覆盖深度或检查触发轨迹；不增加公平性、长度限制或默认disable iff来取得命中。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。

`C_CK_COVER_RD_THREE_COMMANDS` [uncovered]：对应 R02、R12；固定 21 拍窗口中三次接受沿均携带 host_rd_len=0，且按接受、唯一 mem 读、四拍 device 读、done、下一拍接受的节奏连续出现，期望获得三读命令见证。 当前证据：该cover在当前depth12 Cover运行未命中，只报告uncovered；没有不可达证明，不能登记为RTL_BUG。需要独立增加覆盖深度或检查触发轨迹；不增加公平性、长度限制或默认disable iff来取得命中。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。

`C_CK_COVER_WR_THREE_COMMANDS` [uncovered]：对应 R02、R12；固定 21 拍窗口中三次接受沿均携带 host_wr_len=0，且按接受、四拍 device 写、唯一 mem 写、done、下一拍接受的节奏连续出现，期望获得三写命令见证。 当前证据：该cover在当前depth12 Cover运行未命中，只报告uncovered；没有不可达证明，不能登记为RTL_BUG。需要独立增加覆盖深度或检查触发轨迹；不增加公平性、长度限制或默认disable iff来取得命中。 native辅助工程的具体义务、参数和run见06及08报告，其独立结果不改写本条guided状态。