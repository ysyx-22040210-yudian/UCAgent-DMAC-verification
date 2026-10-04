"""End-to-end stage actions, restart safety and engine differences for the native GUI API."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading
import time
from uuid import uuid4

import pytest
import yaml
from fastapi.testclient import TestClient

from test_server_platform_api import _create_server
from test_sby_guided_workflow import counter, real_session
from ucagent.platform.formal_session import FormalSession
from ucagent.server.formal_sessions import FormalSessions, SessionAction, SessionCreate


@pytest.fixture
def service(tmp_path, monkeypatch):
    """Create a real platform database without user configuration or production credentials."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    server = _create_server(tmp_path)
    try:
        yield server._platform_runtime.formal_sessions, server
    finally:
        server._platform_runtime.shutdown()


def make_session(service, counter, engine="sby", **options):
    """Import real source inputs through the platform and create original native stages."""
    paths, records = counter
    project = service.store.create_project(name="Counter", source_root=str(Path(paths.workspace) / "Counter"), config={})
    row = service.create(SessionCreate(project_id=project["project_id"], dut="Counter", engine=engine, **options))
    return row


def action(service, row, name, **extra):
    """Submit a revision-checked operation and wait only for its actual worker completion."""
    request = SessionAction(action=name, revision=row["revision"], stage_index=row["view"]["current_index"], request_id=uuid4().hex, **extra)
    result = service.action(row["id"], request)
    if service.worker:
        service.worker.join(timeout=90)
        assert not service.worker.is_alive()
    return service.public(service.load(row["id"]))


def read_references(service, row):
    """Actually read each current reference file via the same API used by the editor."""
    session = service.session(service.load(row["id"]))
    stage = session.stage_manager.get_current_stage()
    for path in stage.reference_files:
        service.read(row["id"], path.replace("\\", "/"))
    return service.public(service.load(row["id"]))


def populate(service, row, records):
    """Save authored records through compare-and-swap, not by overwriting runtime outputs."""
    opened = service.read(row["id"], "formal_out/.formal_records.yaml")
    content = records.model_dump(mode="json")
    content["run_results"] = None
    content["extra_config"]["sby"].pop("review", None)
    return action(service, opened["session"], "save", path=opened["path"], content=yaml.safe_dump(content), sha256=opened["sha256"])


@pytest.mark.parametrize("engine", ["sby", "formalmc"])
def test_real_planning_gates_and_human_review(service, counter, engine):
    """Both engines use actual reference, planning, journal, review and Complete gates."""
    store, _ = service
    row = make_session(store, counter, engine)
    assert len(row["view"]["stages"]) == 11
    assert len(row["view"]["stages"][2]["children"]) == 3
    assert row["view"]["stages"][7]["enabled"] is False
    assert row["view"]["stages"][7]["disabled_reason"]
    row = action(store, row, "complete", journal="Premature completion must fail.")
    assert row["view"]["current_index"] == 0
    row = populate(store, row, counter[1])
    row = read_references(store, row)
    row = action(store, row, "check")
    assert row["last_result"]["check_pass"], row["last_result"]
    assert row["view"]["current_index"] == 0
    row = action(store, row, "complete", journal="Reviewed declared scope, strategy and risks.")
    assert row["view"]["current_index"] == 0
    row = action(store, row, "reject", journal="Need an independent scope review.")
    row = action(store, row, "complete")
    assert row["view"]["current_index"] == 0
    row = action(store, row, "approve", journal="Scope and risks have been checked against the input specification.")
    row = action(store, row, "complete")
    assert row["view"]["current_index"] == 1, row["last_result"]
    assert row["verification_status"] == "unknown"


def test_restore_reopen_conflicts_and_no_forged_checkpoint(service, counter):
    """Restart uses signed native state; reopening invalidates downstream completion only."""
    store, server = service
    row = make_session(store, counter, human_review=False)
    row = populate(store, row, counter[1])
    row = read_references(store, row)
    row = action(store, row, "complete", journal="Planning prepared and checked.")
    assert row["view"]["current_index"] == 1, row["last_result"]
    # This editable on-disk native checkpoint is not the restore authority.
    checkpoint = Path(row["workspace"]) / ".ucagent/ucagent_info.json"
    checkpoint.write_text('{"stage_index":99,"all_completed":true}', encoding="utf-8")
    restored = FormalSessions(server._platform_runtime)
    new = restored.session(restored.load(row["id"]))
    assert new.stage_manager.stage_index == 1
    old_row = row
    opened = restored.read(row["id"], "formal_out/.formal_records.yaml")
    with pytest.raises(ValueError, match="revision"):
        restored.action(row["id"], SessionAction(action="check", revision=old_row["revision"], stage_index=1, request_id=uuid4().hex))
    records = yaml.safe_load(opened["content"])
    records["planning"]["risks"].append("Additional explicit review risk")
    row = action(restored, opened["session"], "save", path=opened["path"], content=yaml.safe_dump(records), sha256=opened["sha256"])
    assert row["view"]["current_index"] == 0
    assert not row["view"]["stages"][0]["details"]["is_completed"]
    assert (Path(row["workspace"]) / "formal_out/.formal_records.yaml").exists()
    with restored.store._connection() as db:
        db.execute("UPDATE formal_sessions SET payload=? WHERE id=?", ('{}', row["id"]))
    with pytest.raises(ValueError, match="signature"):
        restored.load(row["id"])


@pytest.mark.parametrize("engine", ["sby", "formalmc"])
def test_incremental_spec_layers_preserve_upstream_gates(service, counter, engine):
    """Author FG, FC, CK and property bodies separately through real native stage gates."""
    store, _ = service
    row = make_session(store, counter, engine, human_review=False)
    complete_records = counter[1].model_dump(mode="json")
    authored = counter[1].model_copy(deep=True)
    authored.spec.function_groups = []
    row = populate(store, row, authored)
    for expected in range(6):
        assert row["view"]["current_index"] == expected
        if expected in (2, 3, 4):
            opened = store.read(row["id"], "formal_out/.formal_records.yaml")
            document = yaml.safe_load(opened["content"])
            groups = deepcopy(complete_records["spec"]["function_groups"])
            for group in groups:
                if expected == 2:
                    group["functions"] = []
                for function in group["functions"]:
                    if expected == 3:
                        function["check_points"] = []
                    for point in function["check_points"]:
                        for field in ("sva_body", "sby_guard", "sby_trigger"):
                            point.pop(field, None)
            document["spec"]["function_groups"] = groups
            row = action(store, opened["session"], "save", path=opened["path"],
                         content=yaml.safe_dump(document), sha256=opened["sha256"])
            assert row["view"]["current_index"] == expected
        row = read_references(store, row)
        row = action(store, row, "complete", journal="Incremental fixture stage reviewed; no solver acceptance claimed.")
        assert row["view"]["current_index"] == expected + 1, row["last_result"]

    # Property implementation stays at property generation. Earlier semantic
    # edits still invalidate exactly their own gate and all dependent gates.
    edits = [
        (("function_groups", 1, "functions", 0, "check_points", 0, "sva_body"), "y == $past(y)", 6),
        (("function_groups", 1, "functions", 0, "check_points", 0, "sby_guard"), "uc_past_valid", 6),
        (("function_groups", 1, "functions", 0, "check_points", 0, "sby_trigger"), "en", 6),
        (("function_groups", 1, "functions", 0, "check_points"),
         deepcopy(complete_records["spec"]["function_groups"][1]["functions"][0]["check_points"][-1:]), 4),
        (("function_groups", 1, "functions", 0, "check_points", 0, "description"), "Revised checkpoint requirement", 4),
        (("function_groups", 1, "functions", 0, "description"), "Revised function scope", 3),
        (("function_groups", 1, "name"), "Revised group scope", 2),
        (("parameters",), {"WIDTH": 4}, 2),
    ]
    for fields, value, expected in edits:
        opened = store.read(row["id"], "formal_out/.formal_records.yaml")
        document = yaml.safe_load(opened["content"])
        target = document["spec"]
        for field in fields[:-1]:
            target = target[field]
        target[fields[-1]] = value
        row = action(store, opened["session"], "save", path=opened["path"],
                     content=yaml.safe_dump(document), sha256=opened["sha256"])
        assert row["view"]["current_index"] == expected
        manager = store.live[row["id"]].stage_manager
        assert all(stage.is_completed() for stage in manager.stages[:expected])
        assert all(not stage.is_completed() for stage in manager.stages[expected:])
        assert row["verification_status"] == "unknown"


@pytest.mark.parametrize("path", ["../secret", "/etc/passwd", "C:/secret", ".ucagent/runtime_config.json", "formal_out/tests/../../x", "formal_out/tests/manifest.json", "Counter/Counter.sv"])
def test_unsafe_writes_are_rejected(service, counter, path):
    """The GUI cannot overwrite source inputs, control state or signed evidence."""
    store, _ = service
    row = make_session(store, counter)
    session = store.session(store.load(row["id"]))
    with pytest.raises(ValueError):
        session.write(path, "replacement", None)


def test_api_capabilities_csrf_and_idempotency(service, counter):
    """The public API rejects unsupported engines, cross-site writes and duplicate execution."""
    store, server = service
    row = make_session(store, counter)
    with TestClient(server._app) as client:
        sby = client.get("/api/v1/formal-sessions/capabilities?engine=sby").json()
        mc = client.get("/api/v1/formal-sessions/capabilities?engine=formalmc").json()
        assert sby["coi"] == "unsupported" and mc["coi"] == "requires_real_fanin_report"
        assert sby["vacuity"] != mc["vacuity"]
        assert client.get("/api/v1/formal-sessions/capabilities?engine=auto").status_code == 422
        body = dict(action="journal", revision=row["revision"], stage_index=0, request_id=uuid4().hex, journal="Reviewed inputs without claiming proof.")
        endpoint = "/api/v1/formal-sessions/" + row["id"] + "/actions"
        assert client.post(endpoint, json=body, headers={"origin": "https://evil.invalid"}).status_code == 403
        first = client.post(endpoint, json=body)
        assert first.status_code == 200, first.text
        second = client.post(endpoint, json=body)
        assert second.json()["revision"] == first.json()["revision"]
        body["journal"] = "Different mutation with reused key"
        assert client.post(endpoint, json=body).status_code == 409
        events = client.get("/api/v1/formal-sessions/" + row["id"] + "/events?after=0").json()["items"]
        after = events[-1]["sequence"]
        assert client.get("/api/v1/formal-sessions/" + row["id"] + "/events?after=" + str(after)).json()["items"] == []
        metadata = client.get("/api/v1/formal-sessions/" + row["id"] + "/artifact", params={"path": "Counter/Counter.sv"}).json()
        downloaded = client.get("/api/v1" + metadata["download_path"])
        assert hashlib.sha256(downloaded.content).hexdigest() == metadata["sha256"]
        assert client.get("/api/v1/formal-sessions/" + row["id"] + "/download", params={"path": "../platform.db"}).status_code == 409
        assert client.get("/api/v1/formal-sessions/" + row["id"] + "/records").json()["dut"] == "Counter"


def test_cancel_pause_and_service_restart(service, counter, monkeypatch):
    """Cancel never claims success, and interrupted work requires explicit resume and recheck."""
    store, server = service
    row = make_session(store, counter)
    session = store.session(store.load(row["id"]))
    entered = threading.Event()
    def slow_action(*args):
        """Wait for the real cancellation signal without fabricating a verification result."""
        entered.set()
        assert session.cancelled.wait(5)
        return {"check_pass": False}
    monkeypatch.setattr(session, "act", slow_action)
    request = SessionAction(action="check", revision=row["revision"], stage_index=0, request_id=uuid4().hex)
    row = store.action(row["id"], request)
    assert entered.wait(5)
    with pytest.raises(ValueError, match="running"):
        store.read(row["id"], "formal_out/.formal_records.yaml")
    row = action(store, row, "cancel")
    assert row["state"] == "paused" and row["execution_status"] == "cancelled"
    row = action(store, row, "resume")
    assert row["state"] == "ready" and row["verification_status"] == "unknown"
    persisted = store.load(row["id"])
    persisted["state"] = "running"
    store.persist(persisted, "test_interrupted_operation")
    restarted = FormalSessions(server._platform_runtime)
    assert restarted.load(row["id"])["state"] == "paused"
    assert restarted.load(row["id"])["last_result"]["error_code"] == "INTERRUPTED"


@pytest.mark.parametrize("mode", ["prove", "bmc"])
def test_real_sby_all_enabled_gui_stages(service, counter, real_session, monkeypatch, mode):
    """Advance the real original stage sequence with actual SBY and verified final evidence."""
    from ucagent.eda.sby_guided import GuidedSbySession
    installed, _ = real_session
    def host_session(paths, profile_id):
        """Use installed tools with an ephemeral test key, never fabricated solver output."""
        return GuidedSbySession(paths, installed.profile, installed.key)
    monkeypatch.setattr(GuidedSbySession, "from_host", host_session)
    store, _ = service
    records = counter[1].model_copy(deep=True)
    records.extra_config["sby"]["mode"] = mode
    row = make_session(store, counter, human_review=False)
    row = populate(store, row, records)
    expected = "passed" if mode == "prove" else "inconclusive"
    reviewed = False
    for _ in range(20):
        if row["view"]["all_completed"]:
            break
        index = row["view"]["current_index"]
        if index == 8 and not reviewed:
            assert row["verification_status"] == expected, row["last_result"]
            opened = store.read(row["id"], "formal_out/.formal_records.yaml")
            authored = yaml.safe_load(opened["content"])
            authored["extra_config"]["sby"]["review"] = deepcopy(counter[1].extra_config["sby"]["review"])
            authored["extra_config"]["sby"]["review"]["input_sha256"] = row["evidence"]["input_sha256"]
            authored["summary"]["overall_result"] = expected
            for entry in authored["analysis"]["fa_entries"]:
                entry.update(resolution="INCONCLUSIVE", analysis="Bounded checking cannot establish the required unbounded safety proof.")
            row = action(store, opened["session"], "save", path=opened["path"], content=yaml.safe_dump(authored), sha256=opened["sha256"])
            reviewed = True
        row = read_references(store, row)
        row = action(store, row, "complete", journal="Reviewed current stage requirements and actual tool evidence scope.")
        assert row["view"]["current_index"] > index, row["last_result"]
    assert row["view"]["all_completed"]
    assert row["state"] == "completed" and row["verification_status"] == expected
    assert row["evidence"]["coverage"]["coi"] == "unsupported"
    assert row["capabilities"]["vacuity"] == "not_established_trigger_cover_only"
    assert len(list(Path(row["workspace"]).glob("formal_out/tests/sby_runs/*/manifest.json"))) == 2
    observed_events = []
    cursor = 0
    while True:
        page = store.events(row["id"], cursor)["items"]
        if not page:
            break
        observed_events.extend(page)
        cursor = page[-1]["sequence"]
    assert any(event["type"] == "eda.stdout" for event in observed_events)


def test_checkpoint_failure_releases_worker_without_accepting_progress(service, counter, monkeypatch):
    """Storage failure pauses the task and releases the queue without accepting live state."""
    store, _ = service
    row = make_session(store, counter)
    session = store.session(store.load(row["id"]))
    def fail_checkpoint():
        """Model a checkpoint write failure, not a tool verification result."""
        raise OSError("Checkpoint storage unavailable")
    monkeypatch.setattr(session, "checkpoint", fail_checkpoint)
    row = action(store, row, "check")
    assert row["state"] == "paused" and row["execution_status"] == "error"
    assert row["verification_status"] == "unknown"
    assert row["last_result"]["error_code"] == "STAGE_CHECKPOINT_ERROR"
    assert store.active_id is None and row["id"] not in store.live
    assert row["view"]["current_index"] == 0


def test_reject_external_authoring_mutation_and_tool_results_edit(service, counter):
    """Unsigned file edits and handwritten tool results cannot inherit earlier completion."""
    store, _ = service
    row = make_session(store, counter)
    opened = store.read(row["id"], "formal_out/.formal_records.yaml")
    document = yaml.safe_load(opened["content"])
    document["run_results"] = {"timestamp": "forged", "log_hash": "fake", "stats": {}, "failing_properties": [], "tt_properties": []}
    with pytest.raises(ValueError, match="tool-derived"):
        action(store, opened["session"], "save", path=opened["path"], sha256=opened["sha256"], content=yaml.safe_dump(document))
    path = Path(row["workspace"]) / opened["path"]
    path.write_text(opened["content"] + "\n# changed outside the GUI\n", encoding="utf-8")
    with pytest.raises(ValueError, match="outside the managed editor"):
        store.session(store.load(row["id"]))


def test_real_gui_sby_falsified_is_not_execution_error(service, counter, real_session, monkeypatch):
    """An actual counter defect stays falsified and blocks unanalyzed environment completion."""
    from ucagent.eda.sby_guided import GuidedSbySession
    installed, _ = real_session
    monkeypatch.setattr(GuidedSbySession, "from_host", lambda paths, profile_id: GuidedSbySession(paths, installed.profile, installed.key))
    source = Path(counter[0].workspace) / "Counter/Counter.sv"
    source.write_text(source.read_text(encoding="utf-8").replace("4'd1", "4'd2"), encoding="utf-8")
    store, _ = service
    row = make_session(store, counter, human_review=False)
    row = populate(store, row, counter[1])
    while row["view"]["current_index"] < 8:
        index = row["view"]["current_index"]
        row = read_references(store, row)
        row = action(store, row, "complete", journal="Reviewed current stage artifacts.")
        assert row["view"]["current_index"] > index, row["last_result"]
    assert row["execution_status"] == "completed" and row["verification_status"] == "failed"
    assert any(prop["status"] == "falsified" for prop in row["evidence"]["properties"])
    assert list(Path(row["workspace"]).glob("formal_out/tests/sby_runs/**/*.vcd"))
    row = read_references(store, row)
    row = action(store, row, "complete", journal="A failed property must remain failed pending real analysis.")
    assert row["view"]["current_index"] == 8
    assert row["verification_status"] == "failed"


def test_nested_source_references_exclude_proof_history(service, counter):
    """Restarting a task with nested RTL must not require reading hidden staged inputs."""
    store, server = service
    source = Path(counter[0].workspace) / "Counter"
    (source / "rtl").mkdir()
    (source / "Counter.sv").rename(source / "rtl/Counter.sv")
    row = make_session(store, counter, human_review=False)
    workspace = Path(row["workspace"])
    for name in (".ucagent/history/inputs/Counter/rtl/Counter.sv",
                 "formal_out/tests/sby_runs/old/inputs/Counter/rtl/Counter.sv"):
        staged = workspace / name
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text("module ignored; endmodule\n")
    restored = FormalSessions(server._platform_runtime)
    native = restored.session(restored.load(row["id"]))
    for stage in native.stage_manager.stages:
        references = list(stage.reference_files)
        if references:
            assert "Counter/rtl/Counter.sv" in references
        assert not any("history" in p or "sby_runs" in p for p in references)
