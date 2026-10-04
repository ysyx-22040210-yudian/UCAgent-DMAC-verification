"""Regressions for actual review deliverables and complete static finding linkage."""
from pathlib import Path
import pytest

from ucagent.checkers.formal import BugReportConsistencyChecker, StaticFormalBugLinkageChecker
from ucagent.lang.zh.skills.formal.lib.formal_tools import extract_static_bugs


def checker(kind, workspace):
    """Create a checker with the same resolved workspace contract used by the service."""
    instance = kind('Demo', cfg={'_temp_cfg': {'DUT': 'Demo', 'OUT': 'formal_out'}})
    instance.set_workspace(str(workspace)).on_init()
    (workspace / 'formal_out').mkdir(exist_ok=True)
    return instance


def test_no_defects_still_generates_bug_report(tmp_path):
    """A completed no-defect branch must leave the promised review artifact."""
    instance = checker(BugReportConsistencyChecker, tmp_path)
    Path(instance.paths.records_yaml).write_text('dut: Demo\nanalysis:\n  fa_entries: []\n  tt_entries: []\n')
    passed, result = instance.do_check()
    assert passed, result
    assert Path(instance.paths.bug_report).read_text().strip()


def test_report_generation_error_is_gate_failure(tmp_path, monkeypatch):
    """Disk/template failures cannot close the bug-report stage successfully."""
    instance = checker(BugReportConsistencyChecker, tmp_path)
    Path(instance.paths.records_yaml).write_text('dut: Demo\nanalysis:\n  fa_entries: []\n')
    def fail(*args):
        raise ValueError('report write denied')
    monkeypatch.setattr('ucagent.lang.zh.skills.formal.lib.formal_tools.generate_bug_report_doc', fail)
    passed, result = instance.do_check()
    assert not passed
    assert 'report write denied' in result['details']


@pytest.mark.parametrize('contents', [None, '', ' \n'])
def test_missing_or_empty_static_review_cannot_pass(tmp_path, contents):
    """Absence of reviewed findings is different from absence of the review itself."""
    instance = checker(StaticFormalBugLinkageChecker, tmp_path)
    if contents is not None:
        Path(instance.paths.static_doc).write_text(contents)
    passed, result = instance.do_check()
    assert not passed
    assert 'document' in result['error']


def test_long_static_findings_are_not_silently_dropped(tmp_path):
    """Linkage after a long analysis paragraph belongs to its own finding only."""
    document = tmp_path / 'review.md'
    document.write_text('<BG-STATIC-FIRST>\n' + 'analysis ' * 100 +
                        '\n<LINK-BUG-[BG-NA]>\n<BG-STATIC-SECOND>\nmissing link\n')
    result = extract_static_bugs(str(document))
    assert result['false_positive'] == [('<BG-STATIC-FIRST>', '<LINK-BUG-[BG-NA]>')]
    assert len(result['pending']) == 1
    assert result['pending'][0][0] == '<BG-STATIC-SECOND>'
