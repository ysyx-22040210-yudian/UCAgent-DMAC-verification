"""Offline project import must preserve work and refuse ambiguous package declarations."""
import json
from pathlib import Path

import pytest

from ucagent.server.portable_main import seed_projects


def test_declared_dmac_projects_import_once_and_keep_user_changes(tmp_path):
    bundle = tmp_path / 'bundle'
    data = tmp_path / 'data'
    bundle.mkdir()
    data.mkdir()
    (bundle / 'bundle.json').write_text(json.dumps({'projects': ['DMAC-native', 'DMAC-main']}))
    for name in ('DMAC-native', 'DMAC-main'):
        source = bundle / 'examples' / name
        source.mkdir(parents=True)
        (source / 'rtl.sv').write_text('original')
    first = seed_projects(bundle, data)
    assert [name for name, _ in first] == ['DMAC-native', 'DMAC-main']
    (first[0][1] / 'rtl.sv').write_text('user edit')
    (first[0][1] / 'run.log').write_text('user history')
    assert seed_projects(bundle, data) == first
    assert (first[0][1] / 'rtl.sv').read_text() == 'user edit'
    assert (first[0][1] / 'run.log').read_text() == 'user history'


@pytest.mark.parametrize('names', [['../escape'], ['same', 'same'], [], 'DMAC'])
def test_invalid_offline_project_declaration_cannot_import(tmp_path, names):
    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    data = tmp_path / 'data'
    data.mkdir()
    (bundle / 'bundle.json').write_text(json.dumps({'projects': names}))
    with pytest.raises(ValueError):
        seed_projects(bundle, data)


def test_old_counter_release_still_imports_default_projects(tmp_path):
    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    data = tmp_path / 'data'
    data.mkdir()
    (bundle / 'bundle.json').write_text('{}')
    for name in ('sby_counter', 'sby_counter_bug'):
        (bundle / 'examples' / name).mkdir(parents=True)
    assert len(seed_projects(bundle, data)) == 2
