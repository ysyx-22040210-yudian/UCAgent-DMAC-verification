"""Fixture-style tests for deterministic commercial EDA report parsers."""

from ucagent.eda import ExecutionStatus, FormalPropertyStatus, VerificationStatus
from ucagent.eda.parsers import parse_formal_log, parse_urg_output, parse_urg_report, parse_uvm_log


def test_uvm_summary_pass_and_assertion_failure_are_execution_complete() -> None:
    """Keep DUT/test failures separate from simulator infrastructure status."""

    passed = parse_uvm_log(
        "UVM Report Summary\nUVM_ERROR : 0\nUVM_FATAL : 0\n",
        return_code=0,
        test_name="uart_smoke",
        suite="UT",
        seed=7,
    )
    assert passed.execution_status == ExecutionStatus.COMPLETED
    assert passed.verification_status == VerificationStatus.PASSED
    assert passed.tests[0].seed == 7

    failed = parse_uvm_log(
        "Assertion p_valid failed at 20ns\nUVM Report Summary\nUVM_ERROR : 1\nUVM_FATAL : 0\n",
        return_code=1,
        test_name="uart_bad",
    )
    assert failed.execution_status == ExecutionStatus.COMPLETED
    assert failed.verification_status == VerificationStatus.FAILED
    assert failed.tests[0].error_count == 1
    assert failed.tests[0].assertion_failures == 1


def test_uvm_parser_requires_summary_or_signed_project_marker() -> None:
    """Do not infer pass merely from a zero process return code."""

    undecided = parse_uvm_log("simulation ended", return_code=0)
    assert undecided.verification_status == VerificationStatus.INCONCLUSIVE
    marked = parse_uvm_log("boot... GOOD_SIGNATURE", return_code=0, success_markers=["GOOD_SIGNATURE"])
    assert marked.verification_status == VerificationStatus.PASSED


def test_uvm_license_failure_is_not_a_verification_failure() -> None:
    """Classify license checkout problems as execution errors with unknown verification."""

    parsed = parse_uvm_log("FlexNet Licensing error: license checkout failed", return_code=1)
    assert parsed.execution_status == ExecutionStatus.ERROR
    assert parsed.verification_status == VerificationStatus.UNKNOWN
    assert parsed.diagnostics[0]["error_code"] == "license_unavailable"


def test_urg_parser_extracts_all_supported_metrics() -> None:
    """Parse text or lightly marked-up URG summaries into canonical metric names."""

    report = """
    <td>Line Coverage: 95.5% (191/200)</td>
    Condition Coverage 80% 8/10
    Toggle = 75.0% [3/4]
    FSM 100%
    Branch: 66.7%
    Assertion Coverage 50% 1/2
    """
    metrics = parse_urg_report(report)
    assert [metric.metric for metric in metrics] == ["line", "cond", "tgl", "fsm", "branch", "assert"]
    assert metrics[0].covered == 191
    wrapped = parse_urg_output(report, return_code=0)
    assert wrapped.execution_status == ExecutionStatus.COMPLETED
    assert wrapped.verification_status == VerificationStatus.PASSED


def test_urg_parser_accepts_dashboard_header_and_value_rows() -> None:
    """Parse compact URG dashboard tables that place all metrics on one row."""

    report = """
    SCORE LINE COND TOGGLE FSM BRANCH ASSERT
    Overall 82.0 90.0 80.0 75.0 100.0 66.0 50.0
    """
    metrics = parse_urg_report(report)
    assert [(item.metric, item.percent) for item in metrics] == [
        ("line", 90.0),
        ("cond", 80.0),
        ("tgl", 75.0),
        ("fsm", 100.0),
        ("branch", 66.0),
        ("assert", 50.0),
    ]


def test_urg_parser_aligns_single_metric_html_table_columns() -> None:
    """Parse the O-2018 dashboard table when SCORE and ASSERT cells are line-broken."""

    report = """
    <table>
      <tr><td>SCORE</td><td>ASSERT</td></tr>
      <tr><td>50.00</td><td>50.00</td></tr>
    </table>
    """

    metrics = parse_urg_report(report)

    assert [(item.metric, item.percent) for item in metrics] == [("assert", 50.0)]


def test_formal_parser_preserves_every_canonical_status_including_undec() -> None:
    """Normalize VC Formal/FormalMC status spellings without dropping unknown proofs."""

    log = """
Info-P016: property A_SAFE is TRUE
Info-P016: property A_BAD is FALSE
Info-P016: property A_VAC is TRIVIALLY_TRUE
Info-P016: property A_TRIVIAL_BAD is TRIVIALLY_FALSE
C_REACH covered runtime=0.5 depth=12
C_MISS uncovered
A_LONG Undec
A_OFF disabled
A_TABLE | Proven | 1.2s | depth 8 | coi_size=42
A_CEX falsified runtime=0.4 depth=5 cex=cex/A_CEX.fsdb
1 A_NUMBERED : Pass
2 A_NUMBERED_TT TrivT
3 A_NUMBERED_UNDEC Undec
"""
    parsed = parse_formal_log(log, engine="vc_formal")
    by_name = {item.name: item for item in parsed.properties}
    assert by_name["A_SAFE"].status == FormalPropertyStatus.PROVEN
    assert by_name["A_BAD"].status == FormalPropertyStatus.FALSIFIED
    assert by_name["A_VAC"].status == FormalPropertyStatus.VACUOUS
    assert by_name["A_TRIVIAL_BAD"].status == FormalPropertyStatus.FALSIFIED
    assert by_name["C_REACH"].status == FormalPropertyStatus.COVERED
    assert by_name["C_REACH"].proof_depth == 12
    assert by_name["C_MISS"].status == FormalPropertyStatus.UNCOVERED
    assert by_name["A_LONG"].status == FormalPropertyStatus.INCONCLUSIVE
    assert by_name["A_OFF"].status == FormalPropertyStatus.DISABLED
    assert by_name["A_TABLE"].runtime_seconds == 1.2
    assert by_name["A_TABLE"].proof_depth == 8
    assert by_name["A_TABLE"].coi == "42"
    assert by_name["A_CEX"].counterexample_path.as_posix() == "cex/A_CEX.fsdb"
    assert by_name["A_NUMBERED"].status == FormalPropertyStatus.PROVEN
    assert by_name["A_NUMBERED_TT"].status == FormalPropertyStatus.VACUOUS
    assert by_name["A_NUMBERED_UNDEC"].status == FormalPropertyStatus.INCONCLUSIVE
    assert parsed.verification_status == VerificationStatus.FAILED


def test_malformed_formal_report_is_inconclusive_not_passed() -> None:
    """Retain an explicit diagnostic when report_fv produced no parseable rows."""

    parsed = parse_formal_log("report truncated", return_code=0)
    assert parsed.execution_status == ExecutionStatus.COMPLETED
    assert parsed.verification_status == VerificationStatus.INCONCLUSIVE
    assert parsed.properties == []
    assert parsed.diagnostics[0]["error_code"] == "missing_formal_results"


def test_vc_formal_o2018_list_and_verbose_not_run_are_inconclusive() -> None:
    """Parse real O-2018 report rows and never treat unexecuted goals as passed."""

    report = """
  Summary Results
   Property Summary: FPV
     - # found        : 3
     - # proven       : 1
     - # not_run      : 2

  List Results
     [  0] not_run                                 -  formal_demo.A_FALSIFIED_ALWAYS_HIGH
     [  1] not_run                                 -  formal_demo.A_PROVEN_IDENTITY
     [  2] proven                   (not_run)      -  formal_demo.A_UNBOUNDED_RESPONSE

  Verbose Results
     > ID: [0] not_run
      - name          : formal_demo.A_FALSIFIED_ALWAYS_HIGH
      - language      : SVA

     > ID: [1] not_run
      - name          : formal_demo.A_PROVEN_IDENTITY
      - language      : SVA

     > ID: [2] proven
      - name          : formal_demo.A_UNBOUNDED_RESPONSE
      - engine        : STRUCTURALLY
    """
    parsed = parse_formal_log(report, return_code=0, engine="vc_formal")
    by_name = {item.name: item for item in parsed.properties}

    assert parsed.execution_status == ExecutionStatus.COMPLETED
    assert parsed.verification_status == VerificationStatus.INCONCLUSIVE
    assert by_name["formal_demo.A_FALSIFIED_ALWAYS_HIGH"].status == FormalPropertyStatus.INCONCLUSIVE
    assert by_name["formal_demo.A_PROVEN_IDENTITY"].status == FormalPropertyStatus.INCONCLUSIVE
    assert by_name["formal_demo.A_UNBOUNDED_RESPONSE"].status == FormalPropertyStatus.PROVEN
    assert parsed.diagnostics[0]["error_code"] == "formal_properties_not_run"
    assert parsed.diagnostics[0]["observed"]["count"] == 2

    summary_only_not_run = parse_formal_log(
        "A_SAFE proven\n     - # not_run      : 1\n",
        return_code=0,
        engine="vc_formal",
    )
    assert summary_only_not_run.verification_status == VerificationStatus.INCONCLUSIVE
    assert summary_only_not_run.diagnostics[0]["error_code"] == "formal_properties_not_run"


def test_vc_formal_license_marker_overrides_zero_process_return_code() -> None:
    """Treat O-2018 proof-seat exhaustion as execution failure even when vcf exits zero."""

    parsed = parse_formal_log(
        "[Error] NOT_ENOUGH_APP_LIC: Not enough app specific license(s) to run.\n"
        "     - # not_run      : 2\n",
        return_code=0,
        engine="vc_formal",
    )

    assert parsed.execution_status == ExecutionStatus.ERROR
    assert parsed.verification_status == VerificationStatus.UNKNOWN
    assert parsed.diagnostics[0]["error_code"] == "license_unavailable"
