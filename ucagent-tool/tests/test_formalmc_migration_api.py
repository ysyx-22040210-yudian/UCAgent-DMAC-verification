"""Verify internal project migration through HTTP with real signed SBY evidence."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from test_formal_gui_sessions import service, make_session, populate
from test_sby_guided_workflow import counter, real_session
from test_formalmc_conversion import tree_hashes
from ucagent.eda.sby_guided import GuidedSbySession, render_environment
from ucagent.eda.adapters.formal_mc import FormalMcAdapter
from ucagent.eda.formalmc_conversion import verify_converted_project
from ucagent.lang.zh.skills.formal.lib.formal_paths import FormalPaths
from ucagent.lang.zh.skills.formal.lib.formal_tools import load_records
from ucagent.server.formal_sessions import FormalSessions, FormalMigrationRequest
from ucagent.platform.project import load_project_config, save_project_config


@pytest.fixture
def migration_source(service, counter, real_session):
    """Create real proof/cover evidence in an API-managed task, never the user workspace."""
    store, server = service
    row = populate(store, make_session(store, counter), counter[1])
    paths = FormalPaths(workspace=row["workspace"], dut="Counter", out="formal_out")
    keyfile = Path.home() / ".ucagent/formal-manifest.key"
    keyfile.parent.mkdir(parents=True, exist_ok=True)
    keyfile.write_bytes(b"x" * 32)
    keyfile.chmod(0o600)
    session = GuidedSbySession(paths, real_session[0].profile, b"x" * 32)
    session.collect(render_environment(paths, load_records(paths.records_yaml)), execute=True)
    return store, server, row


def test_migration_api_creates_linked_native_project_and_reuses_it(migration_source):
    """One action registers the target, preserves source progress and survives restart/retry."""
    store, server, row = migration_source
    endpoint = "/api/v1/formal-sessions/" + row["id"] + "/migrate-formalmc"
    body = {"revision": row["revision"], "request_id": uuid4().hex}
    source_before = tree_hashes(Path(row["workspace"]))
    with TestClient(server._app) as client:
        assert client.post(endpoint, json={**body, "revision": row["revision"] + 1}).status_code == 409
        store.active_id = "another-running-task"
        assert client.post(endpoint, json=body).status_code == 409
        store.active_id = None
        response = client.post(endpoint, json=body)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["session"]["view"] == row["view"]
        assert result["session"]["verification_status"] == row["verification_status"]
        assert result["migration"]["initial_verification_status"] == "not_run"
        assert result["project"]["migration"] == result["migration"]
        assert result["migration"]["source_revision"] == body["revision"]
        assert result["project"]["formal"]["engine"] == "formalmc"
        assert result["project"]["run_defaults"]["formal"]["property_sets"] == ["formal.tcl"]
        assert "artifact" not in result
        target = Path(result["project"]["path"])
        assert not list(target.rglob("*.zip")) and not (target / "run_formalmc.py").exists()
        manifest = verify_converted_project(target, result["migration"]["manifest_sha256"])
        request = FormalMcAdapter().build_formal_request(workspace=target, output_dir=Path("test-results"), tcl_path=Path("formal.tcl"))
        assert request.metadata["expected_properties"] == manifest["properties"]
        assert all(Path(name) in request.input_paths for name in manifest["files"])
        assert client.get("/api/v1/projects/" + result["project"]["id"]).json()["migration"] == result["migration"]
        assert client.get("/api/v1/runs?project_id=" + result["project"]["id"]).json()["items"] == []
        assert client.post(endpoint, json=body).json() == result
        restored = FormalSessions(server._platform_runtime)
        assert restored.migrate_formalmc(row["id"], FormalMigrationRequest(**body))["project"]["id"] == result["project"]["id"]
        assert client.post(endpoint, json={**body, "revision": result["session"]["revision"]}).status_code == 409
        repeat = client.post(endpoint, json={"revision": result["session"]["revision"], "request_id": uuid4().hex})
        assert repeat.status_code == 200 and repeat.json()["project"]["id"] == result["project"]["id"]
        assert len(store.store.list_projects()) == 2
        # Target toolchain selection remains editable without changing the CK snapshot.
        config = load_project_config(target).model_copy(update={"toolchain": "target_machine"})
        save_project_config(target, config)
        assert verify_converted_project(target)["properties"] == manifest["properties"]
        assert tree_hashes(Path(row["workspace"])) == source_before
        assert client.post(endpoint.replace("migrate-formalmc", "export-formalmc"), json=body).status_code == 404
        (target / "formal/Counter_checker.sv").write_text("// changed")
        assert client.post(endpoint, json=body).status_code == 409
        with pytest.raises(ValueError, match="changed"):
            FormalMcAdapter().build_formal_request(workspace=target, output_dir=Path("test-results"), tcl_path=Path("formal.tcl"))


def test_migration_registration_rolls_back_on_receipt_failure(migration_source, monkeypatch):
    """A database error cannot leave a visible project, operation or partial workspace."""
    store, server, row = migration_source
    before = deepcopy(store.load(row["id"]))
    original = store.persist

    def fail_publication(*args, **kwargs):
        """Reject only the final transaction, preserving unrelated fixture operations."""
        if kwargs.get("connection") is not None:
            raise RuntimeError("Injected transaction failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "persist", fail_publication)
    request = FormalMigrationRequest(revision=row["revision"], request_id=uuid4().hex)
    with pytest.raises(RuntimeError, match="Injected"):
        store.migrate_formalmc(row["id"], request)
    assert store.load(row["id"]) == before
    assert len(store.store.list_projects()) == 1
    assert not list((server._platform_runtime.state_dir / "formal_projects").iterdir())
    with store.store._connection() as db:
        assert db.execute("SELECT count(*) FROM formal_project_migrations").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM formal_session_operations WHERE request_id=?", (request.request_id,)).fetchone()[0] == 0


def test_concurrent_retry_creates_one_target(migration_source):
    """Two in-flight retries must converge to one project and one saved operation."""
    store, server, row = migration_source
    request = FormalMigrationRequest(revision=row["revision"], request_id=uuid4().hex)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: store.migrate_formalmc(row["id"], request), range(2)))
    assert results[0]["project"]["id"] == results[1]["project"]["id"]
    assert len(store.store.list_projects()) == 2


def test_migration_rejects_wrong_engine_and_missing_evidence(service, counter):
    """Authoring metadata cannot replace a compiled source run."""
    store, server = service
    with TestClient(server._app) as client:
        for engine in ("formalmc", "sby"):
            row = populate(store, make_session(store, counter, engine=engine), counter[1])
            result = client.post("/api/v1/formal-sessions/" + row["id"] + "/migrate-formalmc",
                                json={"revision": row["revision"], "request_id": uuid4().hex})
            assert result.status_code == 409


def test_new_source_version_creates_new_target_and_old_target_stays_fixed(migration_source):
    """Changed attributes require a new real SBY run and produce a distinct linked snapshot."""
    store, server, row = migration_source
    first = store.migrate_formalmc(row["id"], FormalMigrationRequest(revision=row["revision"], request_id=uuid4().hex))
    before = tree_hashes(Path(first["project"]["path"]))
    paths = FormalPaths(workspace=row["workspace"], dut="Counter", out="formal_out")
    records = load_records(paths.records_yaml)
    records.spec.function_groups[1].functions[0].check_points[0].description += " Reviewed version two."
    current = populate(store, first["session"], records)
    with pytest.raises(ValueError, match="differ"):
        store.migrate_formalmc(row["id"], FormalMigrationRequest(revision=current["revision"], request_id=uuid4().hex))
    # Reuse the exact explicit tools that produced the first run, not a model.
    from ucagent.eda.models import ToolchainProfile
    import os
    executable_root = Path(os.environ["UCAGENT_TEST_SBY_BIN"])
    profile = ToolchainProfile(id="source-version-fixture", tools={name: str(executable_root / name)
        for name in ("sby", "yosys", "yosys-smtbmc", "z3")}, environment={"PATH": str(executable_root) + ":" + os.environ["PATH"]}, minimum_free_bytes=0)
    session = GuidedSbySession(paths, profile, b"x" * 32)
    session.collect(render_environment(paths, load_records(paths.records_yaml)), execute=True)
    second = store.migrate_formalmc(row["id"], FormalMigrationRequest(revision=current["revision"], request_id=uuid4().hex))
    assert first["project"]["id"] != second["project"]["id"]
    assert second["migration"]["initial_verification_status"] == "not_run"
    assert tree_hashes(Path(first["project"]["path"])) == before


@pytest.mark.parametrize("outcome,expected", [("complete", "passed"), ("missing", "inconclusive"),
    ("license", "inconclusive"), ("compile", "inconclusive"), ("timeout", "inconclusive"), ("false", "failed")])
def test_migrated_project_runs_through_existing_native_workflow(migration_source, tmp_path, outcome, expected):
    """Exercise API registration, real child processes and the native runner with synthetic tool logs."""
    import json
    import sys
    import time
    from ucagent.eda import ToolchainProfile
    store, server, row = migration_source
    target = store.migrate_formalmc(row["id"], FormalMigrationRequest(revision=row["revision"], request_id=uuid4().hex))
    root = Path(target["project"]["path"])
    manifest = verify_converted_project(root)
    labels = [p["label"] for p in manifest["properties"] if p["kind"] != "assume"]
    if outcome == "missing":
        labels.pop()
    log = "\n".join(label + (" FALSE" if outcome == "false" and label == "A_CK_COUNT" else " Pass") for label in labels)
    if outcome == "license":
        log += "\nlicense checkout failed"
    if outcome == "compile":
        log += "\ncompilation error"
    fake = tmp_path / "synthetic-formalmc"
    fake.write_text("#!" + sys.executable + "\n" +
        "import sys,time\nfrom pathlib import Path\n" +
        "if '-version' in sys.argv: print('SYNTHETIC native-run fixture'); sys.exit(0)\n" +
        "work=Path(sys.argv[sys.argv.index('-work_dir')+1])\n" +
        "(work/'avis.log').write_text(" + repr(log) + ")\n" +
        ("time.sleep(10)\n" if outcome == "timeout" else "") +
        ("sys.exit(2)\n" if outcome == "compile" else ""))
    fake.chmod(0o700)
    runtime = server._platform_runtime
    runtime._profiles["synthetic-formalmc"] = ToolchainProfile(id="synthetic-formalmc", tools={"formalmc": str(fake)},
        versions={"formalmc": "SYNTHETIC fixture"}, minimum_free_bytes=0)
    native = target["project"]["run_defaults"]
    native["toolchain"] = "synthetic-formalmc"
    with TestClient(server._app) as client:
        # Changing the fixed design is blocked before a run or tool is created.
        altered = deepcopy(native)
        altered["design"]["top"] = "Other"
        assert client.post("/api/v1/runs", json=altered).status_code == 400
        if outcome == "timeout":
            original = runtime._build_run_requests

            def bounded_request(*args, **kwargs):
                """Shorten only this process-boundary fixture's outer runtime budget."""
                jobs = original(*args, **kwargs)
                return [job.model_copy(update={"command": job.command.model_copy(update={"timeout_seconds": 1})}) for job in jobs]

            runtime._build_run_requests = bounded_request
        response = client.post("/api/v1/runs", json=native)
        assert response.status_code == 200, response.text
        run_id = response.json()["id"]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            run = client.get("/api/v1/runs/" + run_id).json()
            if run["execution_status"] not in {"queued", "running"}:
                break
            time.sleep(.05)
        assert run["verification_status"] == expected, run
        if outcome in {"license", "compile", "timeout"}:
            assert run["execution_status"] in {"error", "timeout"}, run
            jobs = runtime.store.list_jobs(run_id)
            assert jobs and all(job["verification_status"] == "unknown" for job in jobs), jobs
        assert verify_converted_project(root)["files"] == manifest["files"]
        assert store.load(row["id"])["view"] == row["view"]
        assert client.get("/api/v1/projects/" + target["project"]["id"]).json()["migration"]["initial_verification_status"] == "not_run"
        if outcome == "complete":
            next_run = client.post("/api/v1/runs", json=native)
            assert next_run.status_code == 200 and next_run.json()["id"] != run_id
