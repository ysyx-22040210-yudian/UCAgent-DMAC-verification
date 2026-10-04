
# dmac 功能点与检测点描述

## DUT 整体功能描述

> 本文档由 `.formal_records.yaml` 自动生成，请勿手动编辑。

---

## 功能分组与检测点



### 1. 接口环境与协议假设

<FG-API>



#### 对应 R10、R13；在形式运行的首个采样点触发，期望只要求一个低有效复位样本以建立已知初态，其后 rst_n 仍可任意再次拉低；guided 仅对顶层复位输入建模，不假定只复位一次或同步断言。

<FC-API-RESET>

**检测点：**

- <CK-API-RESET-INITIAL> **(Style: Assume)** 对应 R10、R13；仅在形式时间零的首个采样点触发，要求 rst_n 为低以建立确定初态；此 Assume 不约束后续采样，必须允许运行中再次复位。



#### 对应 R02、R13；当某方向 host req 已提出但尚未 ack 时触发，期望该方向 req、haddr 和 len 保持到接受；guided 只加入规格明确的顶层等待保持，不限制地址、长度取值或请求等待时长。

<FC-API-HOST-WAIT>

**检测点：**

- <CK-API-HOST-RD-WAIT> **(Style: Assume)** 对应 R02、R13；当前一采样沿 host_rd_req 有效且 host_rd_ack 无效、期间未复位时触发，要求本采样沿 host_rd_req、host_rd_haddr、host_rd_len 保持；不限制其数值或等待周期数。
- <CK-API-HOST-WR-WAIT> **(Style: Assume)** 对应 R02、R13；当前一采样沿 host_wr_req 有效且 host_wr_ack 无效、期间未复位时触发，要求本采样沿 host_wr_req、host_wr_haddr、host_wr_len 保持；不限制其数值或等待周期数。



#### 对应 R01、R13；当 device 发起的读或写 req 尚未 ack 时触发，期望读 req 保持、写 req 与写数据保持；guided 不要求 device 必须在有限周期内请求或持续请求，因此不引入公平性。

<FC-API-DEVICE-WAIT>

**检测点：**

- <CK-API-DEV-RD-WAIT> **(Style: Assume)** 对应 R01、R13；当前一采样沿 dev_rd_req 有效且 dev_rd_ack 无效、期间未复位时触发，要求本采样沿 dev_rd_req 保持；不要求 device 在空闲时发起请求。
- <CK-API-DEV-WR-WAIT-REQ> **(Style: Assume)** 对应 R01、R13；当前一采样沿 dev_wr_req 有效且 dev_wr_ack 无效、期间未复位时触发，要求本采样沿 dev_wr_req 保持。
- <CK-API-DEV-WR-WAIT-DATA> **(Style: Assume)** 对应 R01、R13；当前一采样沿 dev_wr_req 有效且 dev_wr_ack 无效、期间未复位时触发，要求本采样沿 dev_wr_data 保持；不限制数据内容。


---


### 2. 主机命令接受与排队

<FG-HOST>



#### 对应 R02；当任一 host ack 置位时触发，期望同方向 req 同时有效且该沿唯一接受命令；guided 可直接判定 ack 不得脱离 req，但不引用不存在的 busy 端口。

<FC-HOST-ACK>

**检测点：**

- <CK-HOST-RD-ACK-REQ> **(Style: Comb)** 对应 R02；当 host_rd_ack 为高时触发，期望同拍 host_rd_req 与 rst_n 均为高，禁止无请求或复位中确认读命令。
- <CK-HOST-WR-ACK-REQ> **(Style: Comb)** 对应 R02；当 host_wr_ack 为高时触发，期望同拍 host_wr_req 与 rst_n 均为高，禁止无请求或复位中确认写命令。



#### 对应 R02、R03、R04；当 req&&ack 接受命令时触发，期望随后首地址和零长度等外部行为使用该沿的 haddr 与 len；guided 通过顶层后续行为检查可见锁存效果，不读取内部地址或计数寄存器。

<FC-HOST-LATCH>

**检测点：**

- <CK-HOST-RD-LATCH-ADDRESS> **(Style: Seq)** 对应 R02、R03；读命令接受后的紧邻周期出现首个 mem_rd_valid 且两拍 rst_n 均高时，期望 mem_rd_addr 等于接受沿 host_rd_haddr；只检查无等待的一拍固定窗口。
- <CK-HOST-WR-LATCH-ADDRESS> **(Style: Seq)** 对应 R02、R03；写命令接受后紧接四拍连续 device 写握手，并在再下一拍首次出现 mem_wr_valid 的固定窗口中，期望 mem_wr_addr 等于接受沿 host_wr_haddr；任意等待下的锁存归 native 模型。



#### 对应 R02；当已接受命令尚未完成且未复位时触发，期望同方向即使保持或重新提出 req 也不出现第二次 ack；guided 以可见接受/完成历史维护局部活动状态，不把另一方向活动误作阻塞条件。

<FC-HOST-BUSY>

**检测点：**

- <CK-HOST-RD-NO-IMMEDIATE-REACK> **(Style: Seq)** 对应 R02；当前一采样沿接受读命令、本采样尚未复位且不可能已完成时触发，期望 host_rd_ack 为低，即使 host_rd_req 继续为高也不重复接受。
- <CK-HOST-WR-NO-IMMEDIATE-REACK> **(Style: Seq)** 对应 R02；当前一采样沿接受写命令、本采样尚未复位且不可能已完成时触发，期望 host_wr_ack 为低，即使 host_wr_req 继续为高也不重复接受。



#### 对应 R02、R12；当 pending req 跨越 done 周期时触发，期望 done 当周期不 ack，而后续空闲周期可以接受；guided 检查有限边界时序，不承诺在 req 未遵守保持或复位重入时接受。

<FC-HOST-NEXT>

**检测点：**

- <CK-HOST-RD-DONE-NO-ACK> **(Style: Comb)** 对应 R02；当 host_rd_done 为高时触发，期望 host_rd_ack 同拍为低，完成报告周期不得接受下一读命令。
- <CK-HOST-WR-DONE-NO-ACK> **(Style: Comb)** 对应 R02；当 host_wr_done 为高时触发，期望 host_wr_ack 同拍为低，完成报告周期不得接受下一写命令。
- <CK-HOST-RD-PENDING-AFTER-DONE> **(Style: Seq)** 对应 R02、R12；当读 req 按协议保持跨越前一拍 host_rd_done、前后两拍 rst_n 均高时，期望当前空闲拍 host_rd_ack 为高并接受等待命令。
- <CK-HOST-WR-PENDING-AFTER-DONE> **(Style: Seq)** 对应 R02、R12；当写 req 按协议保持跨越前一拍 host_wr_done、前后两拍 rst_n 均高时，期望当前空闲拍 host_wr_ack 为高并接受等待命令。


---


### 3. 内存到设备读通道

<FG-READ>



#### 对应 R01、R05；在 mem_rd_valid 与 mem_rd_ready 组合变化时触发，期望仅两者同高的上升沿接收一拍 64 位数据，ready 同沿携带有效读数据；guided 仅依据顶层握手判定传输，不构造独立响应通道。

<FC-READ-MEM-HANDSHAKE>

**检测点：**

- <CK-READ-MEM-FIRST-AFTER-ACCEPT> **(Style: Seq)** 对应 R01、R03；读命令在前一拍接受且当前未复位时，期望当前拍呈现以接受地址为首地址的 mem_rd_valid；若当前 ready 为高则同沿接收 mem_rd_data。



#### 对应 R01、R06；当 device 发起 dev_rd_req 时触发，期望仅在有可交付数据时由 dev_rd_ack 同沿交付一个 16 位片段，ack 不得脱离 req；guided 检查顶层 req/ack/data，不读取 FIFO 有效位。

<FC-READ-DEVICE-HANDSHAKE>

**检测点：**

- <CK-READ-DEV-ACK-REQ> **(Style: Comb)** 对应 R01、R06；当 dev_rd_ack 为高时触发，期望同拍 dev_rd_req 与 rst_n 为高；该沿的 dev_rd_data 才解释为一个有效 16 位交付。



#### 对应 R05、R08；当 memory 与 device 的背压模式不同时触发，期望读侧可预取并按握手独立推进，且未握手时不误计传输；guided 只检查外部握手和稳定性，内部深度、空满及全部排队顺序由 native 模型承担。

<FC-READ-PIPELINE>

**检测点：**

- <CK-READ-NO-DEV-TRANSFER-WITHOUT-REQ> **(Style: Comb)** 对应 R01、R08；当 dev_rd_req 为低时触发，期望 dev_rd_ack 为低，无论 memory 是否正在预取，禁止无 device 请求交付。
- <CK-READ-DEV-FRAGMENT-HOLD> **(Style: Seq)** 对应 R06；当无积压歧义的 len=0 读命令接受、下一拍完成唯一 mem 读，并在再下一拍发生首个 device 交付的固定三拍窗口中，期望首片段等于该 mem 字的低 16 位；完整读数据顺序仍由 NCK-R06-RD-DATA 负责。


---


### 4. 设备到内存写通道

<FG-WRITE>



#### 对应 R01、R07；当 device 发起 dev_wr_req 时触发，期望仅 dev_wr_req&&dev_wr_ack 的上升沿接收一拍 16 位数据，ack 不得脱离 req；guided 观察顶层握手，不读取收集剩余计数或 lane。

<FC-WRITE-DEVICE-HANDSHAKE>

**检测点：**

- <CK-WRITE-DEV-ACK-REQ> **(Style: Comb)** 对应 R01、R07；当 dev_wr_ack 为高时触发，期望同拍 dev_wr_req 与 rst_n 为高；仅该沿采样 dev_wr_data。



#### 对应 R01、R05、R07；当 mem_wr_valid 置位或遭遇 ready 背压时触发，期望 valid&&ready 同沿提交完整地址和 64 位数据，未握手不提交；guided 直接检查顶层 valid/ready/address/data。

<FC-WRITE-MEM-HANDSHAKE>

**检测点：**

- <CK-WRITE-MEM-VALID-AFTER-WORD> **(Style: Seq)** 对应 R01、R07；写命令接受后紧接四拍连续 dev_wr_req&&dev_wr_ack，在再下一拍的固定窗口中期望 mem_wr_valid 呈现所拼完整字；只判定该连续窗口，不要求环境总是连续请求。



#### 对应 R07、R08；当 device 连续提供片段而 memory 背压时触发，期望允许顶层可见范围内的片段收集并在容量边界施加反压，不出现越权 ack；guided 不推断内部 FIFO 空满，完整容量与排队顺序保留给 native 模型。

<FC-WRITE-PIPELINE>

**检测点：**

- <CK-WRITE-NO-DEV-TRANSFER-WITHOUT-REQ> **(Style: Comb)** 对应 R01、R08；当 dev_wr_req 为低时触发，期望 dev_wr_ack 为低，禁止无 device 请求采样写片段。
- <CK-WRITE-STALLED-WORD-NOT-OVERWRITTEN> **(Style: Seq)** 对应 R05、R08；当前一采样 mem_wr_valid 高且 mem_wr_ready 低、期间未复位时触发，期望本采样仍呈现同一 mem_wr_valid、地址和数据，即使 device 侧继续具备局部收集条件。


---


### 5. 内存地址生成与保持

<FG-ADDRESS>



#### 对应 R03；在读命令接受后紧邻读 valid，或写命令接受后四拍连续 device 握手再出现首个写 valid 的固定窗口中，期望 mem 地址等于接受沿任意 haddr；任意等待下完整命令关联由 native 模型承担。

<FC-ADDRESS-FIRST>

**检测点：**

- <CK-ADDRESS-RD-FIRST> **(Style: Seq)** 对应 R03；读命令接受后的紧邻周期出现首个 mem_rd_valid 且两拍 rst_n 均高时，期望 mem_rd_addr 等于接受沿 host_rd_haddr，包括低三位非零值。
- <CK-ADDRESS-WR-FIRST> **(Style: Seq)** 对应 R03；写命令接受后紧接四拍连续 device 写握手，并在再下一拍出现首个 mem_wr_valid 时，期望 mem_wr_addr 等于接受沿 host_wr_haddr，包括低三位非零值。



#### 对应 R03；当前一采样沿发生对应 mem valid&&ready 且事务继续时触发，期望下一可见地址按 32 位加 8；guided 检查局部相邻握手关系，长序列参考地址可由 native 模型交叉检查。

<FC-ADDRESS-STEP>

**检测点：**

- <CK-ADDRESS-RD-STEP> **(Style: Seq)** 对应 R03；当前一采样沿 mem_rd_valid&&mem_rd_ready 且下一读拍仍有效、期间未复位时触发，期望 mem_rd_addr 等于前一地址按 32 位加 8。
- <CK-ADDRESS-WR-STEP> **(Style: Seq)** 对应 R03；当前一采样沿 mem_wr_valid&&mem_wr_ready 且下一写拍仍有效、期间未复位时触发，期望 mem_wr_addr 等于前一地址按 32 位加 8。



#### 对应 R03、R05；当 mem valid 高而 ready 低时触发，期望同方向地址在持续等待期间保持；guided 可直接检查顶层稳定性，不限制背压持续时间。

<FC-ADDRESS-HOLD>

**检测点：**

- <CK-ADDRESS-RD-HOLD> **(Style: Seq)** 对应 R03、R05；当前一采样 mem_rd_valid 高且 mem_rd_ready 低、期间未复位时触发，期望 mem_rd_valid 继续为高且 mem_rd_addr 不变。
- <CK-ADDRESS-WR-HOLD> **(Style: Seq)** 对应 R03、R05；当前一采样 mem_wr_valid 高且 mem_wr_ready 低、期间未复位时触发，期望 mem_wr_valid 继续为高且 mem_wr_addr 不变。



#### 对应 R03；当地址接近 32 位上界并发生 mem 握手时触发，期望加 8 后按 32 位自然回绕而非饱和或对齐；guided 通过顶层相邻地址判定并以 Cover 展示边界可达。

<FC-ADDRESS-WRAP>

**检测点：**

- <CK-ADDRESS-RD-WRAP> **(Style: Seq)** 对应 R03；当前一读地址位于 32 位上界附近并完成握手、下一读拍有效时触发，期望下一 mem_rd_addr 为前值加 8 的低 32 位。
- <CK-ADDRESS-WR-WRAP> **(Style: Seq)** 对应 R03；当前一写地址位于 32 位上界附近并完成握手、下一写拍有效时触发，期望下一 mem_wr_addr 为前值加 8 的低 32 位。


---


### 6. 长度编码与传输配额

<FG-QUOTA>



#### 对应 R04；只在无等待的固定有限窗口中核对接受沿 len=0/1 与一/两拍 64 位 mem 字及四/八拍 16 位 device 数据的关系；不限制其他命令 len，任意 32 位编码由 NCK-R04-COUNT 证明。

<FC-QUOTA-ENCODING>

**检测点：**

- <CK-QUOTA-ENCODING-BOUNDARY> **(Style: Seq)** 对应 R04；当固定窗口内可由过去的 host req&&ack 明确归属 len=0 或 len=1 命令时，检查窗口中的 mem/device 拍数按 1:4 编码；不使用完成时当前 host_len，任意等待和全长度由 NCK-R04-COUNT 证明。



#### 对应 R04、R09；仅在 len=0 命令接受后紧接唯一 mem 拍和四个连续 device 拍的固定窗口中检查完成边界；不添加强迫连续握手的 Assume，任意背压配额由 native 模型承担。

<FC-QUOTA-ZERO>

**检测点：**

- <CK-QUOTA-RD-ZERO> **(Style: Seq)** 对应 R04、R09；固定窗口为过去接受 host_rd_len=0、下一拍唯一 mem 读、随后四拍连续 device 读，当前期望 done；该局部窗口不声称覆盖任意等待。
- <CK-QUOTA-WR-ZERO> **(Style: Seq)** 对应 R04、R09；固定窗口为过去接受 host_wr_len=0、随后四拍连续 device 写、再下一拍唯一 mem 写握手，当前期望 done；该局部窗口不声称覆盖任意等待。



#### 对应 R04、R12；仅在 len=1 命令的两拍 mem 与八拍 device 均落入明确连续窗口时检查首字边界不提前完成及第二字完成；任意背压和 33 位全空间由 NCK-R04-COUNT 与 NCK-R09-DONE 负责。

<FC-QUOTA-LONG>

**检测点：**

- <CK-QUOTA-RD-LEN1> **(Style: Seq)** 对应 R04、R09；以过去接受沿 host_rd_len=1 关联两拍连续 mem 读和随后八拍连续 device 读的固定窗口，检查首字边界无 done、第二字边界后 done；不约束环境必须形成该窗口。
- <CK-QUOTA-WR-LEN1> **(Style: Seq)** 对应 R04、R09；以过去接受沿 host_wr_len=1 关联八拍连续 device 写及两个固定位置 mem 写握手的有限窗口，检查首字提交无 done、第二字提交后 done；任意等待由 native 模型负责。


---


### 7. 数据拆分、拼接与顺序

<FG-DATA>



#### 对应 R06；在过去接受 len=0、下一拍唯一 mem 读、再下一拍首个 device 读的无积压固定窗口中，期望交付该字 [15:0]；任意 FIFO 积压由 NCK-R06-RD-DATA 负责。

<FC-DATA-READ-FIRST>

**检测点：**

- <CK-DATA-RD-LOW-FIRST> **(Style: Seq)** 对应 R06；固定三拍窗口由过去 host_rd_req&&host_rd_ack 且 host_rd_len=0、下一拍 mem_rd_valid&&mem_rd_ready、当前首个 dev_rd_req&&dev_rd_ack 组成，期望当前 dev_rd_data 等于该 mem 字 [15:0]。



#### 对应 R06；仅在过去接受 len=0、唯一 mem 读后连续四拍有效 device 握手的固定窗口中，期望依次匹配四个 16 位片段；不声明覆盖等待或积压数据。

<FC-DATA-READ-LANES>

**检测点：**

- <CK-DATA-RD-FOUR-LANES> **(Style: Seq)** 对应 R06；固定窗口由过去接受 len=0、唯一 mem 读及随后四拍连续 dev_rd_req&&dev_rd_ack 构成，期望四拍数据依次为该 mem 字 [15:0]、[31:16]、[47:32]、[63:48]；深历史须充分有效。



#### 对应 R07；仅在过去接受 len=0 后连续四拍 device 写并在下一拍出现首个 mem 写字的固定窗口中，期望低片段优先拼接；任意等待与积压由 NCK-R07-WR-DATA 负责。

<FC-DATA-WRITE-PACK>

**检测点：**

- <CK-DATA-WR-FOUR-LANES> **(Style: Seq)** 对应 R07；固定窗口由过去 host_wr_req&&host_wr_ack 且 len=0、随后四拍连续 dev_wr_req&&dev_wr_ack、当前首个 mem_wr_valid 构成，期望 mem_wr_data 四个片段按四次接收先后映射。



#### 对应 R06、R07；仅在过去接受 len=1 且两个完整字按预定连续握手窗口传输时检查两个字的局部先后及数据映射；任意等待、积压与完整无损顺序保持为 native 义务。

<FC-DATA-ORDER-BOUNDARY>

**检测点：**

- <CK-DATA-RD-TWO-WORD-LOCAL-ORDER> **(Style: Seq)** 对应 R06；固定窗口由过去接受 len=1、两拍连续 mem 读及随后八拍连续 device 读构成，期望前四片段来自先接收字、后四片段来自后接收字；不覆盖任意 FIFO 积压。
- <CK-DATA-WR-TWO-WORD-LOCAL-ORDER> **(Style: Seq)** 对应 R07；固定窗口由过去接受 len=1、八拍连续 device 写及两个固定位置 mem 写字构成，期望第一组四片段字先提交、第二组后提交；任意积压由 NCK-R07-WR-DATA 负责。


---


### 8. 背压流控与缓冲行为

<FG-FLOW>



#### 对应 R05；当 mem_rd_valid 高而 mem_rd_ready 低时触发，期望 valid 保持且 mem_rd_addr 稳定直至握手或复位；guided 直接检查顶层信号，不限制背压长度。

<FC-FLOW-READ-STALL>

**检测点：**

- <CK-FLOW-RD-VALID-ADDRESS-HOLD> **(Style: Seq)** 对应 R05；当前一采样 mem_rd_valid 高且 mem_rd_ready 低、期间未复位时触发，期望本采样 mem_rd_valid 仍高且 mem_rd_addr 稳定；任意长背压逐拍适用。



#### 对应 R05；当 mem_wr_valid 高而 mem_wr_ready 低时触发，期望 valid、mem_wr_addr 和 mem_wr_data 均稳定直至握手或复位；guided 可完整表达此顶层安全义务。

<FC-FLOW-WRITE-STALL>

**检测点：**

- <CK-FLOW-WR-VALID-ADDRESS-DATA-HOLD> **(Style: Seq)** 对应 R05；当前一采样 mem_wr_valid 高且 mem_wr_ready 低、期间未复位时触发，期望本采样 mem_wr_valid 仍高，mem_wr_addr 与 mem_wr_data 均稳定；不限制背压持续时间。



#### 对应 R01、R08；当 device req 低或命令无可见传输资格时触发，期望对应 ack 不形成脱离请求的传输；guided 检查 req/ack 关系，不以内部 FIFO 空满作为属性前提。

<FC-FLOW-DEVICE-GATING>

**检测点：**

- <CK-FLOW-DEV-RD-ACK-GATED> **(Style: Comb)** 对应 R01、R08；当 dev_rd_req 为低或 rst_n 为低时触发，期望 dev_rd_ack 为低；不以内层 FIFO valid 作为前提。
- <CK-FLOW-DEV-WR-ACK-GATED> **(Style: Comb)** 对应 R01、R08；当 dev_wr_req 为低或 rst_n 为低时触发，期望 dev_wr_ack 为低；不以内层配额或 FIFO ready 作为前提。



#### 对应 R08；当读预取或写提交遭遇连续不对称背压时触发，期望顶层不会覆盖被阻塞的有效写拍或产生无请求设备握手；guided 仅检查可见后果，FIFO 容量、同拍替换、指针和深度 1/3 由 NCK-R08 系列负责。

<FC-FLOW-BUFFER-BOUNDARY>

**检测点：**

- <CK-FLOW-BUFFER-WR-VISIBLE-HOLD> **(Style: Seq)** 对应 R08；当外部可见 mem 写队首遭遇背压时触发，期望地址和数据保持而不被后续 device 片段覆盖；只判定顶层后果。
- <CK-FLOW-BUFFER-NO-SPURIOUS-DEV-ACK> **(Style: Comb)** 对应 R08；当任一 device req 无效时触发，期望其 ack 无效，不因内部同拍 FIFO 入出队或替换产生可见伪传输；内部 FIFO 行为由 NCK-R08 系列另证。


---


### 9. 异步复位与事务中断

<FG-RESET>



#### 对应 R10；只要 rst_n 为低即触发，期望 host ack/done、mem valid 和 device ack 均为低；guided 不通过 disable 条件跳过复位周期，而是直接检查顶层复位行为。

<FC-RESET-SILENCE>

**检测点：**

- <CK-RESET-HOST-SILENCE> **(Style: Comb)** 对应 R10；任一采样或组合观察中 rst_n 为低时触发，期望 host_rd_ack、host_wr_ack、host_rd_done、host_wr_done 全部为低。
- <CK-RESET-DATA-CHANNEL-SILENCE> **(Style: Comb)** 对应 R10；任一采样或组合观察中 rst_n 为低时触发，期望 mem_rd_valid、mem_wr_valid、dev_rd_ack、dev_wr_ack 全部为低。



#### 对应 R10；当读写活动、mem 背压或设备部分片段期间 rst_n 再次拉低时触发，期望当前命令立即中断且接口静默；guided 用顶层历史和 Cover 检查中断，内部状态清除由 NCK-R10-RESET 补足。

<FC-RESET-INTERRUPT>

**检测点：**

- <CK-RESET-INTERRUPT-RD-STALL> **(Style: Seq)** 对应 R10；当前一采样 mem_rd_valid 高且被背压、随后 rst_n 拉低时触发，期望复位采样的 mem_rd_valid 与读侧 ack/done 均为低。
- <CK-RESET-INTERRUPT-WR-STALL> **(Style: Seq)** 对应 R10；当前一采样 mem_wr_valid 高且被背压、随后 rst_n 拉低时触发，期望复位采样的 mem_wr_valid 与写侧 ack/done 均为低。
- <CK-RESET-INTERRUPT-DEVICE-PARTIAL> **(Style: Seq)** 对应 R10；固定两拍窗口中前一拍发生任一 device 握手而当前 rst_n 拉低时，期望当前两个 device ack 和两个 done 均为低；内部 lane 与部分拼接清除留给 NCK-R10-RESET。



#### 对应 R09、R10；当命令在最终目标握手前被复位中断时触发，期望复位期间及释放后的旧命令不产生 done；guided 检查可见 done 因果窗口，完整命令身份隔离由 native 模型承担。

<FC-RESET-NO-DONE>

**检测点：**

- <CK-RESET-RD-DONE-CLEAR> **(Style: Seq)** 对应 R09、R10；当当前 rst_n 低，或前一拍 rst_n 低而当前已释放且尚未接受新读命令时，期望 host_rd_done 为低；旧命令不得在释放后一拍补发完成。
- <CK-RESET-WR-DONE-CLEAR> **(Style: Seq)** 对应 R09、R10；当当前 rst_n 低，或前一拍 rst_n 低而当前已释放且尚未接受新写命令时，期望 host_wr_done 为低；旧命令不得在释放后一拍补发完成。



#### 对应 R10、R12；仅在复位释放后紧接新命令接受及无等待首地址窗口中检查使用新 haddr 且旧 done 不残留；任意等待及完整旧数据隔离由 native 数据模型证明。

<FC-RESET-RESTART>

**检测点：**

- <CK-RESET-RD-RESTART-ADDRESS> **(Style: Seq)** 对应 R10；过去两拍依次为复位低、接受新读命令，当前紧邻出现 mem_rd_valid 时，期望 mem_rd_addr 使用该接受沿的新 host_rd_haddr 且旧 host_rd_done 未出现。
- <CK-RESET-WR-RESTART-ADDRESS> **(Style: Seq)** 对应 R10；复位释放后接受新写命令，紧接四拍连续 device 写并在下一拍出现 mem_wr_valid 的固定窗口中，期望 mem_wr_addr 使用接受沿的新 host_wr_haddr 且旧 done 未出现。


---


### 10. 双向并发与相互独立

<FG-CONCURRENT>



#### 对应 R01、R11；当复位释放后的空闲边界读写 host req 同时有效时，期望两个方向可在同一拍各自 ack；guided 检查该固定边界，不以另一方向为约束。

<FC-CONCURRENT-ACCEPT>

**检测点：**

- <CK-CONCURRENT-ACCEPT-AFTER-RESET> **(Style: Seq)** 对应 R01、R11；当前一采样处于复位、释放后读写 req 同时有效且两个 done 均低时触发，期望 host_rd_ack 与 host_wr_ack 同拍均为高，检查接受路径不互斥。



#### 对应 R11；分别探测 mem 侧和 device 侧读写握手同拍成立的可达性；这些 Cover 不证明互不干扰，跨通道安全由各方向进度属性及独立 native oracle 负责。

<FC-CONCURRENT-TRANSFER>

**检测点：**

- <CK-CONCURRENT-MEM-TRANSFER> **(Style: Cover)** 对应 R11；以 mem_rd_valid&&mem_rd_ready 与 mem_wr_valid&&mem_wr_ready 同拍成立为触发场景，期望获得两个 64 位 mem 传输并发可达见证；Cover 不证明互不干扰。
- <CK-CONCURRENT-DEVICE-TRANSFER> **(Style: Cover)** 对应 R11；以 dev_rd_req&&dev_rd_ack 与 dev_wr_req&&dev_wr_ack 同拍成立为触发场景，期望获得两个 16 位 device 传输并发可达见证；Cover 不证明互不干扰。



#### 对应 R01、R11；在一侧 mem valid 被背压且另一侧同拍已具备完整握手的局部窗口，检查被阻塞侧保持并记录另一侧实际握手；不要求背压解除，完整无跨通道约束行为由 native RD/WR_PROGRESS oracle 负责。

<FC-CONCURRENT-STALL>

**检测点：**

- <CK-CONCURRENT-RD-STALL-WR-HANDSHAKE> **(Style: Seq)** 对应 R01、R11；当前拍写 mem 握手成立且前一拍读 mem valid 被 ready 低阻塞、两拍未复位时，期望读 valid 和地址保持；写握手本身只作为观察条件，不作同义后件。
- <CK-CONCURRENT-WR-STALL-RD-HANDSHAKE> **(Style: Seq)** 对应 R01、R11；当前拍读 mem 握手成立且前一拍写 mem valid 被 ready 低阻塞、两拍未复位时，期望写 valid、地址和数据保持；读握手本身只作为观察条件。



#### 对应 R09、R11；在可由固定 len=0 窗口确认读最终 device 握手与写最终 mem 握手同沿发生时，期望下一拍两个 done 同时呈现；任意长度最终身份由 NCK-R11-DUPLEX 负责。

<FC-CONCURRENT-DONE>

**检测点：**

- <CK-CONCURRENT-SIMULTANEOUS-DONE> **(Style: Seq)** 对应 R09、R11；当前两个 done 同时为高时检查前一拍读 dev 与写 mem 目标握手均成立；并发完成的固定窗口可达性另由 Cover 检查，任意长度最终身份由 native 双模型补足。


---


### 11. 完成时序与命令边界

<FG-DONE>



#### 对应 R09；当 host_rd_done 或 host_wr_done 置位时触发，期望下一采样周期回落，不连续保持或重复；guided 可直接检查脉冲宽度，命令级唯一性由 native 序号模型补足。

<FC-DONE-PULSE>

**检测点：**

- <CK-DONE-RD-ONE-CYCLE> **(Style: Seq)** 对应 R09；当前一采样 host_rd_done 为高且本采样未复位时触发，期望 host_rd_done 已回落，禁止连续两个周期保持读完成。
- <CK-DONE-WR-ONE-CYCLE> **(Style: Seq)** 对应 R09；当前一采样 host_wr_done 为高且本采样未复位时触发，期望 host_wr_done 已回落，禁止连续两个周期保持写完成。



#### 对应 R09；当 host_rd_done 置位时触发，期望前一采样沿发生 dev_rd_req&&dev_rd_ack；guided 证明可见目标端因果，任意长度最终拍身份由 NCK-R09-DONE 负责。

<FC-DONE-READ-CAUSE>

**检测点：**

- <CK-DONE-RD-PREV-DEV-HANDSHAKE> **(Style: Seq)** 对应 R09；当 host_rd_done 为高时触发，期望前一采样沿 dev_rd_req&&dev_rd_ack 成立且 rst_n 为高；不把后件直接用作 guard，最终配额身份由 NCK-R09-DONE 证明。



#### 对应 R09；当 host_wr_done 置位时触发，期望前一采样沿发生 mem_wr_valid&&mem_wr_ready；guided 证明可见目标端因果，完整任意长度因果由 native 配额模型负责。

<FC-DONE-WRITE-CAUSE>

**检测点：**

- <CK-DONE-WR-PREV-MEM-HANDSHAKE> **(Style: Seq)** 对应 R09；当 host_wr_done 为高时触发，期望前一采样沿 mem_wr_valid&&mem_wr_ready 成立且 rst_n 为高；不把后件直接用作 guard，最终配额身份由 NCK-R09-DONE 证明。



#### 对应 R02、R09；当某方向 done 为高且 host req 等待时触发，期望同方向 ack 为低，随后空闲周期方可接受；guided 直接检查顶层 ack/done 边界，不要求请求在复位时保持。

<FC-DONE-ACK-GAP>

**检测点：**

- <CK-DONE-RD-NO-ACK> **(Style: Comb)** 对应 R02、R09；当 host_rd_done 为高时触发，期望 host_rd_ack 为低，无论 host_rd_req 是否等待。
- <CK-DONE-WR-NO-ACK> **(Style: Comb)** 对应 R02、R09；当 host_wr_done 为高时触发，期望 host_wr_ack 为低，无论 host_wr_req 是否等待。
- <CK-DONE-RD-NEXT-ACK> **(Style: Seq)** 对应 R02、R09；当读 req 按协议跨越前一拍 done 保持且当前未复位时，期望当前 host_rd_done 已低并由 host_rd_ack 接受新命令。
- <CK-DONE-WR-NEXT-ACK> **(Style: Seq)** 对应 R02、R09；当写 req 按协议跨越前一拍 done 保持且当前未复位时，期望当前 host_wr_done 已低并由 host_wr_ack 接受新命令。


---


### 12. 业务场景可达性

<FG-COVERAGE>



#### 对应 R03、R12；读侧探测接受后紧邻首 valid，写侧探测接受后四拍连续 device 写再出现首 valid，且接受沿 haddr 低三位非零并原样呈现；不将非对齐或连续握手作为 Assume。

<FC-COVER-NONALIGNED>

**检测点：**

- <CK-COVER-RD-NONALIGNED> **(Style: Cover)** 对应 R03、R12；固定两拍窗口中先接受 host_rd_haddr[2:0] 非零的读命令，当前首个 mem_rd_valid 使用该接受沿地址，期望获得非对齐读见证。
- <CK-COVER-WR-NONALIGNED> **(Style: Cover)** 对应 R03、R12；固定六拍窗口中先接受 host_wr_haddr[2:0] 非零的写命令，随后四拍连续 device 写，当前首个 mem_wr_valid 使用接受沿地址，期望获得非对齐写见证。



#### 对应 R04、R09、R12；探测 len=0 接受后无等待形成完整固定事务窗口；不添加连续握手 Assume，Cover 也不替代任意背压安全判定。

<FC-COVER-ZERO>

**检测点：**

- <CK-COVER-RD-LEN0-COMPLETE> **(Style: Cover)** 对应 R04、R09、R12；固定七拍窗口依次为接受 host_rd_len=0、唯一 mem 读、四拍连续 device 读、当前 host_rd_done，期望获得读见证。
- <CK-COVER-WR-LEN0-COMPLETE> **(Style: Cover)** 对应 R04、R09、R12；固定七拍窗口依次为接受 host_wr_len=0、四拍连续 device 写、唯一 mem 写、当前 host_wr_done，期望获得写见证。



#### 对应 R04、R12；探测 len=1 完整连续窗口，以及 len>1 的固定连续多拍前缀；不限制其他输入，也不将有限见证称为全长度或任意背压证明。

<FC-COVER-LONG>

**检测点：**

- <CK-COVER-RD-LEN1> **(Style: Cover)** 对应 R04、R12；固定窗口中由过去接受沿 host_rd_len=1 关联两拍连续 mem 读、八拍连续 device 读及当前完成，期望获得两字读见证。
- <CK-COVER-WR-LEN1> **(Style: Cover)** 对应 R04、R12；固定窗口中由过去接受沿 host_wr_len=1 关联八拍连续 device 写、两个固定位置 mem 写及当前完成，期望获得两字写见证。
- <CK-COVER-RD-LONGER-PROGRESS> **(Style: Cover)** 对应 R04、R12；固定窗口中接受沿 host_rd_len>1 后出现三拍连续 mem 读及连续 device 读前缀，期望展示更长读事务局部进度；不要求完成任意 len。
- <CK-COVER-WR-LONGER-PROGRESS> **(Style: Cover)** 对应 R04、R12；固定窗口中接受沿 host_wr_len>1 后出现十二拍连续 device 写及三个固定位置 mem 写，期望展示更长写事务局部进度；不要求完成任意 len。



#### 对应 R02、R12；在深度 40 内探测同方向三条 len=0 命令各按固定无等待七拍节奏接受和完成；这是特定连续窗口 Cover，不证明任意等待或无限持续服务。

<FC-COVER-THREE-COMMANDS>

**检测点：**

- <CK-COVER-RD-THREE-COMMANDS> **(Style: Cover)** 对应 R02、R12；固定 21 拍窗口中三次接受沿均携带 host_rd_len=0，且按接受、唯一 mem 读、四拍 device 读、done、下一拍接受的节奏连续出现，期望获得三读命令见证。
- <CK-COVER-WR-THREE-COMMANDS> **(Style: Cover)** 对应 R02、R12；固定 21 拍窗口中三次接受沿均携带 host_wr_len=0，且按接受、四拍 device 写、唯一 mem 写、done、下一拍接受的节奏连续出现，期望获得三写命令见证。



#### 对应 R02、R12；探测 req 在前一拍 done 周期保持等待并于紧邻下一拍获 ack 的两拍窗口；环境等待保持 Assume 仍不限制此前等待长度。

<FC-COVER-PENDING>

**检测点：**

- <CK-COVER-RD-PENDING-NEXT> **(Style: Cover)** 对应 R02、R12；固定两拍窗口中 host_rd_req 在前一拍 host_rd_done 时有效且无 ack，当前仍有效并获得 host_rd_ack，期望获得等待读命令见证。
- <CK-COVER-WR-PENDING-NEXT> **(Style: Cover)** 对应 R02、R12；固定两拍窗口中 host_wr_req 在前一拍 host_wr_done 时有效且无 ack，当前仍有效并获得 host_wr_ack，期望获得等待写命令见证。



#### 对应 R10、R12；以紧邻采样的背压或 device 握手、再次复位及释放后新命令接受组成有限窗口，覆盖中断与恢复；不假定初始样本后复位保持高。

<FC-COVER-RESET-REENTRY>

**检测点：**

- <CK-COVER-RESET-RD-STALL> **(Style: Cover)** 对应 R10、R12；固定四拍窗口依次观察读 mem 背压、rst_n 再次拉低、释放并接受新读命令，期望获得读背压中断恢复见证。
- <CK-COVER-RESET-WR-STALL> **(Style: Cover)** 对应 R10、R12；固定四拍窗口依次观察写 mem 背压、rst_n 再次拉低、释放并接受新写命令，期望获得写背压中断恢复见证。
- <CK-COVER-RESET-PARTIAL-FRAGMENT> **(Style: Cover)** 对应 R10、R12；固定四拍窗口依次观察任一 device 握手、rst_n 再次拉低、释放并接受同方向新命令，期望获得部分进度中断见证。



#### 对应 R11、R12；以读写同拍接受并在固定短窗口中出现同拍读写有效握手为目标，期望获得双向并发见证；Cover 不证明内部双队列数据独立。

<FC-COVER-DUPLEX>

**检测点：**

- <CK-COVER-DUPLEX-OVERLAP> **(Style: Cover)** 对应 R11、R12；固定短窗口由过去读写命令同拍接受及当前读写 mem 或 device 握手同拍成立构成，期望获得双向并发传输见证。



#### 对应 R09、R11、R12；以两个方向当前 host done 同拍为触发目标，期望获得同时完成见证；命中只表明场景可达，不证明完成配额正确。

<FC-COVER-SIMULTANEOUS-DONE>

**检测点：**

- <CK-COVER-SIMULTANEOUS-DONE> **(Style: Cover)** 对应 R09、R11、R12；以 host_rd_done 与 host_wr_done 同一采样周期均为高为触发场景，期望获得双向同时完成见证；Cover 命中不证明完成配额正确。


---

