"""Formal checker parsing must not make the original JSON stage checkpoint fail."""
import json
from types import SimpleNamespace

from ucagent.lang.zh.skills.formal.lib.formal_tools import FormalStageContext


def checker(manager, workspace):
    """Mirror the persistent stage-value API used by existing formal checkers."""
    return SimpleNamespace(stage_manager=manager, workspace=workspace,
        smanager_get_value=lambda key: manager.data.get(key),
        smanager_set_value=lambda key, value: manager.data.__setitem__(key, value))


def test_formal_cache_keeps_json_checkpoint_serializable(tmp_path):
    """Exercise the failing cache path while retaining real durable stage facts."""
    manager = SimpleNamespace(data={'verified_inputs': ['dmac.sv'], 'complete': False})
    context = FormalStageContext.get_or_create(checker(manager, str(tmp_path)))
    source = tmp_path / 'checker.sv'
    source.write_text('assert (dut_ready);')
    assert context.get_checker_content(str(source)) == 'assert (dut_ready);'
    saved = json.dumps({'stage_data': manager.data})
    assert json.loads(saved)['stage_data'] == {'verified_inputs': ['dmac.sv'], 'complete': False}


def test_shared_cache_survives_checkers_and_rebuilds_after_restore(tmp_path):
    """Share one process cache, but restore only durable data into a new manager."""
    manager = SimpleNamespace(data={'input_sha256': 'abc'})
    first = FormalStageContext.get_or_create(checker(manager, None))
    second = FormalStageContext.get_or_create(checker(manager, str(tmp_path)))
    assert first is second
    assert second._workspace == str(tmp_path)
    restored = SimpleNamespace(data=json.loads(json.dumps(manager.data)))
    third = FormalStageContext.get_or_create(checker(restored, str(tmp_path)))
    assert third is not first
    assert json.dumps(restored.data) == json.dumps(manager.data)
