# -*- coding: utf-8 -*-
"""SQLite persistence for the visual verification platform.

The store keeps small, queryable metadata in SQLite while large EDA artifacts
remain on disk.  Every mutating method is transactional and JSON payloads are
stored in canonical form so callers can reproduce and audit a run.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional


def _json_dump(value: Any) -> str:
    """Serialize a JSON value deterministically for persistent records."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_load(value: Optional[str], default: Any) -> Any:
    """Deserialize an optional JSON column with a caller supplied default."""

    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _utc_timestamp() -> float:
    """Return the current Unix timestamp."""

    return time.time()


class PlatformStore:
    """Persist projects, runs, events, results, and audit records in SQLite."""

    def __init__(self, state_dir: str) -> None:
        """Create the store and initialize its schema under ``state_dir``."""

        self.state_dir = os.path.abspath(state_dir)
        os.makedirs(self.state_dir, exist_ok=True)
        self.db_path = os.path.join(self.state_dir, "platform.db")
        self._lock = threading.RLock()
        self._event_condition = threading.Condition(self._lock)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Yield a configured connection and commit or roll back atomically."""

        connection = sqlite3.connect(self.db_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        """Create the current platform schema and enable WAL journaling."""

        schema = """
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;
        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            source_root TEXT NOT NULL,
            config_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
            workflow TEXT NOT NULL,
            adapter TEXT NOT NULL,
            execution_status TEXT NOT NULL,
            verification_status TEXT NOT NULL,
            request_json TEXT NOT NULL,
            result_json TEXT,
            diagnostic_json TEXT,
            created_at REAL NOT NULL,
            started_at REAL,
            finished_at REAL
        );
        CREATE INDEX IF NOT EXISTS runs_project_created
            ON runs(project_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS workflows (
            workflow_id TEXT PRIMARY KEY,
            family TEXT NOT NULL,
            methodology TEXT NOT NULL,
            authoring_mode TEXT NOT NULL,
            definition_json TEXT NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS stages (
            stage_id TEXT NOT NULL,
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            execution_status TEXT NOT NULL,
            verification_status TEXT NOT NULL,
            approval_status TEXT NOT NULL,
            enabled INTEGER NOT NULL,
            disabled_reason TEXT,
            ordinal INTEGER NOT NULL,
            details_json TEXT NOT NULL,
            PRIMARY KEY(run_id, stage_id)
        );
        CREATE INDEX IF NOT EXISTS stages_run_ordinal ON stages(run_id, ordinal);
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            stage_id TEXT,
            kind TEXT NOT NULL,
            execution_status TEXT NOT NULL,
            verification_status TEXT NOT NULL,
            command_json TEXT NOT NULL,
            result_json TEXT,
            created_at REAL NOT NULL,
            started_at REAL,
            finished_at REAL
        );
        CREATE INDEX IF NOT EXISTS jobs_run_created ON jobs(run_id, created_at);
        CREATE TABLE IF NOT EXISTS attempts (
            attempt_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
            number INTEGER NOT NULL,
            execution_status TEXT NOT NULL,
            result_json TEXT,
            manifest_path TEXT,
            created_at REAL NOT NULL,
            finished_at REAL,
            UNIQUE(job_id, number)
        );
        CREATE TABLE IF NOT EXISTS events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS events_run_sequence
            ON events(run_id, sequence);
        CREATE TABLE IF NOT EXISTS artifacts (
            artifact_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            path TEXT NOT NULL,
            media_type TEXT,
            size_bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS artifacts_run ON artifacts(run_id);
        CREATE TABLE IF NOT EXISTS test_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            test_name TEXT NOT NULL,
            suite TEXT,
            seed INTEGER,
            status TEXT NOT NULL,
            duration_s REAL,
            details_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS test_results_run ON test_results(run_id);
        CREATE TABLE IF NOT EXISTS coverage_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            metric TEXT NOT NULL,
            covered REAL,
            total REAL,
            percent REAL,
            scope TEXT,
            details_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS coverage_metrics_run ON coverage_metrics(run_id);
        CREATE TABLE IF NOT EXISTS formal_properties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            property_name TEXT NOT NULL,
            status TEXT NOT NULL,
            engine TEXT,
            depth INTEGER,
            duration_s REAL,
            details_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS formal_properties_run
            ON formal_properties(run_id);
        CREATE TABLE IF NOT EXISTS issues (
            issue_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            severity TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            details_json TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS issues_run ON issues(run_id);
        CREATE TABLE IF NOT EXISTS stage_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            stage_id TEXT NOT NULL,
            action TEXT NOT NULL,
            note TEXT,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS human_approvals (
            approval_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            stage_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            note TEXT,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS counterexample_replays (
            replay_id TEXT PRIMARY KEY,
            source_run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            property_name TEXT NOT NULL,
            counterexample_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
            target_run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            methodology TEXT NOT NULL,
            status TEXT NOT NULL,
            request_json TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            UNIQUE(source_run_id, target_run_id)
        );
        CREATE INDEX IF NOT EXISTS counterexample_replays_source
            ON counterexample_replays(source_run_id, created_at);
        CREATE INDEX IF NOT EXISTS counterexample_replays_target
            ON counterexample_replays(target_run_id);
        CREATE TABLE IF NOT EXISTS toolchain_probes (
            profile_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            details_json TEXT NOT NULL,
            probed_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            subject_type TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            details_json TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        """
        with self._lock, self._connection() as connection:
            connection.executescript(schema)
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(stages)").fetchall()
            }
            if "status" in columns:
                legacy_rows = [
                    dict(row) for row in connection.execute("SELECT * FROM stages").fetchall()
                ]
                connection.execute("DROP INDEX IF EXISTS stages_run_ordinal")
                connection.execute("ALTER TABLE stages RENAME TO stages_legacy")
                connection.execute(
                    """
                    CREATE TABLE stages (
                        stage_id TEXT NOT NULL,
                        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                        name TEXT NOT NULL,
                        execution_status TEXT NOT NULL,
                        verification_status TEXT NOT NULL,
                        approval_status TEXT NOT NULL,
                        enabled INTEGER NOT NULL,
                        disabled_reason TEXT,
                        ordinal INTEGER NOT NULL,
                        details_json TEXT NOT NULL,
                        PRIMARY KEY(run_id, stage_id)
                    )
                    """
                )
                for row in legacy_rows:
                    status = str(row.get("status") or "pending")
                    execution_status = str(
                        row.get("execution_status")
                        or {
                            "pending": "queued",
                            "approved": "completed",
                            "rejected": "cancelled",
                            "disabled": "cancelled",
                        }.get(status, status)
                    )
                    details = _json_load(row.get("details_json"), {})
                    approval_status = str(
                        row.get("approval_status")
                        or (
                            status
                            if status in {"approved", "rejected"}
                            else (
                                "pending"
                                if details.get("requires_human_approval") is True
                                and bool(row.get("enabled"))
                                else "not_required"
                            )
                        )
                    )
                    connection.execute(
                        """
                        INSERT INTO stages(
                            stage_id,run_id,name,execution_status,verification_status,
                            approval_status,enabled,disabled_reason,ordinal,details_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            row["stage_id"],
                            row["run_id"],
                            row["name"],
                            execution_status,
                            str(row.get("verification_status") or "unknown"),
                            approval_status,
                            row["enabled"],
                            row.get("disabled_reason"),
                            row["ordinal"],
                            row["details_json"],
                        ),
                    )
                connection.execute("DROP TABLE stages_legacy")
                connection.execute(
                    "CREATE INDEX stages_run_ordinal ON stages(run_id, ordinal)"
                )
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(stages)").fetchall()
                }
            if "execution_status" not in columns:
                connection.execute(
                    "ALTER TABLE stages ADD COLUMN execution_status TEXT NOT NULL DEFAULT 'queued'"
                )
            if "verification_status" not in columns:
                connection.execute(
                    "ALTER TABLE stages ADD COLUMN verification_status TEXT NOT NULL DEFAULT 'unknown'"
                )
            if "approval_status" not in columns:
                connection.execute(
                    "ALTER TABLE stages ADD COLUMN approval_status TEXT NOT NULL DEFAULT 'not_required'"
                )

    @staticmethod
    def _row(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        """Convert one SQLite row into a plain dictionary."""

        return dict(row) if row is not None else None

    def create_project(
        self,
        *,
        name: str,
        source_root: str,
        config: Dict[str, Any],
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Insert a project and return its public representation."""

        identifier = project_id or uuid.uuid4().hex
        now = _utc_timestamp()
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?)",
                (identifier, name, os.path.abspath(source_root), _json_dump(config), now, now),
            )
        self.add_audit_event("project.created", "project", identifier, {"name": name})
        project = self.get_project(identifier)
        assert project is not None
        return project

    def list_projects(self) -> List[Dict[str, Any]]:
        """Return all projects ordered by most recent update."""

        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC"
            ).fetchall()
        return [self._project_public(dict(row)) for row in rows]

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Return one project or ``None`` when it does not exist."""

        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE project_id=?", (project_id,)
            ).fetchone()
        return self._project_public(dict(row)) if row is not None else None

    @staticmethod
    def _project_public(row: Dict[str, Any]) -> Dict[str, Any]:
        """Decode a stored project row for API consumers."""

        row["config"] = _json_load(row.pop("config_json", None), {})
        return row

    def update_project(self, project_id: str, *, name: str, config: Dict[str, Any]) -> bool:
        """Update a project's name and canonical configuration."""

        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                "UPDATE projects SET name=?, config_json=?, updated_at=? WHERE project_id=?",
                (name, _json_dump(config), _utc_timestamp(), project_id),
            )
        if cursor.rowcount:
            self.add_audit_event("project.updated", "project", project_id, {"name": name})
        return bool(cursor.rowcount)

    def delete_project(self, project_id: str) -> bool:
        """Delete one project and its indexed run metadata."""

        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM projects WHERE project_id=?", (project_id,)
            )
        if cursor.rowcount:
            self.add_audit_event("project.deleted", "project", project_id, {})
        return bool(cursor.rowcount)

    def create_run(
        self,
        *,
        project_id: str,
        workflow: str,
        adapter: str,
        request: Dict[str, Any],
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a queued run and its initial persistent event."""

        identifier = run_id or uuid.uuid4().hex
        now = _utc_timestamp()
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO runs(
                    run_id, project_id, workflow, adapter, execution_status,
                    verification_status, request_json, result_json,
                    diagnostic_json, created_at, started_at, finished_at
                ) VALUES (?, ?, ?, ?, 'queued', 'unknown', ?, NULL, NULL, ?, NULL, NULL)
                """,
                (identifier, project_id, workflow, adapter, _json_dump(request), now),
            )
        self.append_event(identifier, "run.queued", {"execution_status": "queued"})
        self.add_audit_event("run.created", "run", identifier, {"project_id": project_id})
        run = self.get_run(identifier)
        assert run is not None
        return run

    def save_workflow(
        self,
        *,
        workflow_id: str,
        family: str,
        methodology: str,
        authoring_mode: str,
        definition: Dict[str, Any],
    ) -> None:
        """Upsert a complete workflow definition, including disabled stages."""

        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO workflows(
                    workflow_id,family,methodology,authoring_mode,definition_json,updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(workflow_id) DO UPDATE SET
                    family=excluded.family,
                    methodology=excluded.methodology,
                    authoring_mode=excluded.authoring_mode,
                    definition_json=excluded.definition_json,
                    updated_at=excluded.updated_at
                """,
                (
                    workflow_id,
                    family,
                    methodology,
                    authoring_mode,
                    _json_dump(definition),
                    _utc_timestamp(),
                ),
            )

    def replace_run_stages(self, run_id: str, stages: List[Dict[str, Any]]) -> None:
        """Replace a run's persisted stage DAG projection atomically."""

        with self._lock, self._connection() as connection:
            connection.execute("DELETE FROM stages WHERE run_id=?", (run_id,))
            for ordinal, stage in enumerate(stages):
                details = dict(stage)
                legacy_status = str(details.pop("status", ""))
                enabled = bool(stage.get("enabled", True))
                execution_status = str(
                    stage.get("execution_status")
                    or (
                        legacy_status
                        if legacy_status in {"queued", "running", "completed", "error", "timeout", "cancelled"}
                        else ("queued" if enabled else "cancelled")
                    )
                )
                approval_status = str(
                    stage.get("approval_status")
                    or (
                        "pending"
                        if stage.get("requires_human_approval") is True and enabled
                        else "not_required"
                    )
                )
                connection.execute(
                    """
                    INSERT INTO stages(
                        stage_id,run_id,name,execution_status,verification_status,
                        approval_status,enabled,disabled_reason,ordinal,details_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(stage.get("id") or stage.get("stage_id") or f"stage-{ordinal}"),
                        run_id,
                        str(stage.get("name") or stage.get("title") or f"Stage {ordinal + 1}"),
                        execution_status,
                        str(stage.get("verification_status") or "unknown"),
                        approval_status,
                        1 if enabled else 0,
                        stage.get("disabled_reason"),
                        ordinal,
                        _json_dump(details),
                    ),
                )

    def list_run_stages(self, run_id: str) -> List[Dict[str, Any]]:
        """Return the complete ordered stage catalog for a run."""

        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM stages WHERE run_id=? ORDER BY ordinal", (run_id,)
            ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data.pop("status", None)
            details = _json_load(data.pop("details_json", None), {})
            result.append({**details, **data, "enabled": bool(data["enabled"])})
        return result

    def create_job(
        self,
        *,
        run_id: str,
        kind: str,
        command: Dict[str, Any],
        stage_id: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> str:
        """Create one queued EDA job and return its stable identifier."""

        identifier = job_id or uuid.uuid4().hex
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO jobs(
                    job_id,run_id,stage_id,kind,execution_status,verification_status,
                    command_json,result_json,created_at,started_at,finished_at
                ) VALUES (?, ?, ?, ?, 'queued', 'unknown', ?, NULL, ?, NULL, NULL)
                """,
                (identifier, run_id, stage_id, kind, _json_dump(command), _utc_timestamp()),
            )
        return identifier

    def finish_job(
        self,
        job_id: str,
        *,
        execution_status: str,
        verification_status: str,
        result: Dict[str, Any],
    ) -> None:
        """Persist a terminal job result without conflating execution and verification."""

        now = _utc_timestamp()
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                UPDATE jobs SET execution_status=?,verification_status=?,result_json=?,
                    started_at=COALESCE(started_at,created_at),finished_at=? WHERE job_id=?
                """,
                (execution_status, verification_status, _json_dump(result), now, job_id),
            )

    def update_job_status(
        self,
        job_id: str,
        *,
        execution_status: str,
        verification_status: Optional[str] = None,
    ) -> bool:
        """Advance a queued job while preserving its independent conclusion."""

        now = _utc_timestamp()
        terminal = execution_status in {"completed", "error", "timeout", "cancelled"}
        with self._lock, self._connection() as connection:
            current = connection.execute(
                "SELECT verification_status FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if current is None:
                return False
            verification = verification_status or current["verification_status"]
            cursor = connection.execute(
                """
                UPDATE jobs SET execution_status=?,verification_status=?,
                    started_at=CASE
                        WHEN ?='running' THEN COALESCE(started_at,?)
                        ELSE started_at
                    END,
                    finished_at=CASE WHEN ? THEN ? ELSE NULL END
                WHERE job_id=?
                """,
                (
                    execution_status,
                    verification,
                    execution_status,
                    now,
                    1 if terminal else 0,
                    now,
                    job_id,
                ),
            )
        return bool(cursor.rowcount)

    def create_attempt(
        self,
        *,
        job_id: str,
        number: int,
        execution_status: str,
        result: Optional[Dict[str, Any]] = None,
        manifest_path: Optional[str] = None,
    ) -> str:
        """Persist one immutable job attempt for audit and restart recovery."""

        identifier = uuid.uuid4().hex
        now = _utc_timestamp()
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO attempts(
                    attempt_id,job_id,number,execution_status,result_json,manifest_path,
                    created_at,finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identifier,
                    job_id,
                    int(number),
                    execution_status,
                    _json_dump(result) if result is not None else None,
                    manifest_path,
                    now,
                    now if execution_status in {"completed", "error", "timeout", "cancelled"} else None,
                ),
            )
        return identifier

    def update_attempt(
        self,
        attempt_id: str,
        *,
        execution_status: str,
        result: Optional[Dict[str, Any]] = None,
        manifest_path: Optional[str] = None,
    ) -> bool:
        """Advance one persisted attempt and attach terminal evidence atomically."""

        terminal = execution_status in {"completed", "error", "timeout", "cancelled"}
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE attempts SET execution_status=?,result_json=?,manifest_path=?,
                    finished_at=? WHERE attempt_id=?
                """,
                (
                    execution_status,
                    _json_dump(result) if result is not None else None,
                    manifest_path,
                    _utc_timestamp() if terminal else None,
                    attempt_id,
                ),
            )
        return bool(cursor.rowcount)

    def list_jobs(self, run_id: str) -> List[Dict[str, Any]]:
        """Return jobs and attempts for a run in creation order."""

        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs WHERE run_id=? ORDER BY created_at", (run_id,)
            ).fetchall()
            attempts = connection.execute(
                """
                SELECT a.* FROM attempts a JOIN jobs j ON j.job_id=a.job_id
                WHERE j.run_id=? ORDER BY a.number
                """,
                (run_id,),
            ).fetchall()
        attempts_by_job: Dict[str, List[Dict[str, Any]]] = {}
        for row in attempts:
            item = dict(row)
            item["result"] = _json_load(item.pop("result_json", None), None)
            attempts_by_job.setdefault(item["job_id"], []).append(item)
        result = []
        for row in rows:
            item = dict(row)
            item["command"] = _json_load(item.pop("command_json", None), {})
            item["result"] = _json_load(item.pop("result_json", None), None)
            item["attempts"] = attempts_by_job.get(item["job_id"], [])
            result.append(item)
        return result

    def update_run_status(
        self,
        run_id: str,
        *,
        execution_status: str,
        verification_status: Optional[str] = None,
        diagnostic: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Update run lifecycle fields without conflating verification failure."""

        now = _utc_timestamp()
        terminal = execution_status in {"completed", "error", "timeout", "cancelled"}
        with self._lock, self._connection() as connection:
            current = connection.execute(
                "SELECT started_at, verification_status FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if current is None:
                return False
            started_at = current["started_at"]
            if execution_status == "running" and started_at is None:
                started_at = now
            verification = verification_status or current["verification_status"]
            cursor = connection.execute(
                """
                UPDATE runs SET execution_status=?, verification_status=?,
                    diagnostic_json=?, started_at=?, finished_at=? WHERE run_id=?
                """,
                (
                    execution_status,
                    verification,
                    _json_dump(diagnostic) if diagnostic else None,
                    started_at,
                    now if terminal else None,
                    run_id,
                ),
            )
        self.append_event(
            run_id,
            "run.status",
            {"execution_status": execution_status, "verification_status": verification},
        )
        return bool(cursor.rowcount)

    @staticmethod
    def _replace_run_result(
        connection: sqlite3.Connection,
        run_id: str,
        result: Dict[str, Any],
    ) -> None:
        """Replace a run's aggregate and normalized indexes on one transaction."""

        tests = list(result.get("tests") or [])
        coverage = result.get("coverage") or []
        if isinstance(coverage, dict):
            coverage = coverage.get("metrics") or [
                {"metric": key, **(value if isinstance(value, dict) else {"percent": value})}
                for key, value in coverage.items()
                if key not in {"overall", "overall_pct"}
            ]
        properties = list(result.get("properties") or [])
        artifacts = list(result.get("artifacts") or [])
        issues = list(result.get("issues") or [])
        connection.execute(
            "UPDATE runs SET result_json=? WHERE run_id=?",
            (_json_dump(result), run_id),
        )
        for table in (
            "test_results", "coverage_metrics", "formal_properties", "artifacts", "issues"
        ):
            connection.execute(f"DELETE FROM {table} WHERE run_id=?", (run_id,))
        for item in tests:
            connection.execute(
                """
                INSERT INTO test_results(
                    run_id,test_name,suite,seed,status,duration_s,details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    str(item.get("name") or item.get("test_name") or "unknown"),
                    item.get("suite"), item.get("seed"),
                    str(item.get("verification_status") or item.get("status") or "unknown"),
                    item.get("duration_seconds", item.get("duration_s")),
                    _json_dump(item),
                ),
            )
        for item in coverage:
            connection.execute(
                """
                INSERT INTO coverage_metrics(
                    run_id,metric,covered,total,percent,scope,details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, str(item.get("metric") or item.get("name") or "unknown"),
                    item.get("covered"), item.get("total"),
                    item.get("percent", item.get("pct")), item.get("scope"),
                    _json_dump(item),
                ),
            )
        for item in properties:
            connection.execute(
                """
                INSERT INTO formal_properties(
                    run_id,property_name,status,engine,depth,duration_s,details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    str(item.get("name") or item.get("property_name") or "unknown"),
                    str(item.get("status") or "inconclusive"), item.get("engine"),
                    item.get("proof_depth", item.get("depth")),
                    item.get("runtime_seconds", item.get("duration_s")),
                    _json_dump(item),
                ),
            )
        for item in artifacts:
            connection.execute(
                """
                INSERT INTO artifacts(
                    artifact_id,run_id,kind,name,path,media_type,size_bytes,
                    sha256,metadata_json,created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(item.get("artifact_id") or item.get("id") or uuid.uuid4().hex), run_id,
                    str(item.get("kind") or "other"),
                    str(item.get("name") or os.path.basename(str(item.get("path") or "artifact"))),
                    str(item.get("path") or ""), item.get("media_type"),
                    int(item.get("size_bytes") or 0), str(item.get("sha256") or ""),
                    _json_dump(item.get("metadata") or {}), _utc_timestamp(),
                ),
            )
        for item in issues:
            connection.execute(
                """
                INSERT INTO issues(
                    issue_id,run_id,severity,title,status,details_json,created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(item.get("issue_id") or uuid.uuid4().hex), run_id,
                    str(item.get("severity") or "error"),
                    str(item.get("title") or "Verification issue"),
                    str(item.get("status") or "open"), _json_dump(item), _utc_timestamp(),
                ),
            )

    def save_run_result(self, run_id: str, result: Dict[str, Any]) -> None:
        """Atomically replace normalized run results and query indexes."""

        with self._lock, self._connection() as connection:
            self._replace_run_result(connection, run_id, result)
        self.append_event(run_id, "run.result", {"indexed": True})

    def commit_job_result(
        self,
        *,
        run_id: str,
        job_id: str,
        attempt_id: str,
        execution_status: str,
        verification_status: str,
        result: Dict[str, Any],
        manifest_path: Optional[str],
        normalized_result: Dict[str, Any],
    ) -> None:
        """Commit one terminal Job, Attempt, leaf stage, and aggregate evidence atomically."""

        now = _utc_timestamp()
        terminal_states = {"completed", "error", "timeout", "cancelled"}
        if execution_status not in terminal_states:
            raise ValueError("commit_job_result requires a terminal execution status")
        with self._event_condition, self._connection() as connection:
            job = connection.execute(
                "SELECT run_id,stage_id FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            attempt = connection.execute(
                "SELECT job_id FROM attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            if job is None or job["run_id"] != run_id:
                raise KeyError(f"job does not belong to run: {job_id}")
            if attempt is None or attempt["job_id"] != job_id:
                raise KeyError(f"attempt does not belong to job: {attempt_id}")
            connection.execute(
                """
                UPDATE jobs SET execution_status=?,verification_status=?,result_json=?,
                    started_at=COALESCE(started_at,created_at),finished_at=? WHERE job_id=?
                """,
                (
                    execution_status,
                    verification_status,
                    _json_dump(result),
                    now,
                    job_id,
                ),
            )
            connection.execute(
                """
                UPDATE attempts SET execution_status=?,result_json=?,manifest_path=?,finished_at=?
                WHERE attempt_id=?
                """,
                (execution_status, _json_dump(result), manifest_path, now, attempt_id),
            )
            stage_id = job["stage_id"]
            if stage_id:
                stage = connection.execute(
                    "SELECT verification_status FROM stages WHERE run_id=? AND stage_id=?",
                    (run_id, stage_id),
                ).fetchone()
                if stage is not None:
                    priority = {"unknown": 0, "passed": 1, "inconclusive": 2, "failed": 3}
                    observed = str(stage["verification_status"])
                    stage_verification = (
                        verification_status
                        if priority.get(verification_status, -1) >= priority.get(observed, -1)
                        else observed
                    )
                    connection.execute(
                        """
                        UPDATE stages SET execution_status=?,verification_status=?
                        WHERE run_id=? AND stage_id=?
                        """,
                        (execution_status, stage_verification, run_id, stage_id),
                    )
            self._replace_run_result(connection, run_id, normalized_result)
            cursor = connection.execute(
                """
                INSERT INTO events(run_id,event_type,payload_json,created_at)
                VALUES (?, 'job.persisted', ?, ?)
                """,
                (
                    run_id,
                    _json_dump(
                        {
                            "job_id": job_id,
                            "attempt_id": attempt_id,
                            "execution_status": execution_status,
                            "verification_status": verification_status,
                            "manifest_path": manifest_path,
                        }
                    ),
                    now,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("failed to append atomic job persistence event")
            self._event_condition.notify_all()

    def invalidate_job_evidence(
        self,
        *,
        run_id: str,
        job_id: str,
        diagnostic: Dict[str, Any],
    ) -> None:
        """Reject stale terminal evidence while preserving its immutable Attempt record."""

        result = {"diagnostics": [diagnostic], "retryable": True}
        now = _utc_timestamp()
        with self._event_condition, self._connection() as connection:
            job = connection.execute(
                "SELECT run_id,stage_id FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if job is None or job["run_id"] != run_id:
                raise KeyError(f"job does not belong to run: {job_id}")
            connection.execute(
                """
                UPDATE jobs SET execution_status='error',verification_status='inconclusive',
                    result_json=?,finished_at=? WHERE job_id=?
                """,
                (_json_dump(result), now, job_id),
            )
            if job["stage_id"]:
                connection.execute(
                    """
                    UPDATE stages SET execution_status='error',verification_status='inconclusive'
                    WHERE run_id=? AND stage_id=?
                    """,
                    (run_id, job["stage_id"]),
                )
            connection.execute(
                """
                INSERT INTO events(run_id,event_type,payload_json,created_at)
                VALUES (?, 'job.evidence_invalid', ?, ?)
                """,
                (run_id, _json_dump({"job_id": job_id, **diagnostic}), now),
            )
            self._event_condition.notify_all()

    def list_runs(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return runs, optionally filtered by project."""

        query = "SELECT * FROM runs"
        params: tuple[Any, ...] = ()
        if project_id:
            query += " WHERE project_id=?"
            params = (project_id,)
        query += " ORDER BY created_at DESC"
        with self._lock, self._connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._run_public(dict(row)) for row in rows]

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Return one run with decoded request, result, and diagnostics."""

        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
        return self._run_public(dict(row)) if row is not None else None

    @staticmethod
    def _run_public(row: Dict[str, Any]) -> Dict[str, Any]:
        """Decode JSON columns of a stored run."""

        row["request"] = _json_load(row.pop("request_json", None), {})
        row["result"] = _json_load(row.pop("result_json", None), None)
        row["diagnostic"] = _json_load(row.pop("diagnostic_json", None), None)
        return row

    def append_event(self, run_id: str, event_type: str, payload: Dict[str, Any]) -> int:
        """Append a sequenced run event and wake SSE subscribers."""

        with self._event_condition, self._connection() as connection:
            cursor = connection.execute(
                "INSERT INTO events(run_id,event_type,payload_json,created_at) VALUES (?, ?, ?, ?)",
                (run_id, event_type, _json_dump(payload), _utc_timestamp()),
            )
            sequence = int(cursor.lastrowid)
            self._event_condition.notify_all()
        return sequence

    def list_events(self, run_id: str, after: int = 0, limit: int = 500) -> List[Dict[str, Any]]:
        """Return ordered events newer than a global sequence cursor."""

        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT sequence,event_type,payload_json,created_at FROM events
                WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT ?
                """,
                (run_id, max(0, int(after)), max(1, min(int(limit), 5000))),
            ).fetchall()
        return [
            {
                "sequence": row["sequence"],
                "event_type": row["event_type"],
                "payload": _json_load(row["payload_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def wait_for_events(self, run_id: str, after: int, timeout: float = 15.0) -> List[Dict[str, Any]]:
        """Wait for at least one event after ``after`` or until timeout."""

        events = self.list_events(run_id, after)
        if events:
            return events
        with self._event_condition:
            self._event_condition.wait(timeout=max(0.0, timeout))
        return self.list_events(run_id, after)

    def list_result_rows(self, run_id: str, category: str) -> List[Dict[str, Any]]:
        """Return decoded normalized rows for one supported result category."""

        table_map = {
            "tests": ("test_results", "details_json", "id"),
            "coverage": ("coverage_metrics", "details_json", "id"),
            "properties": ("formal_properties", "details_json", "id"),
            "issues": ("issues", "details_json", "created_at"),
        }
        if category not in table_map:
            raise ValueError(f"Unsupported result category: {category}")
        table, json_column, order_column = table_map[category]
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM {table} WHERE run_id=? ORDER BY {order_column}", (run_id,)
            ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            details = _json_load(data.pop(json_column, None), {})
            details.setdefault("record_id", data.pop("id", data.get("issue_id")))
            result.append({**data, **details})
        return result

    def list_artifacts(self, run_id: str) -> List[Dict[str, Any]]:
        """Return indexed artifacts for a run without reading file content."""

        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM artifacts WHERE run_id=? ORDER BY created_at", (run_id,)
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["metadata"] = _json_load(item.pop("metadata_json", None), {})
            result.append(item)
        return result

    def get_artifact(self, artifact_id: str) -> Optional[Dict[str, Any]]:
        """Return one indexed artifact by identifier."""

        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["metadata"] = _json_load(item.pop("metadata_json", None), {})
        return item

    def add_stage_action(self, run_id: str, stage_id: str, action: str, note: str = "") -> None:
        """Persist a human stage decision for recovery and audit."""

        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT INTO stage_actions(run_id,stage_id,action,note,created_at) VALUES (?, ?, ?, ?, ?)",
                (run_id, stage_id, action, note, _utc_timestamp()),
            )
            connection.execute(
                """
                INSERT INTO human_approvals(
                    approval_id,run_id,stage_id,decision,note,created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (uuid.uuid4().hex, run_id, stage_id, action, note, _utc_timestamp()),
            )
        self.append_event(run_id, f"stage.{action}", {"stage_id": stage_id, "note": note})
        self.add_audit_event(f"stage.{action}", "run", run_id, {"stage_id": stage_id})

    def update_stage_execution(
        self,
        run_id: str,
        stage_id: str,
        execution_status: str,
        verification_status: Optional[str] = None,
    ) -> bool:
        """Advance stage execution while monotonically aggregating conclusions."""

        priority = {"unknown": 0, "passed": 1, "inconclusive": 2, "failed": 3}
        with self._lock, self._connection() as connection:
            current = connection.execute(
                "SELECT verification_status FROM stages WHERE run_id=? AND stage_id=?",
                (run_id, stage_id),
            ).fetchone()
            if current is None:
                return False
            observed = str(current["verification_status"])
            proposed = verification_status or observed
            verification = (
                proposed
                if priority.get(proposed, -1) >= priority.get(observed, -1)
                else observed
            )
            cursor = connection.execute(
                """
                UPDATE stages SET execution_status=?,verification_status=?
                WHERE run_id=? AND stage_id=?
                """,
                (execution_status, verification, run_id, stage_id),
            )
        return bool(cursor.rowcount)

    def update_stage_approval(
        self,
        run_id: str,
        stage_id: str,
        approval_status: str,
    ) -> bool:
        """Persist a human gate decision independently from verification status."""

        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                "UPDATE stages SET approval_status=? WHERE run_id=? AND stage_id=?",
                (approval_status, run_id, stage_id),
            )
        return bool(cursor.rowcount)

    def activate_stage(self, run_id: str, stage_name: str) -> Optional[str]:
        """Enable one deferred stage by name and clear its catalog-only reason."""

        with self._lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT stage_id FROM stages WHERE run_id=? AND name=?
                ORDER BY ordinal LIMIT 1
                """,
                (run_id, stage_name),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """
                UPDATE stages SET enabled=1,disabled_reason=NULL,execution_status='queued',
                    verification_status='unknown' WHERE run_id=? AND stage_id=?
                """,
                (run_id, row["stage_id"]),
            )
            return str(row["stage_id"])

    def replace_stage_state(
        self,
        run_id: str,
        stage_id: str,
        execution_status: str,
        verification_status: str,
    ) -> bool:
        """Replace a derived stage state when signed evidence is revalidated."""

        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE stages SET execution_status=?,verification_status=?
                WHERE run_id=? AND stage_id=?
                """,
                (execution_status, verification_status, run_id, stage_id),
            )
        return bool(cursor.rowcount)

    def create_counterexample_replay(
        self,
        *,
        source_run_id: str,
        property_name: str,
        counterexample_artifact_id: str,
        target_run_id: str,
        methodology: str,
        request: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Persist the immutable link from formal evidence to one dynamic run."""

        replay_id = uuid.uuid4().hex
        now = _utc_timestamp()
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO counterexample_replays(
                    replay_id,source_run_id,property_name,counterexample_artifact_id,
                    target_run_id,methodology,status,request_json,evidence_json,
                    created_at,updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, '{}', ?, ?)
                """,
                (
                    replay_id,
                    source_run_id,
                    property_name,
                    counterexample_artifact_id,
                    target_run_id,
                    methodology,
                    _json_dump(request),
                    now,
                    now,
                ),
            )
        replay = self.get_counterexample_replay(replay_id)
        assert replay is not None
        return replay

    def get_counterexample_replay(self, replay_id: str) -> Optional[Dict[str, Any]]:
        """Return one decoded counterexample replay relation."""

        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM counterexample_replays WHERE replay_id=?", (replay_id,)
            ).fetchone()
        return self._counterexample_replay_public(dict(row)) if row is not None else None

    def list_counterexample_replays(self, source_run_id: str) -> List[Dict[str, Any]]:
        """List dynamic replay attempts for one formal source run."""

        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM counterexample_replays WHERE source_run_id=?
                ORDER BY created_at
                """,
                (source_run_id,),
            ).fetchall()
        return [self._counterexample_replay_public(dict(row)) for row in rows]

    def replay_source_runs_for_target(self, target_run_id: str) -> List[str]:
        """Return parent formal runs that depend on one dynamic child run."""

        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT source_run_id FROM counterexample_replays
                WHERE target_run_id=?
                """,
                (target_run_id,),
            ).fetchall()
        return [str(row["source_run_id"]) for row in rows]

    def source_runs_with_counterexample_replays(self) -> List[str]:
        """Return every formal run requiring replay reconciliation after restart."""

        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT DISTINCT source_run_id FROM counterexample_replays"
            ).fetchall()
        return [str(row["source_run_id"]) for row in rows]

    def update_counterexample_replay(
        self,
        replay_id: str,
        *,
        status: str,
        evidence: Dict[str, Any],
    ) -> bool:
        """Persist a replay conclusion derived only from current signed evidence."""

        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE counterexample_replays SET status=?,evidence_json=?,updated_at=?
                WHERE replay_id=?
                """,
                (status, _json_dump(evidence), _utc_timestamp(), replay_id),
            )
        return bool(cursor.rowcount)

    @staticmethod
    def _counterexample_replay_public(row: Dict[str, Any]) -> Dict[str, Any]:
        """Decode structured replay request and evidence columns."""

        row["request"] = _json_load(row.pop("request_json", None), {})
        row["evidence"] = _json_load(row.pop("evidence_json", None), {})
        return row

    def recover_interrupted_runs(self) -> int:
        """Mark orphaned queued/running work after process restart as recoverable errors."""

        diagnostic = {
            "error_code": "service_restarted",
            "error": "The platform process restarted while the run was active.",
            "next_action": "Retry the run from its persisted configuration.",
            "retryable": True,
        }
        recovery_result = {"diagnostics": [diagnostic], "retryable": True}
        now = _utc_timestamp()
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT run_id FROM runs WHERE execution_status IN ('queued','running') AND adapter != 'campaign'"
            ).fetchall()
            for row in rows:
                connection.execute(
                    """
                    UPDATE runs SET execution_status='error',verification_status='inconclusive',
                        diagnostic_json=?,finished_at=? WHERE run_id=?
                    """,
                    (_json_dump(diagnostic), now, row["run_id"]),
                )
                connection.execute(
                    """
                    UPDATE jobs SET execution_status='error',verification_status='inconclusive',
                        result_json=?,finished_at=?
                    WHERE run_id=? AND execution_status IN ('queued','running')
                    """,
                    (_json_dump(recovery_result), now, row["run_id"]),
                )
                connection.execute(
                    """
                    UPDATE attempts SET execution_status='error',result_json=?,finished_at=?
                    WHERE job_id IN (SELECT job_id FROM jobs WHERE run_id=?)
                        AND execution_status IN ('queued','running')
                    """,
                    (_json_dump(recovery_result), now, row["run_id"]),
                )
                connection.execute(
                    """
                    UPDATE stages SET
                        execution_status=CASE
                            WHEN execution_status='running' THEN 'error'
                            ELSE 'cancelled'
                        END,
                        verification_status=CASE
                            WHEN verification_status='failed' THEN 'failed'
                            ELSE 'inconclusive'
                        END
                    WHERE run_id=? AND enabled=1
                        AND execution_status IN ('queued','running')
                    """,
                    (row["run_id"],),
                )
        for row in rows:
            self.append_event(row["run_id"], "run.recovered", diagnostic)
        return len(rows)

    def save_toolchain_probe(self, profile_id: str, status: str, details: Dict[str, Any]) -> None:
        """Upsert a redacted toolchain health snapshot."""

        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO toolchain_probes(profile_id,status,details_json,probed_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(profile_id) DO UPDATE SET
                    status=excluded.status,
                    details_json=excluded.details_json,
                    probed_at=excluded.probed_at
                """,
                (profile_id, status, _json_dump(details), _utc_timestamp()),
            )

    def list_toolchain_probes(self) -> Dict[str, Dict[str, Any]]:
        """Return the latest health snapshot for each toolchain profile."""

        with self._lock, self._connection() as connection:
            rows = connection.execute("SELECT * FROM toolchain_probes").fetchall()
        return {
            row["profile_id"]: {
                "status": row["status"],
                "details": _json_load(row["details_json"], {}),
                "probed_at": row["probed_at"],
            }
            for row in rows
        }

    def add_audit_event(
        self,
        action: str,
        subject_type: str,
        subject_id: str,
        details: Dict[str, Any],
    ) -> None:
        """Append a non-secret administrative audit event."""

        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO audit_events(action,subject_type,subject_id,details_json,created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (action, subject_type, subject_id, _json_dump(details), _utc_timestamp()),
            )

    def overview(self) -> Dict[str, Any]:
        """Return aggregate counters for the platform overview page."""

        with self._lock, self._connection() as connection:
            project_count = connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
            run_count = connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            status_rows = connection.execute(
                "SELECT execution_status,COUNT(*) AS count FROM runs GROUP BY execution_status"
            ).fetchall()
            verification_rows = connection.execute(
                "SELECT verification_status,COUNT(*) AS count FROM runs GROUP BY verification_status"
            ).fetchall()
        return {
            "projects": project_count,
            "runs": run_count,
            "execution": {row["execution_status"]: row["count"] for row in status_rows},
            "verification": {
                row["verification_status"]: row["count"] for row in verification_rows
            },
        }
