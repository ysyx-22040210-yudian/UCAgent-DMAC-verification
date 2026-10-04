# DMAC 静态源码审查与形式证据关联

审查人：Codex 工程师。内置 Agent 已实际读取两个 RTL，后因会话上下文达到上限无法继续；本报告由工程师通读当前固定 RTL 后撰写，通过原始版本校验编辑接口提交。没有登记原始 DUT 的已确认 RTL_BUG；这不等于证明设计没有任何缺陷。

## 审查基线

源码为 dmac/rtl/dmac.sv 与 dmac/rtl/dmac_fifo.sv。原始工作区与任务快照 SHA 相同，功能 RTL 未改动。默认参数 ADDR_W=32、LEN_W=32、FIFO_DEPTH=2。native 四组实例分别为32/32/2、32/8/1、16/8/3、32/1/4；其prove与Cover证据见06报告和逐属性证据表。guided BMC深度12的63条断言仍未决；该报告不能将单独native结果标为guided已证明。

## 逐项源码核对

| 对象与源码位置 | 行为与风险核对 | 当前证据与结论 |
| --- | --- | --- |
| dmac.sv:41–44、109–110、149–150 | 四个剩余拍计数均为LEN_W+1位，接受命令时先零扩展host_len再加1。全1的LEN_W=32长度可表达2^32拍；device配额模型使用LEN_W+3位表达4N。没有将len0误作零拍，没有按字节长度处理。 | native `A_CK_RD_FETCH_LEFT/RD_DELIVER_LEFT/WR_COLLECT_LEFT/WR_COMMIT_LEFT/RD_QUOTA/WR_QUOTA`四实例证明；length_encoding修改版真实反例能被检测。默认最大长度没有有限动态完成回放，但计数不变量证明中len取值自由。 |
| dmac.sv:106–115、146–150、162–164 | 首地址由各自host_haddr原样锁存，只有对应mem实际握手才加ADDR_W'(8)，自然按地址位宽回绕；不作8字节对齐截断。忙时host输入变化不能覆盖已经接受的地址或配额。 | native `A_CK_RD_ADDRESS/WR_ADDRESS`与`ACK_ADMISSION`，地址步进故障对照及回放；guided FIRST/STEP/HOLD/WRAP有界未决。未发现此处确定缺陷。 |
| dmac.sv:56–68、117–124 | 读数据从FIFO队首按2位lane选择16位；仅device实际握手使lane递增，第四lane出队；读目标端最后字第四lane完成后done。FIFO非空与active共同控制ack。 | native `A_CK_RD_LANE/RD_DATA/RD_OCCUPANCY/RD_HEAD_VALID/RD_NO_EXTRA_DEV`，独立shift-queue与计数模型；read_lane修改版反例和原版对照回放。 |
| dmac.sv:70–90、154–160 | 写方向前三个16位允许在FIFO满时继续收集，第四片段要求队列空间。wr_assembled先复制pack再替换本lane，只有第四片段push；该拍入队值包含当前dev_wr_data。lane推进和pack更新只发生在req&&ack。 | native `A_CK_WR_LANE/WR_PACK/WR_PACK_UNUSED_ZERO/WR_ASSEMBLY/WR_DATA/WR_OCCUPANCY`；write_lane修改版反例。完整任意背压数据模型来自native具体实例，guided连续窗口不能替代。 |
| dmac.sv:51–54、101、119–124、141、162–167 | host_ack要求对应通道空闲且非done周期；done默认每拍清零，读在最后目标device握手、写在最后目标mem握手置位。done周期保留，pending命令之后再接受。 | native `A_CK_RD_DONE/WR_DONE/RD_COMPLETE_COUNTS/WR_COMPLETE_COUNTS/*_ACK_ADMISSION`；early_done修改版反例。没有把done与源端最后一拍混淆。 |
| dmac_fifo.sv:16–20、40–48 | PTR_W在DEPTH=1仍至少1位，COUNT_W能表示0..DEPTH；指针比较DEPTH-1后显式回零，非二次幂深度不依赖自然位宽回绕。DEPTH=0/WIDTH=0不在合法参数域；SYNTHESIS排除仿真参数诊断，因此工程必须保持正参数。 | native FIFO深度1/2/3/4具体实例的`A_CK_FIFO_RANGE/POINTER/COUNT`与槽次序证明；D1/D3/D4覆盖。尚未对全部正整数参数量化证明。 |
| dmac_fifo.sv:23–28、40–50 | 满队列出队时in_ready仍为真以允许替换；入/出同时发生时count不变。DEPTH=1同址读写在时钟前读旧head，在NBA写入新值，下拍新head；非二次幂指针显式推进。没有组合环：in_ready依赖pop，pop依赖out_valid/out_ready，out_valid只依赖count/rst_n。 | 独立shift-queue oracle逐槽检查顺序与队首，`A_CK_FIFO_HEAD/READY/VALID`及`C_CK_FIFO_FULL_REPLACE`；fifo_pop修改版反例。物理RAM读写模式仍由综合实现决定，本轮验证RTL寄存器模型。 |
| dmac.sv:53–59、72–81、92–99、131–139；dmac_fifo.sv:23–28、30–34 | 低有效异步复位清active、地址、配额、lane、pack、done及FIFO指针/count；storage内容未逐槽复位但空队列时out_data=0且旧storage不可见。再次复位中断命令而不生成done，新命令无有效残留。 | native reset oracle与FIFO数据有效条件、复位中断Cover以及reset_lane修改版反例，原始复位业务VCD已Icarus回放。亚周期毛刺、恢复/移除时序不在数字采样证明范围内。 |
| dmac.sv:92–129、131–172与两个独立FIFO实例 | 读写方向各自寄存器、lane、配额与FIFO，数据未跨接。单侧背压只影响对应队列；在环境能服务时局部progress成立。 | native两个独立oracle同时证明，`A_CK_RD_PROGRESS/WR_PROGRESS`及duplex完成Cover/回放。没有加入公平性Assume，不声明永久背压下最终完成。 |

## 仍未闭合的审查范围

本轮没有发现需要登记为原始DUT缺陷的确定源码问题，bugs=[]。上述静态核对给出实现依据和具体native证据，不以“没有BMC反例”消除疑点。主任务63条断言的无界prove、7个未命中覆盖目标、全部参数量化、完整空洞性/COI/无界活性、FormalMC/VCS目标工具验收仍未完成。它们是明确保留的验证缺口，不是假造的BG-NA静态误报。

七项故意修改RTL的失败运行仅用于检测敏感性，不能写入当前原始DUT的Bug列表。19次Icarus包括7次修改版反例匹配、7次原版对照不匹配及5次原始业务轨迹匹配；不是guided主任务发现了7个缺陷。
