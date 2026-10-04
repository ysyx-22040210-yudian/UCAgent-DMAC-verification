---
name: cex-gen
description: 指导为每个 RTL_BUG 编写并真实执行 Python 反例复现测试，保留失败断言及签名执行证据。
---

# 反例测试用例生成

## 概述

为 `{OUT}/tests/test_{DUT}_counterexample.py` 编写引脚级反例复现。每个 RTL_BUG 对应一个 `test_cex_*` 测试函数，测试必须运行真实 DUT 并断言设计规范。

执行说明：
- 本技能提供编写规则，不依赖不存在的生成脚本
- 使用 `ReadTextFile` 读取 `.formal_records.yaml`、形式化日志、wrapper 和 `Guide_Doc/counterexample.md`
- 使用 `EditTextFile` 或 `ReplaceStringInFile` 创建和完善测试文件

## 步骤

### 1. 建立属性到测试的精确映射

从 `.formal_records.yaml.analysis.fa_entries` 读取 `resolution: RTL_BUG` 的属性。属性 `A_CK_FOO` 对应函数 `test_cex_foo`；每个属性必须且只能映射到一个测试函数。

### 2. 填写测试逻辑

读取 `avis.log` 反例信息、RTL 和 wrapper，初始化真实 DUT，复现相同输入/状态序列，并用 `assert` 表达设计规范。当前有缺陷的 RTL 必须使这个规范断言失败；禁止 `assert False`、`Not implemented` 或任何占位符制造假复现。

### 3. 执行证据门禁

调用 `Check` 或 `Complete`。Checker 会执行每个精确 pytest 节点，区分预期规范断言失败与收集、依赖、fixture、超时等基础设施错误，并生成签名执行证据。仅函数存在或仅通过静态检查不能完成本阶段。

## 核心规则

1. 每个函数至少一个基于 DUT 观测值的规范断言，清理阶段调用 `dut.Finish()`
2. 正确暴露 RTL 缺陷的失败用例必须保留，不能弱化断言换取 Pass
3. 若无 RTL_BUG，创建说明无反例测试需求的文件即可
