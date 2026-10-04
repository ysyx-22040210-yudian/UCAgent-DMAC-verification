"""Counterexample replay status for the current guided DMAC run.

The current signed guided report contains no falsified assertion classified as
RTL_BUG. The 63 safety assertions are inconclusive after depth-12 BMC, and the
prove attempts timed out without per-property proof or counterexample results.
Therefore there is no current-signature VCD to drive against the original DUT,
and no test_cex_ck_* replay test is required for this branch.

The seven fault-injection counterexamples and the 19 Icarus executions recorded
in formal_out/06_dmac_native_evidence.md belong to a separate native auxiliary
project. Those faults modify the RTL and are not bugs in the original DUT, so
this guided test module intentionally does not reproduce or register them.
"""

# Intentionally no test_cex_ck_* functions: there is no confirmed guided
# RTL_BUG and hence no signed original-DUT counterexample to replay.
