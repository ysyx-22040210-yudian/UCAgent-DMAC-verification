"""Build a Chinese verification dossier from fixed DMAC records and actual evidence.

This documentation helper needs PyYAML and Markdown. It does not run formal tools,
edit the original machine records or change a property result.
"""
import collections
import csv
import hashlib
import json
from pathlib import Path
import re

import markdown
import yaml


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'verification/reports'
DOCS = ROOT / 'docs'
GUIDED_BMC = 'sby-872c6e8dd8bc4642988787232188507c'
GUIDED_COVER = 'sby-36b62d07a5ac4849952f6b3aca922448'
STYLES = {'Assume': '环境假设', 'Comb': '组合断言', 'Seq': '时序断言', 'Cover': '业务覆盖'}


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def cell(value):
    return str(value).replace('|', '\\|').replace('\n', '<br>')


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |',
                      '| ' + ' | '.join('---' for _ in headers) + ' |'] +
                     ['| ' + ' | '.join(cell(v) for v in row) + ' |' for row in rows]) + '\n\n'


def label(point):
    prefix = 'M_' if point['style'] == 'Assume' else ('C_' if point['style'] == 'Cover' else 'A_')
    return prefix + point['id'].replace('-', '_')


def options(path):
    text = path.read_text(encoding='utf-8')
    block = text.split('[options]', 1)[1].split('[', 1)[0]
    return dict(line.split(None, 1) for line in block.strip().splitlines() if line.strip())


def load_inputs():
    records = yaml.safe_load((REPORTS / 'guided/.formal_records.yaml').read_text(encoding='utf-8'))
    with (REPORTS / 'testpoint-evidence.csv').open(encoding='utf-8-sig', newline='') as f:
        evidence = list(csv.DictReader(f))
    guided = {r['属性编号']: r for r in evidence if r['运行案例'] == 'guided-current'}
    points = [(g, f, p) for g in records['spec']['function_groups']
              for f in g['functions'] for p in f['check_points']]
    counts = collections.Counter(p['style'] for _, _, p in points)
    audit = read_json(REPORTS / 'final-state-audit.json')
    assert len(points) == 88 and len({p['id'] for _, _, p in points}) == 88
    assert counts == {'Assume': 6, 'Comb': 15, 'Seq': 48, 'Cover': 19}
    assert len(guided) == 151 and len(evidence) == 1163
    assert (audit['FG'], audit['FC'], audit['CK']) == (12, 48, 88)
    assert audit['all_completed'] and audit['verification_status'] == 'inconclusive'
    assert audit['assumption_review_count'] == 6 and audit['bugs'] == []
    checker_path = REPORTS / 'guided/tests/sby_runs' / GUIDED_BMC / 'inputs/formal_out/tests/dmac_checker.sv'
    checker = checker_path.read_text(encoding='utf-8')
    for _, _, p in points:
        assert label(p) in guided and label(p) + ':' in checker
        if p['style'] in ('Comb', 'Seq'):
            assert 'G_' + label(p) in guided and 'G_' + label(p) + ':' in checker
    for run in read_json(REPORTS / 'guided-verified-evidence.json'):
        for name, digest in run['staged_input_sha256'].items():
            p = REPORTS / 'guided/tests/sby_runs' / run['run_id'] / 'inputs' / name
            assert hashlib.sha256(p.read_bytes()).hexdigest() == digest, p
    task = read_json(REPORTS / 'task.json')
    for name, digest in task['source_sha256'].items():
        assert hashlib.sha256((ROOT / 'dmac/rtl' / name).read_bytes()).hexdigest() == digest
    native = read_json(REPORTS / 'verified-evidence.json')
    assert sum(r['assertion_count'] for r in native if r['case'].startswith('accepted_prove')) == 236
    offline = read_json(ROOT / 'verification/offline-validation/cli-results.json')
    assert len(offline['runs']) == 18 and len(offline['replay']) == 19
    assert all(r['expected_observation'] for r in offline['runs'] + offline['replay'])
    return records, evidence, guided, points, native, task, offline


INTRO = '''# DMAC 详细验证文档

**验证方案、测试点、验证策略与实际验证报告**

文档版本：1.0；整理日期：2026 年 10 月 7 日（北京时间）。设计证据基线为 2026 年 10 月 5 日的 UCAgent 完整流程；离线重跑基线为 2026 年 10 月 7 日。本次整理没有新增形式证明或更改原始结果。

**当前结论：UCAgent 14 个启用阶段已完成，DMAC 主任务设计验证仍为未决。** 主任务 63 条安全断言在深度 12 内无反例，尚未获无界证明；四组 native 辅助参数实例安全证明通过。两类结果各有独立属性、输入与运行身份，不能互相替代。

## 1. 文档用途与阅读顺序

本文供设计人员、验证人员和验收人员共同使用：第 2–4 章定义设计、验证目标和参考模型；第 5–7 章说明环境约束、验证策略和测试点；第 8 章提供时序示例；第 9–12 章给出实际报告、故障对照、完备性评价和重跑方法；附录完整保留 88 个 CK 的表达式与默认 native 工程的逐属性结果。

所有“已证明”“命中”“失败”“未决”来自保存的机器证据。后续建议与当前已执行工作分开说明。表中 `FG` 是功能分组，`FC` 是功能点，`CK` 是检测点，`NCK` 是辅助工程的规划义务标识。NCK 需要追溯到真实编译属性和 run，不能单独当作证明结果。

## 2. DUT 规格与接口

### 2.1 功能与参数

DMAC 是单时钟、双向独立的数据搬运控制器。host 读命令驱动 `mem → DMAC → device`；host 写命令驱动 `device → DMAC → mem`。内存数据宽度为 64 bit，device 数据宽度为 16 bit，每个内存字对应四个 device 握手。

| 参数 | 默认值 | 合法域与本轮验证边界 |
| --- | --- | --- |
| `ADDR_W` | 32 | RTL 仿真检查要求至少 4；主任务为 32，native 实测 16 和 32 |
| `LEN_W` | 32 | 至少 1；主任务为 32，native 实测 1、8、32 |
| `FIFO_DEPTH` | 2 | 正整数；具体实例验证 1、2、3、4，未作全部正整数参数量化 |
| FIFO `WIDTH` | 64 | DMAC 两个 FIFO 均为 64 bit；其他位宽不在本轮验收范围 |

host 读写通道分别有一个 `haddr` 字段，只在对应命令接受沿锁存。mem 读写通道各自输出地址，device 口仅有 req、ack、data，没有地址信号。当前接口没有 busy、status、dev_fixed、byte enable 或独立内存读响应通道。

### 2.2 完整接口列表

方向以 DMAC 为参照；下面列出全部 26 个端口，位宽采用默认参数。输入请求由外部产生，输出确认由 DMAC 产生。

'''


SPEC = '''### 2.3 握手、地址、长度和数据顺序

全部协议在 `posedge clk` 采样。定义六类事件：

```text
Hrd = host_rd_req && host_rd_ack    // 接受读命令
Hwr = host_wr_req && host_wr_ack    // 接受写命令
Mrd = mem_rd_valid && mem_rd_ready  // 接收一个 64 位内存字
Mwr = mem_wr_valid && mem_wr_ready  // 提交一个 64 位内存字
Drd = dev_rd_req && dev_rd_ack      // device 接收一个 16 位片段
Dwr = dev_wr_req && dev_wr_ack      // device 发送一个 16 位片段
```

`mem_rd_ready` 表示本沿地址可接受且读数据已就绪，DMAC 在 `Mrd` 的同一个沿采样 `mem_rd_data`。没有另一个返回 valid，也不添加固定响应延迟。

对每条接受的命令，令 `L` 为接受沿的 len，`A0` 为接受沿的 haddr：

```text
Nmem = zero_extend(L) + 1
Ndev = 4 * Nmem
mem_addr(k) = (A0 + 8*k) mod 2**ADDR_W
```

`len=0` 表示 1 拍内存、4 拍 device；`len=1` 表示 2 拍内存、8 拍 device。默认 `len=32'hFFFF_FFFF` 表示 2^32 拍内存、2^34 拍 device；数学值由扩展计数表达，不能在 32 位中先加一。长度不是字节数，也不存在奇数字节末拍。

地址不要求 8 字节对齐。例如 `haddr=0x1007,len=1`，两个 mem 握手地址是 `0x1007` 与 `0x100F`。非对齐访问由 mem 端提供支持；DMAC 不拆分成额外内存拍。地址仅在实际 mem 握手后加 8，等待时不推进。

读方向每个字依次交付 `[15:0]`、`[31:16]`、`[47:32]`、`[63:48]`。写方向接收的四个片段 `d0,d1,d2,d3` 拼成 `{d3,d2,d1,d0}`，第四拍必须包含本沿输入数据，不能拼入前拍旧值。

### 2.4 命令与完成边界

每个方向最多执行一条命令；另一方向可以独立执行。等待命令由 host 保持 req、haddr 和 len，DUT 不提供 host 命令队列。读写数据 FIFO 不等于 host 命令 FIFO。

读 done 对应最后一个 device 片段握手，写 done 对应最后一个 mem 字握手。最后目标握手沿更新完成寄存器，随后一个完整周期 done 为高；下一个采样沿可观察到该高值。done 只持续一个周期，done 为高的周期不接受同方向下一命令；之后空闲周期可接受 pending 请求。

### 2.5 实现结构与检查风险

```mermaid
flowchart LR
  MR["mem 读握手 · 64 bit"] --> RF["读 FIFO"]
  RF --> SPL["2 位 lane · 64→16"]
  SPL --> DR["device 读握手 · 16 bit"]
  DW["device 写握手 · 16 bit"] --> PACK["四片段拼接 · 16→64"]
  PACK --> WF["写 FIFO"]
  WF --> MW["mem 写握手 · 64 bit"]
  HR["host 读命令 · 地址/配额"] -.-> RF
  HR -.-> SPL
  HW["host 写命令 · 地址/配额"] -.-> PACK
  HW -.-> WF
```

读方向按 mem 握手预取整字，按 device 握手推进 lane，第 4 个 lane 才出队。写方向前三个片段可先保存在拼接寄存器；第 4 个片段需要 FIFO 空间，形成完整字后入队。FIFO 空时没有同拍输入直通，满时出队可同拍接收新字；非二次幂深度采用显式指针末端回绕。

主要风险是长度加一溢出、握手与推进条件错配、片段顺序错误、满队列同拍替换错误、目标端未完成就 done，以及复位后旧片段或队首残留。这些风险分别由配额 oracle、数据参考队列、FIFO 不变量、done oracle 和复位场景检查承担。

## 3. 验证方案与范围

### 3.1 验证目标和验收层次

本轮验证包含控制安全性、端到端数据一致性、缓冲顺序、边界时序、复位中断、双向并发和场景可达性。需求 R01–R14 是规格到 FG/FC/CK 的追踪入口。

验收分三层：流程完成要求各启用阶段有记录并通过工具门禁；设计证明要求目标断言有当前输入下的 proven 证据；环境交付要求新设备能复现预期结果。三层分别报告，离线包可运行不代表所有设计要求已证明。

### 3.2 主任务与辅助工程的职责

| 项目 | Guided 主任务 | Native 辅助工程 |
| --- | --- | --- |
| 观察范围 | 只观察顶层端口，由 checker/wrapper 连接 DUT | 在独立副本中增加 FORMAL 观察与 oracle，检查内部状态和 FIFO |
| 主要责任 | 接口合法性、背压保持、固定历史窗口、复位可见行为、业务场景 | 任意长度的扩展计数、完整数据队列、所有有效 FIFO 槽位顺序、任意积压 |
| 当前参数 | `32/32/2` | `32/32/2`、`32/8/1`、`16/8/3`、`32/1/4` |
| 当前安全结果 | 63 条 depth-12 BMC 无反例，仍未决 | 四组 prove 通过，共 236 条断言实例 |
| 约束 | 初始复位与等待协议共 6 条 Assume | harness 只有初始复位 Assume；不约束请求保持、数据或 ready |
| 结果关联 | R→FG→FC→CK→A/M/C/G 属性→当前 run | NCK 义务→实际编译属性及实例→具体参数/run |

native 输入允许比 guided 更广的请求变化，独立参考模型按真实握手记录事务。但由于属性合同和 harness 不同，其通过结果不能覆盖主任务 63 条断言的未决状态。联合证明实际超时，此结论也必须单独保留。

### 3.3 纳入和排除范围

纳入：单时钟数字 RTL 语义、全部接口、len 全位模式、任意字节首地址及自然回绕、64/16 数据转换、任意时长背压、FIFO 合法状态、命令边界、初始及运行中复位、并发和三条命令可达性。

未验收：模拟毛刺、复位恢复/移除时序、CDC、综合 RAM 实际读写模式、物理时序收敛、地址混叠内存一致性、多时钟设计、全部参数组合量化、完整空洞性、COI 和无界活性。FormalMC、VCS 的真实编译及运行未完成。没有公平性前提时不要求永久背压的事务最终完成。

## 4. 参考模型与关键证明义务

### 4.1 独立计数与命令身份

参考模型在命令接受沿锁存地址和 `N`，按外部实际握手累计 mem/device 次数。它不直接复制 DUT 的剩余计数更新作为唯一判据。对读方向累计值 `Rm,Rd` 和写方向累计值 `Wm,Wd`，检查：

```text
rd_fetch_left   = N - Rm
rd_deliver_left = N - floor(Rd/4)
wr_collect_left = N - floor(Wd/4)
wr_commit_left  = N - Wm
0 <= Rm,Wm <= N
0 <= Rd,Wd <= 4*N
read_lane = Rd mod 4; write_lane = Wd mod 4
```

mem 总数与剩余配额使用 `LEN_W+1` 位，device 累计与上限使用 `LEN_W+3` 位；默认分别为 33 和 35 位。命令完成前后核对配额，不允许多采集、多提交或重复完成。只证明 safety 与完成时的因果，不由此推出环境不服务时仍一定完成。

### 4.2 数据队列与 FIFO 容量

读参考队列捕获每个 Mrd 的 64 位数据，Drd 时核对当前队首指定片段，第 4 次交付后才移除该字。写参考拼接寄存器捕获每个 Dwr，四片段成字后加入参考队列；Mwr 时逐字比对并出队。

读缓冲字数等于 `Rm-floor(Rd/4)`；写缓冲完整字数等于 `floor(Wd/4)-Wm`。FIFO oracle 使用移位队列表示顺序，与 DUT 环形指针实现不同：比较 count、ready/valid、队首和所有有效槽位。满时 push/pop 同拍 count 不变，空时不能因为同拍 push 就把旧 out_valid 改成有效；深度 1 的替换和深度 3 的回绕必须单独核对。

### 4.3 地址、done 与复位模型

地址 oracle 用锁存首地址加实际 mem 握手累计值的八倍计算，按 ADDR_W 截断。读 done oracle 由最后一个 Drd 产生，写 done oracle 由最后一个 Mwr 产生；同时核对完成时全部计数达到配额、接口不会继续传输和新命令接受边界。

复位清除 active、地址、配额、lane、拼接和 FIFO 有效状态；FIFO storage 不必逐槽清零，但无效旧值不能被新事务观察到。参考队列的存储内容同样只在 count 指示有效时参与比较。被中断命令不要求 done，复位后的新命令使用全新地址、长度和数据。

## 5. 环境约束、采样和历史有效性

### 5.1 Guided 的六条 Assume

下面是源工程的实际约束；未额外限制地址对齐、len 子集、数据内容、请求出现时间或背压持续周期。

'''


STRATEGY = '''### 5.2 复位策略和历史表达式

工程配置是 `reset_policy=unconstrained`，模板不自动施加复位序列。`M_CK_API_RESET_INITIAL` 显式要求首采样 `rst_n=0`；以后可任意再次拉低。unconstrained 配置与显式初态 Assume 并不矛盾，实际约束必须以 checker 为准。

一拍历史检查使用 `uc_past_valid`；引用更深 `$past(x,k)` 时，必须确认足够历史已建立，并对窗口内必要的复位样本逐项判断。不能引用完成时当前 host_len 代替接受沿锁存的 len。复位期间静默性质直接检查 rst_n 低时的输出，不能用统一 `disable iff` 把它们关闭。

当前 `Comb` 属性在 `always @*` 中检查；`Seq`、Assume 和相应时序 Cover 在 `posedge clk` 中检查。安全性为 `if (guard) assert(body)`，环境为 `if (guard) assume(body)`，业务 Cover 为 `cover(guard && body)`，guard witness 为独立 `cover(guard && trigger)`。时钟和组合语义不能互换。字段 `sva_body` 在当前 SBY 流程中保存的是 Yosys 可接受的过程式检查表达式，并不表示完整并发 SVA 已通过 VCS 编译。

### 5.3 约束审查原则

所有 Assume 需有协议依据并绑定输入哈希。ready 和数据在握手前后不必被人为固定；mem 读只在 valid&&ready 的采样沿使用数据。device 写请求未获确认时，guided 协议要求数据保持；native harness 不施加该约束，仍只在握手沿采集。

原生安全证明不添加“环境必须最终响应”的公平性 Assume。`A_CK_RD_PROGRESS`、`A_CK_WR_PROGRESS` 检查 active 且本拍 ready/req 同时满足时至少一侧握手的局部前进；它们不是无界最终完成证明。

## 6. 验证策略和执行流程

### 6.1 工具与编译输入

实际使用 SBY、Yosys、yosys-smtbmc/Z3；动态回放使用 Icarus/vvp。当前离线重跑版本为 SBY `v0.67-4-gfea6e46`、Yosys `0.67+94`、Z3 `4.15.5`、Icarus 14.0 开发版，完整版本和来源见 [离线运行清单](../verification/offline-validation/bundle.json)。

主任务源顺序为 `dmac_fifo.sv` 再 `dmac.sv`，宏 `SYNTHESIS` 排除仿真 assert...else/$fatal 和参数诊断；合法参数与端口展开另行审查。当前文件列表、include 搜索目录为空，没有内存初始化文件。native 工程在独立输入中加入 FORMAL monitor；原始 RTL 不修改。SBY 脚本内的 `async2sync` 等前端处理用于数字采样模型，不将结果扩大到模拟复位时序。

### 6.2 安全证明、BMC 与 Cover 的顺序

1. 先固定规格、参数、源文件、宏、checker/wrapper 和输入哈希，完成接口及 Assume 审查。
2. 尝试 prove；若实际超时，保留 timeout/未决记录，再以同属性合同进行 BMC，不将无反例当作 proven。
3. 独立运行 Cover：业务场景与安全断言 guard witness 分开统计。Cover 命中只说明存在路径，不说明所有路径正确。
4. 原生辅助环境通过计数、数据和 FIFO 不变量进行归纳，参数实例分别执行。prove 配置中的 depth 是求解/归纳展开设置；prove 通过不能误读成只有该深度的 BMC 结论。
5. 对 FAIL 检查真实 Assert failed、轨迹与输入身份；对 ERROR、缺失结果、超时分别报告，不能计为 RTL 反例。
6. 反例和业务轨迹执行动态编译及回放，核对输出症状；静态线索必须有源码位置和证据边界。

### 6.3 UCAgent 14 阶段与产物

'''


POINTS_INTRO = '''## 7. 测试点分解与检查矩阵

主任务完整分解为 **12 FG、48 FC、88 CK**，其中 6 Assume、15 Comb、48 Seq、19 Cover。63 条安全断言各增加一个 guard witness，因此生成的属性记录为 `6 + 63 + 19 + 63 = 151`。Cover 目标总数为 82，其中业务 Cover 为 19，guard witness 为 63。

证据 CSV 共 1,163 行，包含不同参数、模式、重复属性实例和故障修改版，不能把行数当作 1,163 个独立测试点，也不能把 prove 模式中 disabled 的 Cover 计为命中。

### 7.1 FG/FC/CK 数量与责任

'''


WAVES = '''## 8. 读写及连续 burst 时序示例

以下为依据当前 RTL 推导的**预期时序示意**，不是新采集的仿真或形式化波形。实际 VCD 和回放日志见第 10 章。表中 Ck 表示该上升沿之前的信号及该沿采样的握手；最后目标握手在 C9 时更新 done，C10 采样可观察 done=1。示例开始前已完成复位，FIFO_DEPTH=2，ready/req 在需要服务时为高。

### 8.1 非对齐、两拍 mem 的读 burst

`haddr=0x1007,len=1`，内存字 W0=`64'h7788_5566_3344_1122`，W1=`64'hF0F0_E0E0_D0D0_C0C0`。

| 采样沿 | host | mem 读握手 | device 读握手 | done / 下一命令 |
| --- | --- | --- | --- | --- |
| C0 | req&&ack 接受 len=1 | 无 | 无 | done=0 |
| C1 | 当前事务活动 | addr=0x1007，W0 | 无，空 FIFO 无同拍直通 | done=0 |
| C2 | 活动 | addr=0x100F，W1 | 0x1122（W0 lane0） | done=0 |
| C3 | 活动 | 无，读配额用完 | 0x3344 | done=0 |
| C4 | 活动 | 无 | 0x5566 | done=0 |
| C5 | 活动 | 无 | 0x7788，W0 出队 | 首字交付不能 done |
| C6–C8 | 活动 | 无 | 依次 0xC0C0、0xD0D0、0xE0E0 | done=0 |
| C9 | 活动至本沿 | 无 | 0xF0F0，最终片段握手 | 沿后置 done |
| C10 | pending req 可保持 | 无 | 无 | done=1，ack=0 |
| C11 | pending req&&ack | 新命令尚未传数据 | 无 | done=0，接受新命令 |

总量为 2 个 Mrd 和 8 个 Drd，done 与最后 Drd 关联，与 C2 的最后 Mrd 不关联。

### 8.2 非对齐、两拍 mem 的写 burst

同样使用 `haddr=0x1007,len=1`，device 先后发送上表的八个片段。

| 采样沿 | device 写握手 | mem 写握手 | 完成观察 |
| --- | --- | --- | --- |
| C0 | 无，host req&&ack 接受命令 | 无 | done=0 |
| C1–C3 | 0x1122、0x3344、0x5566 | 无 | 仅部分字，不能提交 |
| C4 | 0x7788，第 4 片段，W0 入队 | 无，空队列无同拍直通 | done=0 |
| C5 | 0xC0C0，第二字第 1 片段 | addr=0x1007，W0 | 首字提交不能 done |
| C6–C7 | 0xD0D0、0xE0E0 | 无 | done=0 |
| C8 | 0xF0F0，第 8 片段，W1 入队 | 无 | device 配额用完 |
| C9 | 无 | addr=0x100F，W1 | 最终 mem 握手后置 done |
| C10 | 无 | 无 | done=1，同方向 host ack=0 |
| C11 | 下一命令可接受 | 新命令尚未提交 | done=0 |

总量为 8 个 Dwr 和 2 个 Mwr，done 与最后 Mwr 关联，不能在 C8 接完 device 数据就提前完成。

### 8.3 连续三条 len=0 命令

本示例每条命令包含 1 个 mem 字和 4 个 device 片段。读、写为独立的两种示例，均假设环境连续服务；这只是展示可达路径，不是给所有输入增加持续服务约束。

| 命令 | host 接受 | 读方向：Mrd / 四个 Drd | 写方向：四个 Dwr / Mwr | done 高值观察 | 下一命令最早接受 |
| --- | --- | --- | --- | --- | --- |
| 第 1 条 | C0 | C1 / C2–C5 | C1–C4 / C5 | C6 | C7 |
| 第 2 条 | C7 | C8 / C9–C12 | C8–C11 / C12 | C13 | C14 |
| 第 3 条 | C14 | C15 / C16–C19 | C15–C18 / C19 | C20 | C21 |

这解释了当前固定 21 拍历史窗口的三命令 Cover 不能由 depth-12 结果闭合。native Cover 使用自己的计数型目标并在 depth 24 运行，两个结果应分开报告。

### 8.4 背压、满替换与中途复位

mem valid 高且 ready 低时，地址、valid 和写数据需要跨采样沿保持；没有握手就不更新 mem 地址和 mem 计数。device req 等待 ack 的保持由协议 Assume 表达。读 FIFO 满且第四 lane 正被 device 接收时，可以同拍接收新 mem 字；写 FIFO 满且本拍 mem 接收旧字时，可以同拍接收第四片段形成新字。

如果 rst_n 在以上任一部分进度拉低，接口确认/有效被关闭，活动命令与缓冲有效状态被清除。不要等待被取消命令的 done；复位解除后的新命令应从新 haddr 和 lane0 起步。该时序说明限数字 RTL 行为，亚周期复位毛刺没有本轮验证证据。

## 9. 实际验证报告

### 9.1 汇总结论

'''


LIMITS = '''## 11. 验证完备性评价与未闭合项

### 11.1 已有充分证据的部分

需求已落到 12 FG、48 FC、88 CK，接口、握手、地址、长度、数据、缓冲、复位和并发都有检查责任。默认 native 实例含自由 32 位 len 的扩展计数不变量，以及任意数据和背压下的完整参考队列；深度 1/3/4 的实际参数证明补充了 FIFO 边界。故障对照显示 oracle 对七类具体突变敏感；反例有真实动态执行；已有项目断网搬迁可复现预期结果。

### 11.2 仍不足以宣布整体验证通过的部分

| 缺口 | 当前证据边界 | 后续闭合条件 |
| --- | --- | --- |
| 主任务无界证明 | 63 条断言仅 BMC 深度 12，无界和联合 prove 均超时 | 划分属性、建立经独立证明的辅助不变量，保留同一合同或明确新版本，并获得逐属性 proven |
| 7 个 Cover/guard 未命中 | 深度不足或触发需要检查，没有不可达证明 | 不更改目标含义和协议约束，增加深度并分析轨迹；固定三命令窗口至少超过当前 12 拍预算 |
| 完整空洞性 | 61/63 guard 命中只证明部分触发可达 | 审查约束可满足性、断言 trigger/body 与 reset/history；采用完整工具支持，不把 witness 当作 vacuity 结论 |
| COI | 当前引擎不支持 | 使用可提供影响范围证据的工具或独立分析，单独报告 |
| 全部参数量化 | 只执行四组 DMAC prove 和列出的 Cover 参数实例 | 为合法域建立参数化证明，或按产品配置扩展实际运行矩阵；不能由抽样推全域 |
| 无界活性 | 只有条件满足本拍的局部 progress，没有最终完成证明 | 与规格确认服务公平性后建立单独活性义务，保留原 safety 假设；永久背压仍允许不完成 |
| 最大默认 len 的完整轨迹 | 33/35 位不变量可表达全域，但未动态执行 2^32/2^34 拍 | 说明数学安全证明与有限回放的不同范围；不得声称有限仿真穷举最大长度 |
| 模拟/物理复位 | 数字采样 RTL 模型和若干轨迹 | 单独做复位同步释放、恢复/移除和实现级检查，不从本轮 Cover 推出电气时序正确 |
| 商用工具交叉验收 | FormalMC/VCS 未实测 | 用固定输入在目标机编译、求解、回放并保存版本/日志/逐属性结果；新工具结果从尚未运行开始 |
| 内存一致性及实现 | mem 是同沿 ready/data 协议，数据由环境自由提供 | 如产品要求地址别名、读后写一致性或真实 RAM 模式，另建系统环境和实现级验收 |

后续建议的优先级：先使主任务安全性质获得逐属性证明并闭合七个目标；再完成空洞性与目标工具交叉检查；按产品需要扩展参数域、活性和实现级检查。这些是待执行事项，本次文档整理不把它们标为完成。

### 11.3 当前缺陷状态

原始设计 `bugs=[]`，当前没有已确认 RTL 缺陷；静态审查逐项核对计数扩展、地址更新、lane/拼接、done、FIFO、复位和双通道，详见 [静态审查报告](../verification/reports/guided/04_dmac_static_bug_analysis.md)。无已确认缺陷不表示设计不存在任何缺陷，主任务未决项和能力限制仍保留。

曾处理的环境/工具问题包括：前端不能直接处理仿真参数检查语法，通过明确 SYNTHESIS 宏重新编译；旧会话检查点缓存不能恢复，修复后在新恢复会话重执行门禁；离线搬入含空格路径后 Icarus 内部辅助程序启动失败，改用临时私有无空格别名并重新验收。它们不是原始 DMAC RTL 缺陷，历史失败记录未被删除。

## 12. 重跑、证据保存与验收标准

### 12.1 完整离线版运行

Linux x86_64 下载 [完整离线发行包](https://github.com/ysyx-22040210-yudian/UCAgent-DMAC-verification/releases/tag/v2026.10.07-offline)，目标机无需另装 Python、SBY 或求解器；已有验证项目执行不调用模型。新规格和属性的模型生成仍需用户配置模型服务。

```sh
sha256sum -c UCAgent-DMAC-20261007-linux-x86_64.tar.gz.sha256
tar -xzf UCAgent-DMAC-20261007-linux-x86_64.tar.gz
cd UCAgent-DMAC-20261007-linux-x86_64
./Check-Package
./Start-UCAgent                   # 有桌面显示环境
./Run-DMAC --suite smoke          # 一组证明、一项突变、19 次回放
./Run-DMAC --suite all            # 18 个 SBY 任务、19 次回放
```

`native` 运行 16 个辅助任务，`guided` 运行主任务 BMC/Cover，`replay` 运行 19 次回放。使用 `--output-root /路径` 可指定结果目录；每次建立独立子目录，保存命令、日志和 results.json。桌面首次导入 DMAC-native、DMAC-main 和两个 Counter 项目，新结果不继承旧审批或通过状态。服务需 10 GiB 可用磁盘门槛，解压约 2.8 GiB；GUI 需要显示环境，纯 SSH 可用命令行。

### 12.2 每次重跑的证据要求

保存 RTL、checker/wrapper、参数、源顺序、宏、约束和工具版本；记录输入哈希、run ID、命令及退出码；保存逐属性结果、未命中项和反例/VCD；动态回放同时保留编译及执行日志。签名密钥不发布，当前仓库中的证据身份依赖各级文件清单和原执行端已记录的核验。

缺少结果、编译错误、许可证错误或超时不能显示为通过。运行入口返回 0 只说明所选 suite 观察到预期证据：故障对照 FAIL 和原版反例不匹配也是预期；必须继续查看设计整体未决状态。

### 12.3 宣布“完整设计验收通过”所需条件

目标规格和合法参数范围冻结；所有必须的安全性质有当前合同下的证明，或由批准的等价验证策略完整覆盖；业务目标命中或有经审查的不可达证明；Assume、复位、历史和空洞性完成审查；真实缺陷关闭并回归；所有未决项明确处理；环境迁移与目标工具有实际证据。目前尚不满足这些完整验收条件。

## 13. 证据索引与输入身份

'''


def build():
    records, evidence, guided, points, native, task, offline = load_inputs()
    chunks = [INTRO]
    ports = records['basic_info']['ports']
    chunks.append(table(['接口', '端口', '方向', '位宽', '含义'],
                        [[('时钟/复位' if p['name'] in ('clk', 'rst_n') else p['name'].split('_')[0]),
                          '`' + p['name'] + '`', direction, p['width'], p['desc']]
                         for key, direction in [('inputs', '输入'), ('outputs', '输出')] for p in ports[key]]))
    requirements = '### 3.4 R01–R14 需求分配\n\n' + table(
        ['需求', '规格要求', 'Guided 责任', 'Native 责任'],
        [[r['id'], r['requirement'], r['guided_responsibility'], r['native_responsibility']]
         for r in records['planning']['requirements']])
    chunks.append(SPEC.replace('## 4. 参考模型与关键证明义务',
                               requirements + '## 4. 参考模型与关键证明义务'))
    chunks.append(table(['属性身份', '生效条件', '约束内容'],
                        [['`' + label(p) + '`', '`' + p['sby_guard'] + '`', '`' + p['sva_body'] + '`']
                         for _, _, p in points if p['style'] == 'Assume']))
    chunks.append(STRATEGY)
    stage_names = ['需求分析与验证规划', '设计功能理解与接口分析', '功能分组', '功能点分解', '检测点设计',
                   '功能规格汇总', '属性生成与审查', '验证脚本生成与执行', '环境调试与约束审查', '覆盖分析与缺口审查',
                   '反例测试分支', '验证结果与缺陷报告', '静态源码审查与证据关联', '验收审查与验证总结']
    artifacts = ['01 规划与 R01–R14', '02 接口、时钟和复位', '03 中 12 FG', '03 中 48 FC', '03 中 88 CK',
                 '.formal_records.yaml 规格记录', 'checker/wrapper 与逐属性复核', '实际 SBY 日志与 manifest',
                 '07 环境分析、6 条 Assume 审查', '75/82 覆盖结果及 7 个未命中分析',
                 '主任务无 RTL_BUG 分支；独立 native 突变与回放', 'bugs=[] 与分类结果', '04 静态审查',
                 '05 总结、final-state-audit.json']
    chunks.append(table(['阶段', '内容', '实际产物', '状态'],
                        [[i + 1, name, artifacts[i], '已完成'] for i, name in enumerate(stage_names)]))
    chunks.append('以上完成状态由原生门禁与最终审计记录提供。内置 Agent 承担规划、分解、前 12 个 CK 实现及多次门禁；工程师补充其余 76 个候选、native 环境及部分审查。因上下文和缓存问题使用新恢复会话重执行，不能表述为全程无人接续的自主验证。\n\n')
    chunks.append('### 6.4 实际执行矩阵\n\n')
    matrix = []
    for r in native:
        o = options(REPORTS / 'evidence' / r['case'] / 'control/run.sby')
        state = '预期反例' if r['case'].startswith('fault_') else ('超时/未决' if 'joint_' in r['case'] else '通过')
        matrix.append([r['case'], '/'.join(map(str, r['parameters'])), r['mode'], o.get('depth', '—'), o.get('timeout', '—'), state])
    for mode in ('bmc', 'cover', 'prove'):
        o = options(REPORTS / 'guided/tests' / (mode + '.sby'))
        matrix.append(['guided_' + mode, '32/32/2', mode, o['depth'], o['timeout'],
                       '无反例/未决' if mode == 'bmc' else ('75/82 命中/未决' if mode == 'cover' else '超时/未决')])
    chunks.append(table(['案例', 'ADDR_W/LEN_W/FIFO_DEPTH', '模式', '展开深度', 'SBY 超时秒', '实际结果'], matrix))
    chunks.append('矩阵包含历史证明尝试；离线 `all` 仅重跑 16 个 native 任务与 guided BMC/Cover，共 18 个，不默认重复已知超时的 prove/联合 prove。进程级 runner 默认超时为 300 秒，与 SBY 配置的内部超时分别记录。\n\n')
    chunks.append(POINTS_INTRO)
    chunks.append(table(['FG', '功能分组', 'FC', 'CK', '类型分布'],
                        [[g['id'], g['name'], len(g['functions']), sum(len(f['check_points']) for f in g['functions']),
                          '；'.join(STYLES[k] + ' ' + str(v) for k, v in collections.Counter(
                              p['style'] for f in g['functions'] for p in f['check_points']).items())]
                         for g in records['spec']['function_groups']]))
    chunks.append('### 7.2 88 个检测点总表\n\n每一行对应唯一主任务 CK；点击编号可查看附录中的完整描述、guard/body/trigger 和证据路径。组合/时序安全结果列使用 BMC 状态，guard 列使用独立 Cover 结果；两列不能混为“已通过”。另附 [88 CK 独立清单](DMAC检测点清单.csv)，便于在表格软件中查看完整表达式和当前结果。\n\n')
    compact = []
    for g, f, p in points:
        r = guided[label(p)]
        witness = guided.get('G_' + label(p))
        req = '、'.join(dict.fromkeys(re.findall(r'R\d{2}', p['description'])))
        compact.append(['[' + p['id'] + '](#' + p['id'].lower() + ')', req, g['id'], f['id'], STYLES[p['style']],
                        r['实际结论'], witness['实际结论'] if witness else '不适用'])
    chunks.append(table(['CK 检测点', '需求', 'FG', 'FC', '类别', '当前结果', 'guard witness'], compact))
    chunks.append('### 7.3 Native 的九项规划义务\n\n')
    chunks.append(table(['NCK', '义务', '规划参数'],
                        [[r['planned_id'], r['obligation'], r['parameters']] for r in records['planning']['native_ck_obligations']]))
    chunks.append('NCK 名称不是新增检查端口；默认实际 58 Assert/17 Cover 的编译身份与结果见附录 B，所有参数/run 对应见第 9 章及原始证据表。\n\n')
    chunks.append(WAVES)
    chunks.append(table(['项目', '实际结果', '解释'], [
        ['流程门禁', '14/14 已完成', '流程状态与设计结论分别保存'],
        ['主任务安全断言', '63 条 BMC 深度 12 无反例，0 条获无界证明', '63 条均 inconclusive'],
        ['guard witness', '61/63 命中（96.83%）', '仅触发可达，不是完整空洞性'],
        ['业务 Cover', '14/19 命中（73.68%）', '场景覆盖，不是 RTL 代码覆盖率'],
        ['全部 Cover 目标', '75/82 命中（91.46%）', '包含业务目标与 guard，不能替代安全证明'],
        ['主任务/联合 prove', '两类实际尝试均 240 秒超时', '无逐属性 proven 结论'],
        ['native 安全', '四组参数，共 236 断言实例获证', '默认实例 58；不是 236 个唯一 CK 或全参数证明'],
        ['native Cover', '两组 DMAC 共 34、三组 FIFO 共 9 个目标命中', '43 个目标实例各有轨迹'],
        ['故障对照', '7/7 检出预期反例', '修改版 FAIL，不是原始 DUT Bug'],
        ['回放', '19/19 符合预期', '7 mutant 匹配、7 baseline 不匹配、5 业务匹配'],
        ['历史工具回归', '66 项通过，0 失败、0 跳过', '工具回归不是新增设计断言'],
        ['离线版相关回归', '19 项通过', '与历史 66 项范围可能重叠，不合并为独立总数'],
        ['原始 RTL', '未修改，当前 0 个已确认缺陷', '未决保留，不能推导完全无缺陷'],
        ['FormalMC / VCS', '尚未实测', '不继承 SBY 通过结论']]))
    chunks.append('### 9.2 Guided 当前运行与未命中列表\n\n')
    chunks.append(table(['运行', '模式', '结果', '证据'], [
        [GUIDED_BMC, 'bmc depth 12', '63 inconclusive，82 Cover disabled', '[manifest](../verification/reports/guided/tests/sby_runs/' + GUIDED_BMC + '/manifest.json)'],
        [GUIDED_COVER, 'cover depth 12', '75 covered、7 uncovered，63 Assert disabled', '[manifest](../verification/reports/guided/tests/sby_runs/' + GUIDED_COVER + '/manifest.json)']]))
    chunks.append(table(['属性', 'CK', '类别', '当前状态'],
                        [[r['属性编号'], r['检测点'], r['属性类别'], r['实际结论']]
                         for r in guided.values() if r['实际结论'] == '未命中']))
    chunks.append('这些未命中目标属于当前深度/触发审查缺口，没有不可达证明。主任务有 63 条安全未决和 7 个未命中目标，共 70 个分析项，均与当前输入绑定并保留 INCONCLUSIVE 分类。\n\n')
    chunks.append('### 9.3 Native 逐运行结果\n\n参数顺序为 ADDR_W、LEN_W、FIFO_DEPTH；断言/Cover 数是该次编译的数量。prove 不执行 Cover，cover 不证明 Assert。\n\n')
    native_runs = []
    for r in native:
        state = '预期反例（修改版）' if r['case'].startswith('fault_') else ('超时/未决' if 'joint_' in r['case'] else '通过')
        native_runs.append([r['case'], str(r['parameters']), r['mode'], r['assertion_count'], r['cover_count'], state,
                            '[' + r['run_id'] + '](../verification/reports/evidence/' + r['case'] + '/manifest.json)'])
    chunks.append(table(['案例', '参数', '模式', 'Assert', 'Cover', '结果', 'run / manifest'], native_runs))
    chunks.append('联合 prove 所存 0/0 统计表示未取得有效逐属性结果，并不表示联合工程没有验证义务。单独 default native 的 58 条 proven 不能填入 guided 的 63 条结果。\n\n')
    chunks.append('### 9.4 离线搬迁与再运行报告\n\n2026-10-07 在 CentOS 7 x86_64、UID 1004 普通用户、只有 loopback 的独立网络命名空间、含空格的新根目录运行。包内 40,929 项完整性检查匹配，四工程首次自动导入且旧 run 数为 0；实际 Tk 窗口显示项目列表，重启保留修改和新历史。Counter 正向证明通过，故障 Counter 显示失败；DMAC-native 默认 58 条证明通过，DMAC-main BMC 仍显示未决。\n\n')
    chunks.append(table(['本次实际重跑', '结果'],
                        [[r['case'], r['tool_status'] + '；' + r['conclusion']] for r in offline['runs']]))
    chunks.append('另完成 19 次实际 Icarus 回放，全部 compile_code=0 且达到各自预期结果。离线重跑是新执行证据，不替换原 UCAgent 会话的 run ID。详见 [离线验收报告](离线版验收.md) 和 [新执行 results.json](../verification/offline-validation/cli-results.json)。\n\n')
    chunks.append('## 10. 故障对照、反例与动态回放\n\n### 10.1 七类故障对照\n\n故意修改仅发生在独立输入副本，原始 RTL 保持不变。每个失败运行须有真实断言失败和 VCD，不能用编译 ERROR 代替检测成功。下表的失效属性来自实际逐属性证据，提前完成和长度编码可能同时触发多个不变量。\n\n')
    fault_names = {'fault_address_step': '地址步进错误', 'fault_early_done': '提前完成', 'fault_fifo_pop': '错误 FIFO 出队',
                   'fault_length_encoding': 'len 编码错误', 'fault_read_lane': '读片段顺序错误',
                   'fault_reset_lane': '复位后 lane 残留', 'fault_write_lane': '写拼接顺序错误'}
    fault_rows = []
    for case, name in fault_names.items():
        failed = [r for r in evidence if r['运行案例'] == case and r['实际结论'] == '已发现反例']
        assert failed
        fault_rows.append([case, name, '、'.join(r['属性编号'] for r in failed),
                           '[反例](../verification/reports/evidence/' + case + '/proof/engine_0/trace.vcd)',
                           'mutant 匹配；baseline 不匹配'])
    chunks.append(table(['案例', '故障类别', '实际失效属性', '轨迹', '对照回放'], fault_rows))
    chunks.append('### 10.2 全部 19 次回放\n\n同一反例输入在 mutant 上复现，在原始 RTL 上应出现预期 VECTOR_MISMATCH，说明该轨迹能区分修改版与原版。baseline 退出码 1 在这里是对照有效，不能解释为原始设计被证明有缺陷。业务回放匹配也只证明这条轨迹符合原始 RTL。\n\n')
    replay_rows = []
    for r in offline['replay']:
        history = next(x for x in read_json(REPORTS / 'replay/results.json') if x['case'] == r['case'])
        meaning = '原版区分对照：预期不匹配' if r['case'].endswith('_baseline') else ('修改版反例匹配' if r['case'].endswith('_mutant') else '原始业务轨迹匹配')
        replay_rows.append([r['case'], history.get('vectors', '—'), r['compile_code'], r['run_code'], r['expected_run_code'],
                            meaning, '[日志](../verification/offline-validation/runs/replay_' + r['case'] + '/run.log)'])
    chunks.append(table(['回放', '向量数', '编译码', '运行码', '预期运行码', '含义', '证据'], replay_rows))
    chunks.append('主任务当前没有 RTL_BUG，启用的主任务反例分支走“无确认缺陷”路径。以上七项反例是 native 辅助突变实验，不冒充主任务发现的七个 Bug。静态审查与原始缺陷报告分别保留。\n\n')
    chunks.append(LIMITS)
    chunks.append(table(['资料', '内容'], [
        ['[原完整流程报告](../verification/reports/DMAC_完整流程验证报告.md)', '历史 14 阶段与结论'],
        ['[需求规划](../verification/reports/guided/01_dmac_verification_needs_and_plan.md)', '范围、责任、需求与原生义务'],
        ['[原测试点文档](../verification/reports/guided/03_dmac_functions_and_checks.md)', '12 FG / 48 FC / 88 CK 的原始分解'],
        ['[需求追踪表](../verification/reports/guided/08_dmac_requirement_traceability.md)', 'R 到两类工程证据和边界'],
        ['[逐属性证据 CSV](../verification/reports/testpoint-evidence.csv)', '1,163 行跨模式/实例记录'],
        ['[原交互证据页面](../verification/reports/testpoints.html)', '按需求、CK、参数与结果筛选'],
        ['[机器规格记录](../verification/reports/guided/.formal_records.yaml)', '本详细文档的 CK 表达式来源'],
        ['[流程最终审计](../verification/reports/final-state-audit.json)', '14/14、当前输入审查与未决统计'],
        ['[Guided 输入核验](../verification/reports/guided-verified-evidence.json)', '当前两次运行的 staged 输入哈希'],
        ['[Native 输入核验](../verification/reports/verified-evidence.json)', '具体参数/run 与输入 fingerprint'],
        ['[联合证明记录](../verification/reports/joint-proof.json)', '超时身份与范围'],
        ['[原回放清单](../verification/reports/replay/results.json)', 'VCD 身份、实际编译/运行结果'],
        ['[离线重跑结果](../verification/offline-validation/cli-results.json)', '18 SBY / 19 回放的新执行'],
        ['[离线后端验收](../verification/offline-validation/acceptance.json)', '逐属性、断网/搬迁/桌面证据'],
        ['[历史工具回归](../verification/reports/tool-fix/regression.xml)', '66 项工具测试'],
        ['[离线版回归](../verification/offline-validation/regression.xml)', '19 项相关测试']]))
    review = records['extra_config']['sby']['review']['input_sha256']
    chunks.append('当前 guided 输入 SHA-256：`' + review + '`。恢复任务 ID：`' + task['session_id'] + '`；前序任务 ID：`' + task['predecessor_session_id'] + '`。\n\n')
    chunks.append(table(['原始文件', 'SHA-256'], [['dmac/rtl/' + k, '`' + v + '`'] for k, v in task['source_sha256'].items()]))
    chunks.append('## 附录 A. 全部 88 个 CK 的详细定义与实际表达式\n\n下述 FC、CK 描述及表达式从固定机器记录读取，原自动生成文档不被修改。每个检查按原类型保持组合或采样语义；状态来自 guided-current 合并证据。某些属性描述的责任较宽，其实际 guard/body 只覆盖固定局部窗口，不能据标题扩大已验证范围。\n\n')
    for gi, g in enumerate(records['spec']['function_groups'], 1):
        chunks.append('### A.' + str(gi) + ' ' + g['id'] + ' · ' + g['name'] + '\n\n' + g['description'] + '\n\n')
        for f in g['functions']:
            chunks.append('#### ' + f['id'] + '\n\n' + f['description'] + '\n\n')
            for p in f['check_points']:
                r = guided[label(p)]
                witness = guided.get('G_' + label(p))
                chunks.append('##### ' + p['id'] + '\n\n')
                chunks.append(p['description'] + '\n\n')
                chunks.append('类型：' + STYLES[p['style']] + '；属性：`' + label(p) + '`；当前结果：**' + r['实际结论'] + '**。')
                if witness:
                    chunks.append(' guard witness：`G_' + label(p) + '`，**' + witness['实际结论'] + '**。')
                chunks.append('\n\n```systemverilog\n// guard：生效条件\n' + p.get('sby_guard', "1'b1") +
                              '\n// body：检查或覆盖内容\n' + p['sva_body'] + '\n// trigger：guard witness 的触发探针\n' +
                              p.get('sby_trigger', "1'b1") + '\n```\n\n')
                run = GUIDED_COVER if p['style'] == 'Cover' else GUIDED_BMC
                if p['style'] == 'Assume':
                    chunks.append('环境假设不是已证明性质；六项审查绑定当前输入。')
                chunks.append(' [编译与运行身份](../verification/reports/guided/tests/sby_runs/' + run + '/manifest.json)。')
                if r['轨迹文件']:
                    chunks.append(' [该覆盖轨迹](../verification/reports/guided/tests/sby_runs/' + GUIDED_COVER + '/' + r['轨迹文件'] + ')。')
                if witness and witness['轨迹文件']:
                    chunks.append(' [guard 轨迹](../verification/reports/guided/tests/sby_runs/' + GUIDED_COVER + '/' + witness['轨迹文件'] + ')。')
                chunks.append('\n\n')
    chunks.append('## 附录 B. 默认 Native 实例的逐属性结果\n\n本表以 `accepted_prove_a32_l32_f2` 的实际 58 个安全编译实例和 `accepted_cover_a32_l32_f2` 的 17 个覆盖实例为准。FIFO 属性可在读/写两个实例中同名，使用“编译对象与位置”区分；匿名槽位顺序属性保留原编译身份。安全列来自 prove，覆盖列来自 cover，不把 disabled 状态隐藏后冒充一次运行全部通过。\n\n')
    selected = [r for r in evidence if (r['运行案例'] == 'accepted_prove_a32_l32_f2' and r['实际结论'] == '已证明') or
                (r['运行案例'] == 'accepted_cover_a32_l32_f2' and r['实际结论'] == '已命中')]
    assert len(selected) == 75
    chunks.append(table(['属性/CK 身份', '需求', '类别', '实际结果', '编译对象与位置', '轨迹/记录'],
                        [[r['属性编号'], '、'.join(json.loads(r['需求编号'])), r['属性类别'], r['实际结论'], r['编译属性名'],
                          ('[VCD](../verification/reports/evidence/' + r['运行案例'] + '/' + r['轨迹文件'] + ')' if r['轨迹文件'] else
                           '[manifest](../verification/reports/evidence/' + r['运行案例'] + '/manifest.json)')]
                         for r in selected]))
    document = ''.join(chunks)
    DOCS.mkdir(exist_ok=True)
    (DOCS / 'DMAC详细验证文档.md').write_bytes(document.encode('utf-8'))
    render_html(document)
    fields = ['需求编号', '功能分组', '功能分组名称', '功能点', '功能点说明', '检测点', '检测说明', '检查类型',
              '属性编号', '触发guard', '检查body', 'guard探针trigger', '当前主任务结果', 'guard属性编号',
              'guard结果', 'BMC运行编号', 'Cover运行编号', '参数', '输入SHA256']
    with (DOCS / 'DMAC检测点清单.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for g, f, p in points:
            r = guided[label(p)]
            witness = guided.get('G_' + label(p))
            values = ['、'.join(dict.fromkeys(re.findall(r'R\d{2}', p['description']))),
                      g['id'], g['name'], f['id'], f['description'], p['id'], p['description'], STYLES[p['style']],
                      label(p), p.get('sby_guard', "1'b1"), p['sva_body'], p.get('sby_trigger', "1'b1"),
                      r['实际结论'], 'G_' + label(p) if witness else '', witness['实际结论'] if witness else '不适用',
                      GUIDED_BMC, GUIDED_COVER, '32/32/2', review]
            writer.writerow(dict(zip(fields, values)))
    print('Built detailed DMAC documents: 26 ports, 14 requirements, 12 FG, 48 FC, 88 CK, 151 guided records, 75 native instances.')


def render_html(document):
    converter = markdown.Markdown(extensions=['tables', 'fenced_code', 'toc', 'sane_lists'],
                                  extension_configs={'toc': {'toc_depth': '2-2'}})
    body = converter.convert(document)
    pattern = r'<table>\s*<thead>\s*<tr>\s*<th>CK 检测点</th>'
    body, count = re.subn(pattern, '<table id="ck-matrix">\n<thead><tr><th>CK 检测点</th>', body)
    assert count == 1
    filters = '''<div class="filterbar"><label>检测点筛选 <input id="search" type="search" placeholder="输入 CK、FC、需求、类别或状态" /></label><label>类型 <select id="kind"><option value="">全部类型</option><option>环境假设</option><option>组合断言</option><option>时序断言</option><option>业务覆盖</option></select></label><label>结果 <select id="state"><option value="">全部结果</option><option>未决</option><option>已命中</option><option>未命中</option><option>环境假设</option></select></label><span id="count"></span></div>'''
    body = body.replace('<table id="ck-matrix">', filters + '<table id="ck-matrix">')
    # Mermaid is rendered as an inline SVG so this document works without a CDN.
    svg = '''<svg class="architecture" viewBox="0 0 920 220" role="img" aria-label="DMAC 双通道数据路径"><defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10z" fill="#245cd4"/></marker></defs><g fill="#eef4ff" stroke="#245cd4" stroke-width="1.5"><rect x="20" y="45" width="180" height="55" rx="8"/><rect x="250" y="45" width="180" height="55" rx="8"/><rect x="480" y="45" width="180" height="55" rx="8"/><rect x="710" y="45" width="180" height="55" rx="8"/><rect x="20" y="145" width="180" height="55" rx="8"/><rect x="250" y="145" width="180" height="55" rx="8"/><rect x="480" y="145" width="180" height="55" rx="8"/><rect x="710" y="145" width="180" height="55" rx="8"/></g><g stroke="#245cd4" stroke-width="2" marker-end="url(#arrow)"><path d="M200 72 H247 M430 72 H477 M660 72 H707"/><path d="M200 172 H247 M430 172 H477 M660 172 H707"/></g><g font-family="sans-serif" font-size="16" fill="#17335c" text-anchor="middle"><text x="460" y="23">host 读写命令分别控制地址、配额和完成，两个方向独立</text><text x="110" y="78">mem 读 · 64 bit</text><text x="340" y="78">读 FIFO</text><text x="570" y="78">lane 拆分 64→16</text><text x="800" y="78">device 读 · 16 bit</text><text x="110" y="178">device 写 · 16 bit</text><text x="340" y="178">四片段拼接 16→64</text><text x="570" y="178">写 FIFO</text><text x="800" y="178">mem 写 · 64 bit</text></g></svg>'''
    body = re.sub(r'<pre><code class="language-mermaid">.*?</code></pre>', svg, body, flags=re.S)
    page = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DMAC 详细验证文档</title><style>
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#f5f7fb;color:#243044;font:16px/1.75 system-ui,"Microsoft YaHei",sans-serif}.shell{display:grid;grid-template-columns:260px minmax(0,1fr);max-width:1680px;margin:auto}aside{position:sticky;top:0;height:100vh;overflow:auto;padding:22px 20px;background:#142039;color:#dde8ff}aside h2{font-size:20px;color:white;border:0;margin:0 0 12px;padding:0}aside a{color:#c5d8fa;text-decoration:none;display:block;font-size:13px;padding:5px 0}aside ul{list-style:none;padding-left:0}aside ul ul{display:none}main{background:white;padding:30px 38px;min-width:0}h1{font-size:32px;color:#112746}h2{margin-top:45px;padding-top:15px;border-top:1px solid #e1e7f2;color:#1e4378}h3{color:#245cd4}h4{color:#384967}h5{font-size:17px}p,li{overflow-wrap:anywhere}a{color:#225cce}table{border-collapse:collapse;width:100%;font-size:13px;display:block;overflow-x:auto;margin:15px 0 26px}td,th{border:1px solid #dbe3ee;padding:9px 11px;text-align:left;vertical-align:top}th{background:#edf3fd;white-space:nowrap}tbody tr:nth-child(even){background:#f9fbfe}code{font:13px/1.6 ui-monospace,Consolas,monospace;background:#eef2f8;border-radius:3px;padding:2px 4px}pre{background:#15213a;color:#e1ebfe;padding:16px;overflow-x:auto;border-radius:8px;max-height:390px}pre code{background:none;padding:0;color:inherit;white-space:pre-wrap;overflow-wrap:anywhere}blockquote{border-left:4px solid #4982e8;margin-left:0;padding:0 16px;color:#4d6180}.architecture{width:100%;min-width:480px;background:#fff;border:1px solid #dbe3ee;border-radius:8px}.filterbar{display:flex;flex-wrap:wrap;gap:12px;padding:16px;border:1px solid #dbe3ee;background:#f0f5ff;align-items:center}.filterbar label{font-size:13px}.filterbar input,.filterbar select{padding:8px;border:1px solid #bac9e2;border-radius:5px;background:white}button{cursor:pointer;border:1px solid #7898d2;border-radius:5px;background:#f4f7ff;padding:8px 16px}.pill{display:inline-block;padding:4px 10px;border-radius:20px;background:#fff3d7;color:#825600;font-size:13px}.ck-formula summary{cursor:pointer;color:#225cce;margin:8px 0}.print-only{display:none}@media(max-width:980px){.shell{display:block}aside{height:auto;position:static}aside .toc{display:none}main{padding:22px 16px}}@media print{body{background:white;font-size:11px}.shell{display:block}aside,.filterbar,.actions{display:none}main{padding:0}h2{break-before:page}table{display:table;font-size:9px}pre{max-height:none;background:#f2f4f8;color:#17233b;white-space:pre-wrap}pre code{color:inherit}thead{display:table-header-group}tr{break-inside:avoid}a{color:inherit;text-decoration:none}.architecture{min-width:0}.print-only{display:block}}
</style></head><body><div class="shell"><aside><h2>DMAC 验证档案</h2><p>方案 · 测试点 · 策略 · 报告</p><p><span class="pill">设计结论：未决</span></p><div class="actions"><button id="print">打印 / 另存 PDF</button></div>''' + converter.toc + '''</aside><main>''' + body + '''</main></div><script>
const rows=Array.from(document.querySelectorAll('#ck-matrix tbody tr'));const search=document.getElementById('search'),kind=document.getElementById('kind'),state=document.getElementById('state');function filter(){const q=search.value.trim().toLowerCase();let n=0;for(const row of rows){const c=row.cells;const keep=row.textContent.toLowerCase().includes(q)&&(!kind.value||c[4].textContent===kind.value)&&(!state.value||c[5].textContent===state.value);row.hidden=!keep;if(keep)n++}document.getElementById('count').textContent=`显示 ${n} / ${rows.length} 个 CK`}for(const x of [search,kind,state])x.addEventListener('input',filter);filter();document.getElementById('print').addEventListener('click',()=>window.print());for(const pre of document.querySelectorAll('pre')){if(pre.querySelector('code.language-systemverilog')){const d=document.createElement('details');d.className='ck-formula';const s=document.createElement('summary');s.textContent='展开完整 guard / body / trigger 表达式';pre.parentNode.insertBefore(d,pre);d.appendChild(s);d.appendChild(pre)}}let openBefore=[];window.addEventListener('beforeprint',()=>{openBefore=Array.from(document.querySelectorAll('details')).filter(x=>x.open);for(const d of document.querySelectorAll('details'))d.open=true});window.addEventListener('afterprint',()=>{for(const d of document.querySelectorAll('details'))d.open=openBefore.includes(d)});
</script></body></html>'''
    (DOCS / 'DMAC详细验证文档.html').write_bytes(page.encode('utf-8'))


if __name__ == '__main__':
    build()
