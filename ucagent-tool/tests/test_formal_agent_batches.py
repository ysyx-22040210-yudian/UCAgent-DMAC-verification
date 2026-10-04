"""CK batch authoring preserves native version, source and result protections."""
from copy import deepcopy
import json
from uuid import uuid4

import pytest
import yaml

from test_formal_gui_sessions import service, counter, make_session, populate
from ucagent.server.formal_agent import FormalAgentTurn
from ucagent.server.formal_sessions import SessionAction


def test_ck_batches_use_native_editor_and_reject_stale_or_untrusted_fields(service, counter):
    """Patching a CK must preserve every other field and cannot alter signed results or metadata."""
    store, _ = service
    row = make_session(store, counter, human_review=False)
    row = populate(store, row, counter[1])
    turn = FormalAgentTurn(store, row['id'], SessionAction(action='agent', revision=row['revision'],
        stage_index=0, request_id=uuid4().hex, timeout=120))
    store.active_id = row['id']
    try:
        opened = turn.call('ReadTextFile', path='formal_out/.formal_records.yaml')
        before = yaml.safe_load(opened['content'])
        batch = turn.call('ReadCheckPoints', ids=['CK-COUNT'])
        assert batch['sha256'] == opened['sha256']
        result = turn.call('UpdateCheckPoints', check_points=[{'id': 'CK-COUNT', 'sva_body': 'y == $past(y)'}],
                           expected_sha256=batch['sha256'])
        assert result['updated_ck_ids'] == ['CK-COUNT']
        after = yaml.safe_load(turn.call('ReadTextFile', path=opened['path'])['content'])
        expected = deepcopy(before)
        expected['spec']['function_groups'][1]['functions'][0]['check_points'][0]['sva_body'] = 'y == $past(y)'
        assert after == expected
        with pytest.raises(ValueError, match='changed'):
            turn.call('UpdateCheckPoints', check_points=[{'id': 'CK-COUNT', 'sva_body': 'y == 0'}],
                      expected_sha256=batch['sha256'])
        latest = turn.call('ReadCheckPoints', ids=['CK-COUNT'])
        for invalid in ({'id': 'CK-COUNT', 'style': 'Cover'}, {'id': 'CK-COUNT', 'run_results': {}},
                        {'id': 'CK-UNKNOWN', 'sva_body': '1'}, {'id': 'CK-COUNT', 'sva_body': 1}):
            with pytest.raises(ValueError):
                turn.call('UpdateCheckPoints', check_points=[invalid], expected_sha256=latest['sha256'])
        assert turn.call('ReadCheckPoints', ids=['CK-COUNT'])['sha256'] == latest['sha256']
        with pytest.raises(ValueError):
            turn.call('ReadCheckPoints', ids=['CK-COUNT', 'CK-COUNT'])
        assert store.load(row['id'])['verification_status'] == 'unknown'
    finally:
        store.active_id = None
