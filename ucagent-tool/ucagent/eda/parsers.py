"""Deterministic parsers for simulator, URG, and formal-engine reports."""

from __future__ import annotations

import html
from html.parser import HTMLParser
from pathlib import Path
import re
from typing import Iterable
import xml.etree.ElementTree as ElementTree

from pydantic import Field

from .models import (
    CoverageMetric,
    ExecutionStatus,
    FormalProperty,
    FormalPropertyStatus,
    StrictModel,
    TestResult,
    VerificationStatus,
)


class ParsedOutput(StrictModel):
    """Bundle normalized conclusions and bounded diagnostics from one process log."""

    execution_status: ExecutionStatus
    verification_status: VerificationStatus
    tests: list[TestResult] = Field(default_factory=list)
    coverage: list[CoverageMetric] = Field(default_factory=list)
    properties: list[FormalProperty] = Field(default_factory=list)
    diagnostics: list[dict[str, object]] = Field(default_factory=list)


_LICENSE_FAILURES = (
    re.compile(r"\bNOT_ENOUGH_APP_LIC\b", re.IGNORECASE),
    re.compile(r"not enough app specific licen[cs]e", re.IGNORECASE),
    re.compile(r"license\s+(?:checkout|check[- ]?out).*(?:fail|denied|unable)", re.IGNORECASE),
    re.compile(r"(?:no|cannot find|unable to obtain).{0,40}(?:valid\s+)?license", re.IGNORECASE),
    re.compile(r"lm_license_file.{0,80}(?:invalid|failed|not set)", re.IGNORECASE),
    re.compile(r"flexnet licensing error", re.IGNORECASE),
)
_COMPILE_FAILURES = (
    re.compile(r"\bError-[A-Z][A-Z0-9_-]*\b"),
    re.compile(r"\b(?:syntax|parse|elaboration|compilation)\s+error\b", re.IGNORECASE),
    re.compile(r"compilation terminated", re.IGNORECASE),
)


def _execution_diagnostic(text: str) -> dict[str, object] | None:
    """Recognize infrastructure failures that must not be reported as DUT bugs."""

    for pattern in _LICENSE_FAILURES:
        match = pattern.search(text)
        if match:
            return {
                "error_code": "license_unavailable",
                "error": "EDA license checkout failed",
                "observed": match.group(0)[:240],
                "next_action": "Check the configured license environment and retry when a license is available.",
            }
    for pattern in _COMPILE_FAILURES:
        match = pattern.search(text)
        if match:
            return {
                "error_code": "compile_error",
                "error": "EDA compilation or elaboration failed",
                "observed": match.group(0)[:240],
                "next_action": "Inspect the compiler log and correct the reported source or file-list error.",
            }
    return None


def parse_uvm_log(
    text: str,
    *,
    return_code: int,
    test_name: str = "unknown",
    suite: str | None = None,
    seed: int | None = None,
    success_markers: Iterable[str] = (),
) -> ParsedOutput:
    """Classify UVM/SV output without conflating DUT failures with process errors."""

    diagnostic = _execution_diagnostic(text)
    if diagnostic is not None:
        test = TestResult(
            test_name=test_name,
            suite=suite,
            seed=seed,
            execution_status=ExecutionStatus.ERROR,
            verification_status=VerificationStatus.UNKNOWN,
            message=str(diagnostic["error"]),
        )
        return ParsedOutput(
            execution_status=ExecutionStatus.ERROR,
            verification_status=VerificationStatus.UNKNOWN,
            tests=[test],
            diagnostics=[diagnostic],
        )

    error_matches = re.findall(r"(?im)^\s*UVM_ERROR\s*(?::|=)\s*(\d+)\s*$", text)
    fatal_matches = re.findall(r"(?im)^\s*UVM_FATAL\s*(?::|=)\s*(\d+)\s*$", text)
    error_count = int(error_matches[-1]) if error_matches else len(re.findall(r"(?m)^UVM_ERROR\b(?!\s*[:=]\s*\d+\s*$)", text))
    fatal_count = int(fatal_matches[-1]) if fatal_matches else len(re.findall(r"(?m)^UVM_FATAL\b(?!\s*[:=]\s*\d+\s*$)", text))
    assertion_failures = 0
    for line in text.splitlines():
        summary = re.search(r"(?i)\bassertion(?:s| failures?)?\s*[:=]\s*(\d+)\s*$", line)
        if summary:
            assertion_failures = max(assertion_failures, int(summary.group(1)))
            continue
        if re.search(r"(?i)(?:\bassertion\b.{0,100}\bfailed\b|\bSVA\b.{0,80}\b(?:fail(?:ed)?|error)\b)", line):
            assertion_failures += 1
    has_summary = bool(re.search(r"UVM_(?:REPORT_)?SUMMARY|UVM Report Summary", text, re.IGNORECASE))
    marker_list = tuple(success_markers) + ("TEST PASSED", "UVM_TEST_PASSED", "HIT GOOD TRAP")
    has_success_marker = any(marker in text for marker in marker_list if marker)
    verification_failure = error_count > 0 or fatal_count > 0 or assertion_failures > 0

    if verification_failure:
        execution = ExecutionStatus.COMPLETED
        verification = VerificationStatus.FAILED
        message = "Verification failures were reported by the testbench."
    elif return_code != 0:
        execution = ExecutionStatus.ERROR
        verification = VerificationStatus.UNKNOWN
        message = f"Simulator exited with return code {return_code} without a verification conclusion."
    elif has_summary or has_success_marker:
        execution = ExecutionStatus.COMPLETED
        verification = VerificationStatus.PASSED
        message = "The test completed with no UVM error, fatal, or assertion failure."
    else:
        execution = ExecutionStatus.COMPLETED
        verification = VerificationStatus.INCONCLUSIVE
        message = "The log has no authoritative UVM summary or configured success marker."

    diagnostics: list[dict[str, object]] = []
    if execution == ExecutionStatus.ERROR:
        diagnostics.append(
            {
                "error_code": "simulator_exit_error",
                "error": message,
                "observed": {"return_code": return_code},
                "next_action": "Inspect the simulator log for an infrastructure or testbench failure.",
            }
        )
    elif verification == VerificationStatus.INCONCLUSIVE:
        diagnostics.append(
            {
                "error_code": "missing_verification_summary",
                "error": message,
                "expected": "UVM summary or a configured project success marker",
                "next_action": "Enable the non-invasive observer or configure the project's signed success marker.",
            }
        )
    test = TestResult(
        test_name=test_name,
        suite=suite,
        seed=seed,
        execution_status=execution,
        verification_status=verification,
        error_count=error_count,
        fatal_count=fatal_count,
        assertion_failures=assertion_failures,
        message=message,
    )
    return ParsedOutput(
        execution_status=execution,
        verification_status=verification,
        tests=[test],
        diagnostics=diagnostics,
    )


def parse_pytest_log(
    text: str,
    *,
    return_code: int,
    test_name: str,
    suite: str | None = None,
    seed: int | None = None,
) -> ParsedOutput:
    """Classify a pytest run from its JUnit report and documented exit status.

    A JUnit ``failure`` is a completed verification failure. Collection,
    setup, and framework ``error`` nodes are infrastructure failures. A run
    that collected no executable test, including an all-skipped selection, is
    inconclusive rather than passed.
    """

    report_matches = list(
        re.finditer(
            r"(?s)(<\?xml[^>]*>\s*)?(<testsuites\b.*?</testsuites>|<testsuite\b.*?</testsuite>)",
            text,
        )
    )
    if not report_matches:
        if return_code == 5:
            message = "Pytest collected no tests."
            test = TestResult(
                test_name=test_name,
                suite=suite,
                seed=seed,
                execution_status=ExecutionStatus.COMPLETED,
                verification_status=VerificationStatus.INCONCLUSIVE,
                message=message,
            )
            return ParsedOutput(
                execution_status=ExecutionStatus.COMPLETED,
                verification_status=VerificationStatus.INCONCLUSIVE,
                tests=[test],
                diagnostics=[
                    {
                        "error_code": "pytest_no_tests_collected",
                        "error": message,
                        "expected": "At least one executable pytest item",
                        "next_action": "Correct the configured UnityTest path or test selection and rerun.",
                    }
                ],
            )
        message = "Pytest did not produce a readable JUnit result."
        return ParsedOutput(
            execution_status=ExecutionStatus.ERROR,
            verification_status=VerificationStatus.UNKNOWN,
            tests=[
                TestResult(
                    test_name=test_name,
                    suite=suite,
                    seed=seed,
                    execution_status=ExecutionStatus.ERROR,
                    verification_status=VerificationStatus.UNKNOWN,
                    message=message,
                )
            ],
            diagnostics=[
                {
                    "error_code": "pytest_report_missing",
                    "error": message,
                    "observed": {"return_code": return_code},
                    "next_action": "Inspect pytest stdout and stderr, then restore the JUnit reporting path.",
                }
            ],
        )

    report_text = report_matches[-1].group(0)
    try:
        report_root = ElementTree.fromstring(report_text)
    except ElementTree.ParseError as exc:
        message = "Pytest produced a malformed JUnit result."
        return ParsedOutput(
            execution_status=ExecutionStatus.ERROR,
            verification_status=VerificationStatus.UNKNOWN,
            tests=[
                TestResult(
                    test_name=test_name,
                    suite=suite,
                    seed=seed,
                    execution_status=ExecutionStatus.ERROR,
                    verification_status=VerificationStatus.UNKNOWN,
                    message=message,
                )
            ],
            diagnostics=[
                {
                    "error_code": "pytest_report_malformed",
                    "error": message,
                    "observed": str(exc)[:240],
                    "next_action": "Inspect the retained report and rerun after correcting the reporting infrastructure.",
                }
            ],
        )

    testcases = report_root.findall(".//testcase")
    total = len(testcases)
    failures = sum(1 for case in testcases if case.find("failure") is not None)
    errors = sum(1 for case in testcases if case.find("error") is not None)
    skipped = sum(1 for case in testcases if case.find("skipped") is not None)
    executed = total - skipped
    diagnostics: list[dict[str, object]] = []
    if return_code in {2, 3, 4} or errors:
        execution = ExecutionStatus.ERROR
        verification = VerificationStatus.UNKNOWN
        message = "Pytest encountered a collection, setup, usage, or framework error."
        diagnostics.append(
            {
                "error_code": "pytest_infrastructure_error",
                "error": message,
                "observed": {
                    "return_code": return_code,
                    "tests": total,
                    "failures": failures,
                    "errors": errors,
                    "skipped": skipped,
                },
                "next_action": "Inspect the JUnit error nodes and pytest logs, then repair the test infrastructure.",
            }
        )
    elif failures:
        if return_code not in {1}:
            execution = ExecutionStatus.ERROR
            verification = VerificationStatus.UNKNOWN
            message = "Pytest exit status conflicts with its JUnit failure count."
            diagnostics.append(
                {
                    "error_code": "pytest_result_mismatch",
                    "error": message,
                    "observed": {"return_code": return_code, "failures": failures},
                    "next_action": "Inspect the retained report and runner log for result corruption.",
                }
            )
        else:
            execution = ExecutionStatus.COMPLETED
            verification = VerificationStatus.FAILED
            message = f"Pytest completed with {failures} verification failure(s)."
    elif return_code == 5 or executed == 0:
        execution = ExecutionStatus.COMPLETED
        verification = VerificationStatus.INCONCLUSIVE
        message = "Pytest selected no executable tests."
        diagnostics.append(
            {
                "error_code": "pytest_no_tests_collected",
                "error": message,
                "observed": {"tests": total, "skipped": skipped},
                "next_action": "Correct the configured UnityTest path or remove unconditional skips and rerun.",
            }
        )
    elif return_code != 0:
        execution = ExecutionStatus.ERROR
        verification = VerificationStatus.UNKNOWN
        message = "Pytest exited unsuccessfully without a verification failure."
        diagnostics.append(
            {
                "error_code": "pytest_exit_error",
                "error": message,
                "observed": {"return_code": return_code},
                "next_action": "Inspect pytest stdout, stderr, and the JUnit report for an infrastructure failure.",
            }
        )
    else:
        execution = ExecutionStatus.COMPLETED
        verification = VerificationStatus.PASSED
        message = f"Pytest completed {executed} executable test(s) without failures."

    test = TestResult(
        test_name=test_name,
        suite=suite,
        seed=seed,
        execution_status=execution,
        verification_status=verification,
        error_count=errors,
        assertion_failures=failures,
        message=message,
    )
    return ParsedOutput(
        execution_status=execution,
        verification_status=verification,
        tests=[test],
        diagnostics=diagnostics,
    )


_COVERAGE_NAMES = {
    "line": "line",
    "cond": "cond",
    "condition": "cond",
    "tgl": "tgl",
    "toggle": "tgl",
    "fsm": "fsm",
    "branch": "branch",
    "assert": "assert",
    "assertion": "assert",
}


class _UrgHtmlTableParser(HTMLParser):
    """Collect textual cells from URG HTML table rows without executing markup."""

    def __init__(self) -> None:
        """Initialize row and cell state for one report document."""

        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Start rows and header/data cells while ignoring all attributes."""

        del attrs
        lowered = tag.lower()
        if lowered == "tr":
            self._row = []
        elif lowered in {"td", "th"} and self._row is not None:
            self._cell = []
        elif lowered == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_data(self, data: str) -> None:
        """Accumulate nested text belonging to the active cell."""

        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        """Finalize cells and nonempty rows at their closing tags."""

        lowered = tag.lower()
        if lowered in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif lowered == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
            self._cell = None


def parse_urg_report(text: str, *, scope: str = "overall") -> list[CoverageMetric]:
    """Extract supported URG percentages and optional covered/total counts."""

    row_broken = re.sub(r"(?i)</(?:tr|div|p|li)>", "\n", text)
    plain = html.unescape(re.sub(r"<[^>]+>", " ", row_broken))
    results: dict[str, CoverageMetric] = {}
    table_parser = _UrgHtmlTableParser()
    table_parser.feed(text)
    table_parser.close()
    for row_index, header in enumerate(table_parser.rows[:-1]):
        metric_columns: list[tuple[int, str]] = []
        for column, cell in enumerate(header):
            words = re.findall(r"[A-Za-z]+", cell.lower())
            metric = next((_COVERAGE_NAMES[word] for word in words if word in _COVERAGE_NAMES), None)
            if metric is not None:
                metric_columns.append((column, metric))
        if not metric_columns:
            continue
        for candidate in table_parser.rows[row_index + 1 : row_index + 4]:
            parsed_cells: list[tuple[str, float]] = []
            for column, metric in metric_columns:
                if column >= len(candidate):
                    continue
                value_match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*%?\s*", candidate[column])
                if value_match is None:
                    continue
                percent = float(value_match.group(1))
                if percent <= 100:
                    parsed_cells.append((metric, percent))
            if not parsed_cells:
                continue
            for metric, percent in parsed_cells:
                if metric not in results:
                    results[metric] = CoverageMetric(metric=metric, percent=percent, scope=scope)
            break
    line_pattern = re.compile(
        r"(?i)^[ \t]*(line|cond(?:ition)?|tgl|toggle|fsm|branch|assert(?:ion)?)"
        r"(?:[ \t]+coverage)?[ \t]*(?::|=|[ \t])[ \t]*"
        r"(\d+(?:\.\d+)?)[ \t]*%?"
        r"(?:[ \t]*(?:\(|\[)?[ \t]*(\d+)[ \t]*(?:/|of)[ \t]*(\d+)[ \t]*(?:\)|\])?)?"
    )
    for line in plain.splitlines():
        match = line_pattern.match(line)
        if match is None:
            continue
        metric = _COVERAGE_NAMES[match.group(1).lower()]
        percent = float(match.group(2))
        if percent > 100:
            continue
        covered = int(match.group(3)) if match.group(3) is not None else None
        total = int(match.group(4)) if match.group(4) is not None else None
        if covered is not None and total is not None and covered > total:
            continue
        results[metric] = CoverageMetric(
            metric=metric,
            percent=percent,
            scope=scope,
            covered=covered,
            total=total,
        )
    lines = [line.strip() for line in plain.splitlines() if line.strip()]
    for index, line in enumerate(lines[:-1]):
        header_words = re.findall(r"[A-Za-z]+", line.lower())
        metric_words = [word for word in header_words if word in _COVERAGE_NAMES]
        if len(metric_words) < 2:
            continue
        has_score_column = "score" in header_words and header_words.index("score") < min(
            header_words.index(word) for word in metric_words
        )
        for candidate in lines[index + 1 : index + 4]:
            numbers = [float(value) for value in re.findall(r"(?<![\w.])(\d+(?:\.\d+)?)\s*%?", candidate)]
            if has_score_column and len(numbers) >= len(metric_words) + 1:
                numbers = numbers[1:]
            if len(numbers) < len(metric_words):
                continue
            for word, percent in zip(metric_words, numbers):
                metric = _COVERAGE_NAMES[word]
                if metric not in results and percent <= 100:
                    results[metric] = CoverageMetric(metric=metric, percent=percent, scope=scope)
            break
    return [results[name] for name in ("line", "cond", "tgl", "fsm", "branch", "assert") if name in results]


_FORMAL_STATUS = {
    "proven": FormalPropertyStatus.PROVEN,
    "proved": FormalPropertyStatus.PROVEN,
    "pass": FormalPropertyStatus.PROVEN,
    "passed": FormalPropertyStatus.PROVEN,
    "true": FormalPropertyStatus.PROVEN,
    "falsified": FormalPropertyStatus.FALSIFIED,
    "fail": FormalPropertyStatus.FALSIFIED,
    "failed": FormalPropertyStatus.FALSIFIED,
    "false": FormalPropertyStatus.FALSIFIED,
    "trivially_false": FormalPropertyStatus.FALSIFIED,
    "cex": FormalPropertyStatus.FALSIFIED,
    "trivially_true": FormalPropertyStatus.VACUOUS,
    "trivial_true": FormalPropertyStatus.VACUOUS,
    "trivt": FormalPropertyStatus.VACUOUS,
    "vacuous": FormalPropertyStatus.VACUOUS,
    "cover_pass": FormalPropertyStatus.COVERED,
    "covered": FormalPropertyStatus.COVERED,
    "reachable": FormalPropertyStatus.COVERED,
    "cover_fail": FormalPropertyStatus.UNCOVERED,
    "uncovered": FormalPropertyStatus.UNCOVERED,
    "unreachable": FormalPropertyStatus.UNCOVERED,
    "undec": FormalPropertyStatus.INCONCLUSIVE,
    "undecided": FormalPropertyStatus.INCONCLUSIVE,
    "undetermined": FormalPropertyStatus.INCONCLUSIVE,
    "unknown": FormalPropertyStatus.INCONCLUSIVE,
    "timeout": FormalPropertyStatus.INCONCLUSIVE,
    "inconclusive": FormalPropertyStatus.INCONCLUSIVE,
    "not_run": FormalPropertyStatus.INCONCLUSIVE,
    "uncoverable": FormalPropertyStatus.UNCOVERED,
    "disabled": FormalPropertyStatus.DISABLED,
    "waived": FormalPropertyStatus.DISABLED,
}
_FORMAL_WORDS = "|".join(sorted((re.escape(word) for word in _FORMAL_STATUS), key=len, reverse=True))


def parse_formal_log(text: str, *, return_code: int = 0, engine: str | None = None,
                     expected_properties: list[dict] | None = None) -> ParsedOutput:
    """Normalize VC Formal and FormalMC outcomes, retaining undecided properties."""

    diagnostic = _execution_diagnostic(text)
    if diagnostic is not None:
        return ParsedOutput(
            execution_status=ExecutionStatus.ERROR,
            verification_status=VerificationStatus.UNKNOWN,
            diagnostics=[diagnostic],
        )

    properties: dict[str, FormalProperty] = {}
    formal_mc = re.compile(
        rf"(?im)Info-P016:\s*property\s+([^\s:]+)\s+is\s+({_FORMAL_WORDS})\b"
    )
    formal_mc_table = re.compile(
        rf"(?im)^\s*\d+\s+([A-Za-z_][\w.$:/\[\]\\-]*)\s*(?:\s*:\s*|\s+)"
        rf"({_FORMAL_WORDS})\b"
    )
    generic = re.compile(
        rf"(?im)^\s*(?:\[[^\]]+\]\s*)?([A-Za-z_$\\][\w.$:/\[\]\\-]*)\s*(?:\||:|=|\s)\s*"
        rf"({_FORMAL_WORDS})\b"
        r"(?:[^\n]*?\b(?:time|runtime)\s*[=:]\s*(\d+(?:\.\d+)?)(?:\s*s)?)?"
        r"(?:[^\n]*?\bdepth\s*[=:]\s*(\d+))?"
    )

    def record(
        name: str,
        raw_status: str,
        runtime: str | None = None,
        depth: str | None = None,
        context: str = "",
    ) -> None:
        """Store the last authoritative outcome for one property name."""

        normalized_word = raw_status.lower().replace("-", "_")
        status = _FORMAL_STATUS[normalized_word]
        upper_name = name.upper()
        if status == FormalPropertyStatus.PROVEN and upper_name.startswith(("C_", "COVER_")):
            status = FormalPropertyStatus.COVERED
        elif status == FormalPropertyStatus.FALSIFIED and upper_name.startswith(("C_", "COVER_")):
            status = FormalPropertyStatus.UNCOVERED
        if runtime is None:
            runtime_match = re.search(r"(?i)\b(?:time|runtime)\s*[=:]?\s*(\d+(?:\.\d+)?)\s*s?\b", context)
            if runtime_match:
                runtime = runtime_match.group(1)
            else:
                column_match = re.search(
                    rf"(?i)(?:^|\|)\s*{re.escape(raw_status)}\s*\|\s*(\d+(?:\.\d+)?)\s*s\b",
                    context,
                )
                if column_match:
                    runtime = column_match.group(1)
        if depth is None:
            depth_match = re.search(r"(?i)\bdepth\s*[=:]?\s*(\d+)\b", context)
            if depth_match:
                depth = depth_match.group(1)
        coi_match = re.search(r"(?i)\bcoi(?:_size)?\s*[=:]\s*([^\s|,]+)", context)
        cex_match = re.search(r"(?i)\b(?:cex|counterexample)(?:_path)?\s*[=:]\s*([^\s|,]+)", context)
        evidence_match = re.search(r"(?i)\bevidence(?:_path)?\s*[=:]\s*([^\s|,]+)", context)
        properties[name] = FormalProperty(
            name=name,
            status=status,
            runtime_seconds=float(runtime) if runtime is not None else None,
            proof_depth=int(depth) if depth is not None else None,
            engine=engine,
            coi=coi_match.group(1) if coi_match else None,
            vacuous=True if status == FormalPropertyStatus.VACUOUS else None,
            counterexample_path=cex_match.group(1) if cex_match else None,
            evidence_path=evidence_match.group(1) if evidence_match else None,
            details={"raw_status": raw_status},
        )

    occupied: list[tuple[int, int]] = []
    for match in formal_mc.finditer(text):
        line_end = text.find("\n", match.start())
        context = text[match.start() : line_end if line_end >= 0 else len(text)]
        record(match.group(1), match.group(2), context=context)
        occupied.append(match.span())
    for match in formal_mc_table.finditer(text):
        line_end = text.find("\n", match.start())
        context = text[match.start() : line_end if line_end >= 0 else len(text)]
        record(match.group(1), match.group(2), context=context)
        occupied.append(match.span())
    vc_formal_list = re.compile(
        rf"(?im)^\s*\[\s*\d+\s*\]\s+({_FORMAL_WORDS})\b"
        r"(?:\s+\([^\r\n)]*\))?\s*-\s*"
        r"([A-Za-z_$\\][\w.$:/\[\]\\-]*)\s*$"
    )
    for match in vc_formal_list.finditer(text):
        record(match.group(2), match.group(1), context=match.group(0))
        occupied.append(match.span())
    vc_formal_verbose_header = re.compile(
        rf"(?im)^\s*>\s*ID:\s*\[\s*\d+\s*\]\s+({_FORMAL_WORDS})\b[^\r\n]*$"
    )
    verbose_headers = list(vc_formal_verbose_header.finditer(text))
    for index, match in enumerate(verbose_headers):
        block_end = verbose_headers[index + 1].start() if index + 1 < len(verbose_headers) else len(text)
        context = text[match.start() : block_end]
        name_match = re.search(
            r"(?im)^\s*-\s*name\s*:\s*([A-Za-z_$\\][\w.$:/\[\]\\-]*)\s*$",
            context,
        )
        if name_match is not None:
            record(name_match.group(1), match.group(1), context=context)
            occupied.append((match.start(), block_end))
    for match in generic.finditer(text):
        if any(start <= match.start() < end for start, end in occupied):
            continue
        line_end = text.find("\n", match.start())
        context = text[match.start() : line_end if line_end >= 0 else len(text)]
        record(match.group(1), match.group(2), match.group(3), match.group(4), context)
    cex_line = re.compile(
        r"(?im)^\s*(?:counterexample|cex)\s+(?:for\s+)?([A-Za-z_$\\][\w.$:/\[\]\\-]*)\s*[:=]\s*(\S+)"
    )
    for match in cex_line.finditer(text):
        if match.group(1) in properties:
            properties[match.group(1)] = properties[match.group(1)].model_copy(
                update={"counterexample_path": Path(match.group(2))}
            )

    if expected_properties is not None:
        from .formalmc_results import parse_results
        checked = parse_results(text, expected_properties, return_code)
        values = []
        for item in checked["properties"]:
            if item["kind"] == "assume":
                continue
            observed = [p for name, p in properties.items() if re.split(r"[./:]", name)[-1] == item["label"]]
            base = observed[0] if len(observed) == 1 else FormalProperty(name=item["label"], status=item["status"], engine=engine)
            values.append(base.model_copy(update={"name": item["label"], "status": FormalPropertyStatus(item["status"]),
                "details": {**base.details, **item, "property_id": item["label"]}}))
        issues = [{"error_code": "migrated_property_result_missing", "error": p["label"],
                   "next_action": "Inspect the retained log and rerun every converted property."}
                  for p in checked["properties"] if p.get("diagnostic")]
        if checked["diagnostic"]:
            issues.append({"error_code": checked["diagnostic"], "error": "FormalMC execution failed.",
                           "next_action": "Repair the reported tool error before accepting property results."})
        return ParsedOutput(execution_status=checked["execution_status"], verification_status=checked["verification_status"],
                            properties=values, diagnostics=issues)
    values = list(properties.values())
    statuses = {item.status for item in values}
    if FormalPropertyStatus.FALSIFIED in statuses:
        verification = VerificationStatus.FAILED
    elif statuses & {FormalPropertyStatus.INCONCLUSIVE, FormalPropertyStatus.UNCOVERED}:
        verification = VerificationStatus.INCONCLUSIVE
    elif statuses & {
        FormalPropertyStatus.PROVEN,
        FormalPropertyStatus.VACUOUS,
        FormalPropertyStatus.COVERED,
    }:
        verification = VerificationStatus.PASSED
    else:
        verification = VerificationStatus.INCONCLUSIVE

    diagnostics: list[dict[str, object]] = []
    not_run_names = sorted(
        item.name
        for item in values
        if str(item.details.get("raw_status", "")).lower().replace("-", "_") == "not_run"
    )
    summary_not_run_counts = [
        int(match.group(1))
        for match in re.finditer(r"(?im)^\s*-\s*#\s*not_run\s*:\s*(\d+)\s*$", text)
    ]
    not_run_count = max([len(not_run_names), *summary_not_run_counts], default=0)
    if not_run_count:
        if verification == VerificationStatus.PASSED:
            verification = VerificationStatus.INCONCLUSIVE
        diagnostics.append(
            {
                "error_code": "formal_properties_not_run",
                "error": "One or more formal properties were not run.",
                "observed": {
                    "count": not_run_count,
                    "properties": not_run_names[:50],
                    "properties_truncated": len(not_run_names) > 50,
                },
                "expected": "Every enabled property has a conclusive proof or counterexample result.",
                "next_action": "Inspect proof-engine availability and rerun the incomplete property set.",
            }
        )
    if return_code != 0 and not values:
        execution = ExecutionStatus.ERROR
        verification = VerificationStatus.UNKNOWN
        diagnostics.append(
            {
                "error_code": "formal_exit_error",
                "error": f"Formal engine exited with return code {return_code} without property results.",
                "observed": {"return_code": return_code},
                "next_action": "Inspect the formal console log and generated Tcl inputs.",
            }
        )
    else:
        execution = ExecutionStatus.COMPLETED
        if not values and not not_run_count:
            diagnostics.append(
                {
                    "error_code": "missing_formal_results",
                    "error": "No recognizable property results were emitted.",
                    "expected": sorted(set(status.value for status in FormalPropertyStatus)),
                    "next_action": "Inspect the raw report and confirm report_fv completed.",
                }
            )
    return ParsedOutput(
        execution_status=execution,
        verification_status=verification,
        properties=values,
        diagnostics=diagnostics,
    )


def parse_urg_output(text: str, *, return_code: int = 0, scope: str = "overall") -> ParsedOutput:
    """Wrap URG metric parsing in the common process-result contract."""

    diagnostic = _execution_diagnostic(text)
    if diagnostic is not None:
        return ParsedOutput(
            execution_status=ExecutionStatus.ERROR,
            verification_status=VerificationStatus.UNKNOWN,
            diagnostics=[diagnostic],
        )
    coverage = parse_urg_report(text, scope=scope)
    if return_code != 0:
        return ParsedOutput(
            execution_status=ExecutionStatus.ERROR,
            verification_status=VerificationStatus.UNKNOWN,
            coverage=coverage,
            diagnostics=[
                {
                    "error_code": "urg_exit_error",
                    "error": f"URG exited with return code {return_code}.",
                    "next_action": "Inspect the URG log and coverage database inputs.",
                }
            ],
        )
    if not coverage:
        return ParsedOutput(
            execution_status=ExecutionStatus.COMPLETED,
            verification_status=VerificationStatus.INCONCLUSIVE,
            diagnostics=[
                {
                    "error_code": "missing_coverage_metrics",
                    "error": "URG completed without recognizable coverage metrics.",
                    "next_action": "Retain the raw report and verify that URG emitted a supported summary.",
                }
            ],
        )
    return ParsedOutput(
        execution_status=ExecutionStatus.COMPLETED,
        verification_status=VerificationStatus.PASSED,
        coverage=coverage,
    )
