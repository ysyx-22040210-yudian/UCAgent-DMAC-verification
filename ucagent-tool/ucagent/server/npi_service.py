"""Resolve NPI query artifact IDs to signed, immutable read-only evidence."""

from pathlib import Path
import re
import shutil
from uuid import uuid4

from ucagent.eda.manifest import sha256_file
from ucagent.eda.npi import NpiQuery, build_npi_request, query_wire_data, read_npi_result
from ucagent.eda.security import resolve_within
from .analysis_jobs import start_analysis_job


class NpiService:
    """Own bounded query preparation; only JobRunner starts NPI processes."""

    def __init__(self, runtime):
        """Use existing artifact provenance and the administrator-selected SDK bridge."""
        self.runtime = runtime
        with runtime.store._lock, runtime.store._connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS npi_queries(id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id), request_json TEXT NOT NULL)")

    def create(self, query: NpiQuery):
        """Resolve only signed artifact IDs and copy only our bridge and control input."""
        artifact, database = self.runtime.resolve_artifact(query.artifact_id)
        source_run = self.runtime.store.get_run(artifact["run_id"])
        self.runtime.verify_artifact_provenance(source_run["run_id"], query.artifact_id)
        profile_id = source_run["request"].get("toolchain")
        profile = self.runtime._profiles.get(profile_id)
        if profile is None:
            raise ValueError("The source run's explicit toolchain is unavailable")
        profile.require_tool("npi")
        profile.require_tool("perl")
        bridge = profile.npi_bridge
        if bridge is None or not bridge.is_absolute() or not bridge.is_file() or bridge.is_symlink():
            raise ValueError("Build and configure the host-owned NPI bridge before querying evidence")
        if not profile.npi_bridge_sha256 or sha256_file(bridge) != profile.npi_bridge_sha256:
            raise ValueError("NPI bridge does not match the administrator-approved build hash")
        if query.operation == "waveform" and (database.suffix.lower() != ".fsdb" or not database.is_file()):
            raise ValueError("Waveform queries require an actual signed FSDB file")
        if query.operation == "coverage" and (database.suffix.lower() != ".vdb" or not database.is_dir() or not query.selector):
            raise ValueError("Coverage queries require a signed VDB directory and an explicit test name")
        if query.operation not in {"waveform", "coverage"} and (database.suffix.lower() != ".daidir" or not database.is_dir()):
            raise ValueError("Design queries require a signed VCS KDB .daidir artifact")
        project = self.runtime.store.get_project(source_run["project_id"])
        workspace = Path(project["source_root"]).resolve(strict=True)
        # The vendor's old npi wrapper internally invokes Shell and Tcl. Its
        # executable and complete working path therefore need this stronger gate.
        for path in (str(workspace), profile.require_tool("npi")):
            if not re.fullmatch(r"/[A-Za-z0-9_./-]+", path):
                raise ValueError("This NPI launcher requires administrator-managed ASCII shell-safe host paths")
        identifier = uuid4().hex
        controls = resolve_within(workspace, ".ucagent/npi-controls/" + identifier, must_exist=False)
        controls.mkdir(parents=True)
        shutil.copyfile(bridge, controls / "bridge.so")
        if sha256_file(controls / "bridge.so") != profile.npi_bridge_sha256:
            raise ValueError("NPI bridge changed while staging")
        control_file = controls / "query.txt"
        control_file.write_text(query_wire_data(query, database), encoding="utf-8")
        request = build_npi_request(workspace=workspace, bridge=(controls / "bridge.so").relative_to(workspace),
            request_file=control_file.relative_to(workspace), database=database.relative_to(workspace),
            output_dir=Path(".ucagent/npi-runs") / identifier, query=query,
            npi_script=Path(profile.require_tool("npi")))
        result = start_analysis_job(self.runtime, project_id=source_run["project_id"], profile=profile,
                                    request=request, kind="npi")
        with self.runtime.store._lock, self.runtime.store._connection() as db:
            db.execute("INSERT INTO npi_queries VALUES(?,?,?)", (identifier, result["id"], query.model_dump_json()))
        return {"id": identifier, "run_id": result["id"], "execution_status": result["execution_status"]}

    def get(self, identifier):
        """Validate published query evidence before returning design, waveform or bin data."""
        with self.runtime.store._lock, self.runtime.store._connection() as db:
            row = db.execute("SELECT * FROM npi_queries WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise ValueError("NPI query not found")
        query = NpiQuery.model_validate_json(row["request_json"])
        run = self.runtime.store.get_run(row["run_id"])
        response = {"id": identifier, "run_id": run["run_id"], "execution_status": run["execution_status"],
                    "verification_status": "unknown", "result": None}
        if run["execution_status"] == "completed":
            for artifact in self.runtime.store.list_artifacts(run["run_id"]):
                if artifact["name"] == "result.json":
                    _, path, receipt = self.runtime.verify_artifact_provenance(run["run_id"], artifact["artifact_id"])
                    response["result"] = read_npi_result(path, query)
                    response["evidence"] = receipt
                    break
            if response["result"] is None:
                raise ValueError("Completed NPI query has no signed normalized result")
        return response
