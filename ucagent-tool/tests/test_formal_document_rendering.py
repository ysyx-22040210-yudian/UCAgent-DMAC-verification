"""Verify that accepted formal records produce readable documents and failures remain visible."""
from pathlib import Path

import pytest

from ucagent.lang.zh.skills.formal.lib import formal_tools as tools
from ucagent.lang.zh.skills.formal.lib.models import FormalRecords


def records():
    """Use the minimal currently documented schema, including actual requirement identities."""
    return FormalRecords(dut='Counter', planning={
        'project_overview': 'Portable counter verification',
        'verification_scope': {'included': ['count and reset']},
        'strategy': ['prove and cover'], 'deliverables': ['evidence'],
        'risks': ['Unbounded stalls do not imply eventual completion'],
        'requirements': [{'id': 'R04', 'requirement': 'Exact transfer quota',
                          'guided_responsibility': 'protocol', 'native_responsibility': 'queue model'}],
        'native_ck_obligations': [{'planned_id': 'NCK-R04-COUNT', 'obligation': 'count model',
                                   'parameters': 'LEN_W=32'}]},
        basic_info={'module_type': 'counter',
            'ports': {'inputs': [{'name': 'clk', 'width': 1, 'signal_type': 'clock', 'desc': 'clock'}],
                      'outputs': [{'name': 'y', 'width': 4, 'signal_type': 'data', 'desc': 'value'}]},
            'clock_reset': {'clock_signal': 'clk', 'clock_count': 1, 'reset_signal': 'rst_n'},
            'core_functions': ['count'], 'correctness_requirements': ['reset clears']})


def test_minimal_planning_and_basic_info_are_actually_rendered(tmp_path):
    """Optional nested metadata must not make the accepted Guide_Doc schema lose its reports."""
    data = records()
    plan = tmp_path / '01_Counter_verification_needs_and_plan.md'
    basic = tmp_path / '02_Counter_basic_info.md'
    tools.generate_planning_doc(data, str(plan))
    tools.generate_basic_info_doc(data, str(basic))
    assert 'Portable counter verification' in plan.read_text()
    assert 'Unbounded stalls' in plan.read_text()
    assert 'R04' in plan.read_text() and 'NCK-R04-COUNT' in plan.read_text()
    assert '| y | 4 |' in basic.read_text()
    assert '| clk | 1 |' in basic.read_text()


def test_rich_planning_retains_risk_and_mitigation(tmp_path):
    """Existing structured risk data is rendered with both cause and mitigation."""
    data = records()
    data.planning['risks'] = [{'risk': 'reset timing', 'mitigation': 'sampled model'}]
    target = tmp_path / 'planning.md'
    tools.generate_planning_doc(data, str(target))
    assert 'reset timing' in target.read_text() and 'sampled model' in target.read_text()


def test_missing_template_cannot_be_reported_as_rendered(tmp_path):
    """A missing resource is a gate error, not a logged success with no artifact."""
    with pytest.raises(ValueError, match='missing-dmac-template'):
        tools._render_to_file('missing-dmac-template.md', {'DUT': 'Counter'}, str(tmp_path / 'missing.md'))
    assert not (tmp_path / 'missing.md').exists()


def test_output_write_failure_is_visible(tmp_path):
    """A missing output directory must propagate a concrete error to the stage gate."""
    target = tmp_path / 'missing-parent' / 'planning.md'
    with pytest.raises(ValueError, match='planning.md'):
        tools.generate_planning_doc(records(), str(target))


def test_hdl_template_keeps_undefined_expression_failures(tmp_path):
    """Optional Markdown metadata handling must not relax HDL expression rendering."""
    import jinja2
    captured = []
    real = jinja2.Environment

    def environment(*args, **kwargs):
        captured.append(kwargs.get('undefined', jinja2.Undefined))
        return real(*args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(jinja2, 'Environment', environment)
        tools._render_to_file('tests/checker.sv', {}, str(tmp_path / 'checker.sv'))
    assert captured == [jinja2.Undefined]
