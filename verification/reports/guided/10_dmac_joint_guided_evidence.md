# 前序会话实际证明尝试（同属性合同）

旧会话保留，不继承其阶段或工具结论；恢复会话将重新执行BMC/Cover。以下prove/frontend历史来自前序会话e266f8230d2140f184854271dcf7d864。

# 主任务与联合证明尝试记录

实际超时不是证明通过，也不构成RTL缺陷。为继续完整审查流程，工程师以相同属性/Assume追加depth12的BMC及Cover，BMC无反例严格保留inconclusive。

| 尝试 | 实际结果 | 范围 |
| --- | --- | --- |
| formal_out/tests/sby_runs/sby-f016812672bd4dd68d9433d29d23c3d5/manifest.json | error / unknown | prove；{} |
| formal_out/tests/sby_runs/sby-022f841335c54e6598c65d53cdb36594/manifest.json | timeout / unknown | prove；{} |
| formal_out/tests/sby_runs/sby-63cc3dd686ff4d53904a78f6cf1f2944/manifest.json | completed / inconclusive | bmc；{'inconclusive': 63, 'disabled': 82} |
| formal_out/tests/sby_runs/sby-6fc5fc87846843d9aacb68f28d358cf4/manifest.json | completed / inconclusive | cover；{'disabled': 63, 'covered': 75, 'uncovered': 7} |

联合工程run ID：`6fe692e2e61d49f78a3caf1103bab687`，实际execution=timeout，verification=inconclusive。当时生成checker/wrapper哈希与当前相同：True。未产生逐属性结果，不得给63条主任务断言标proven。

联合工程原生不变式与主checker合并耗时达到240秒，单独native默认58条证明成功并不意味着此次合并也成功。全部结果分别保留。

首次frontend错误来自仿真参数检查assert...else，工程师明确宏SYNTHESIS排除仿真诊断并实际重新编译；合法默认参数及26个端口展开另核对。原始RTL不变。

后续必做环境版本/Assume审查、覆盖缺口逐项INCONCLUSIVE、启用反例分支的无RTL_BUG记录、实际静态源码审查和14节点总结，不能因为求解困难跳过这些阶段。
