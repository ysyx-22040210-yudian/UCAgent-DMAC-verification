"""Require complete results for the CK set of a migrated FormalMC project."""
import re


def parse_results(text, expected, return_code):
    """Require a unique, conclusive outcome for every expected assertion and cover."""
    infrastructure = re.search(
        r"(?im)Error-\w+|syntax error|compilation error|elaboration error|license.{0,100}(?:fail|denied|unavailable)|(?:no|unable to obtain).{0,40}(?:valid )?license|FlexNet Licensing error",
        text)
    statuses = {}
    pattern = re.compile(
        r"(?im)(?:Info-P016:\s*property\s+(\S+)\s+is\s+|^\s*(?:\d+\s+)?([\w.$:/\[\]\\-]+)\s*(?:[:|=]\s*|\s+))"
        r"(TRIVIALLY_TRUE|TRIVIALLY_FALSE|COVER_PASS|COVER_FAIL|PROVEN|PROVED|PASSED|PASS|TRUE|FALSIFIED|FALSE|FAILED|FAIL|COVERED|REACHABLE|UNCOVERED|UNREACHABLE|UNDECIDED|UNDEC|UNKNOWN|TIMEOUT|DISABLED|WAIVED|INCONCLUSIVE)\b")
    for match in pattern.finditer(text):
        full = match.group(1) or match.group(2)
        leaf = re.split(r"[./:]", full)[-1]
        statuses.setdefault(leaf, {})[full] = match.group(3).upper()
    properties = []
    for item in expected:
        if item["kind"] == "assume":
            properties.append({**item, "status": "assumption"})
            continue
        matches = statuses.get(item["label"], {})
        raw = next(iter(matches.values())) if len(matches) == 1 else None
        cover = item["kind"] in {"cover", "guard_witness"}
        if raw in {"PROVEN", "PROVED", "PASS", "PASSED", "TRUE"}:
            state = "covered" if cover else "proven"
        elif raw in {"FALSE", "FALSIFIED", "FAIL", "FAILED", "TRIVIALLY_FALSE"}:
            state = "uncovered" if cover else "falsified"
        elif raw in {"COVER_PASS", "COVERED", "REACHABLE"} and cover:
            state = "covered"
        elif raw in {"COVER_FAIL", "UNCOVERED", "UNREACHABLE"} and cover:
            state = "uncovered"
        elif raw == "TRIVIALLY_TRUE":
            state = "vacuous"
        else:
            state = "inconclusive"
        properties.append({**item, "status": state, "raw_status": raw,
                           "diagnostic": "missing_or_ambiguous_result" if raw is None else None})
    # Preserve tool-reported properties inside RTL as well as the exported CK set.
    expected_labels = {p["label"] for p in expected}
    for leaf, matches in statuses.items():
        if leaf in expected_labels:
            continue
        raw = next(iter(matches.values())) if len(matches) == 1 else None
        state = ("falsified" if raw in {"FALSE", "FALSIFIED", "FAIL", "FAILED", "TRIVIALLY_FALSE"} else
                 "proven" if raw in {"PROVEN", "PROVED", "PASS", "PASSED", "TRUE"} else
                 "covered" if raw in {"COVER_PASS", "COVERED", "REACHABLE"} else "inconclusive")
        properties.append({"label": leaf, "kind": "unmapped", "status": state, "raw_status": raw})
    states = [p["status"] for p in properties if p["kind"] != "assume"]
    verification = ("failed" if "falsified" in states else
                    "passed" if states and all(s in {"proven", "covered"} for s in states) else "inconclusive")
    execution = "completed"
    if return_code != 0 or infrastructure:
        execution, verification = "error", "unknown"
    return {"execution_status": execution, "verification_status": verification,
            "properties": properties, "return_code": return_code,
            "diagnostic": "tool_execution_error" if execution == "error" else None}

