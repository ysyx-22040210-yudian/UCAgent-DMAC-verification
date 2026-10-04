"""Human-operated formal sessions using the original StageManager and Checker gates."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import threading

import yaml

from ucagent.version import __version__
from ucagent.eda.sby_guided import publish_text
from ucagent.stage import StageManager
from ucagent.tools.fileops import ReadTextFile
from ucagent.util.config import get_config, save_runtime_config
from ucagent.util.functions import load_ucagent_info, render_template_dir


def digest(value):
    """Fingerprint a JSON contract without depending on dictionary insertion order."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class FormalSession:
    """Host the existing stage lifecycle without constructing an LLM or command shell."""

    def __init__(self, workspace, options, checkpoint=None):
        """Load a fixed formal workflow and restore only a server-verified checkpoint."""
        self.workspace = str(Path(workspace).resolve())
        self.dut_name = options["dut"]
        self.options = options
        self.cancelled = threading.Event()
        self.backend = self
        self._need_human = False
        self._signature = None
        overrides = [
            {"runtime_options.formal_engine": options["engine"]},
            {"runtime_options.formal_toolchain": options["toolchain"]},
            {"skill.use_skill": False},
            {"vmanager.llm_suggestion.check_pass_refinement.enable": False},
            {"vmanager.llm_suggestion.check_fail_refinement.enable": False},
        ]
        if (Path(self.workspace) / ".ucagent/setting.yaml").exists():
            raise ValueError("Imported workspace settings cannot be executed in a managed formal session.")
        formal_config = Path(__file__).parents[1] / "lang/zh/config/formal.yaml"
        cfg = get_config(str(formal_config), overrides, workspace=self.workspace)
        cfg.un_freeze()
        # Keep optional branches in the configuration but let StageManager apply
        # its normal ignore semantics. The view projects these absent nodes too.
        for stage in cfg.stage:
            if stage.name == "counterexample_python_testgen":
                stage.ignore = not options["cex_replay"]
            if stage.name == "static_bug_validation":
                stage.ignore = not options["static_review"]
            if options["human_review"]:
                stage.need_human_check = True
                for child in stage.get_value("stage", []):
                    child.need_human_check = True
        cfg.freeze()
        args = {"DUT": self.dut_name, "OUT": "formal_out", "WORKSPACE": self.workspace, "Version": __version__}
        cfg.update_template(args)
        cfg.update_template(cfg.template_overwrite.as_dict())
        cfg.un_freeze()
        cfg._temp_cfg = args
        cfg.freeze()
        self.cfg = cfg
        self.contract_hash = digest({"stage": [s.as_dict() for s in cfg.stage], "options": options})
        if checkpoint and checkpoint["contract_hash"] != self.contract_hash:
            raise ValueError("Workflow contract changed; create a new session instead of reusing old progress.")
        cfg.un_freeze()
        # Resolve only immutable imported RTL. A missing glob must not fall back
        # to matching staged proof copies or hidden history with regex search.
        input_root = Path(self.workspace) / self.dut_name
        rtl_references = [path.relative_to(self.workspace).as_posix()
                          for path in sorted(input_root.rglob("*"))
                          if path.is_file() and path.suffix.lower() in {".v", ".sv"}]
        source_patterns = {self.dut_name + "/*.sv", self.dut_name + "/*.v"}
        for stage in cfg.stage:
            for node in (stage, *stage.get_value("stage", [])):
                references = node.get_value("reference_files", [])
                if any(item in source_patterns for item in references):
                    node.reference_files = [item for item in references if item not in source_patterns] + rtl_references
        cfg.freeze()
        root = Path(self.workspace)
        resources = Path(__file__).parents[1] / "lang" / cfg.lang
        if checkpoint is None:
            shutil.copytree(resources / "doc" / cfg.guide_doc.source, root / "Guide_Doc")
            render_template_dir(self.workspace, str(resources / "template" / cfg.template), {"DUT": self.dut_name, "Version": __version__})
            (root / cfg.template).rename(root / "formal_out")
        save_runtime_config(self.workspace, cfg)
        self.reader = ReadTextFile(self.workspace, max_read_size=400000)
        saved = deepcopy(checkpoint["info"]) if checkpoint else {}
        self.stage_manager = StageManager(self.workspace, cfg, self, self.reader, saved,
                                          force_stage_index=saved.get("stage_index", 0),
                                          tool_inspect_file=[self.reader])
        self.stage_manager.init_stage()
        # Original restore does not restore human approvals. Carry only approvals
        # from the authenticated server checkpoint, never from an editable file.
        for index, stage in enumerate(self.stage_manager.stages):
            old = saved.get("stages_info", {}).get(str(index), {})
            stage._hum_check_passed = old.get("last_human_check_result")
            stage._hum_check_msg = old.get("last_human_check_msg", "")

    def is_break(self):
        """Let original checkers observe an explicit operation cancellation."""
        return self.cancelled.is_set()

    def is_exit(self):
        """Keep session shutdown separate from verification completion."""
        return False

    def get_stat_info(self):
        """Supply only non-secret identity data to the native stage checkpoint."""
        return {"dut_name": self.dut_name}

    def on_stage_complete(self, stage):
        """Honor the native backend callback without claiming AI authoring occurred."""

    def checkpoint(self):
        """Persist and return the native checkpoint for server-side authentication."""
        self.stage_manager.save_stage_info()
        hashes = {}
        output = Path(self.workspace) / "formal_out"
        candidates = [output / ".formal_records.yaml", *output.glob("*.md")]
        tests = output / "tests"
        if tests.is_dir():
            candidates.extend(path for path in tests.iterdir() if path.suffix in {".py", ".sv", ".v", ".tcl"})
        for path in candidates:
            relative = path.relative_to(self.workspace).as_posix()
            if path.is_file() and self.editable(relative):
                hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        return {"contract_hash": self.contract_hash, "info": load_ucagent_info(self.workspace), "authoring_hashes": hashes}

    def projection(self):
        """Project all eleven stages and nested branches from the active manager."""
        manager = self.stage_manager
        live = {stage.name: (index, stage) for index, stage in enumerate(manager.stages)}
        def node(config, parent_disabled=False):
            """Join one configured node with its actual stage instance, if enabled."""
            ignored = parent_disabled or config.get_value("ignore", False) or config.get_value("skip", False)
            index, stage = live.get(config.name, (None, None))
            details = stage.detail() if stage else {"task": {"description": config.task, "output_files": config.get_value("output_files", [])}}
            return {"id": config.name, "name": config.name, "index": index,
                    "description": stage.description() if stage else config.desc, "enabled": not ignored,
                    "disabled_reason": "Not selected when this session was created." if ignored else "",
                    "status": "disabled" if ignored else "completed" if stage and stage.is_completed() else "running" if index == manager.stage_index else "queued",
                    "current": index == manager.stage_index, "details": details,
                    "journal": stage.meta_get_journal() if stage else None,
                    "children": [node(child, ignored) for child in config.get_value("stage", [])]}
        return {"stages": [node(config) for config in self.cfg.stage],
                "current_index": manager.stage_index, "all_completed": manager.all_completed,
                "last_check": manager.last_check_info,
                "next_action": "Review final evidence." if manager.all_completed else "Read stage inputs, edit required artifacts, save a journal, then Check / Complete."}

    def act(self, action, index, journal="", timeout=300):
        """Execute native Check/Complete or review; never advance by changing UI state."""
        manager = self.stage_manager
        if index != manager.stage_index:
            raise ValueError("The active stage changed; refresh before submitting an action.")
        stage = manager.get_current_stage()
        if stage is None:
            raise ValueError("The stage workflow has completed.")
        if action == "journal":
            return manager.set_current_stage_journal(journal)
        if action in {"approve", "reject"}:
            if not stage.is_hmcheck_needed():
                raise ValueError("This stage has no human-review gate.")
            return stage.do_hmcheck_pass(journal) if action == "approve" else stage.do_hmcheck_fail(journal)
        if action == "complete" and journal:
            manager.set_current_stage_journal(journal)
        if action == "check":
            return manager.check(timeout)
        if action == "complete":
            return manager.complete(timeout)
        raise ValueError("Unsupported stage action.")

    def cancel(self):
        """Request cancellation through the existing Checker process-tree contract."""
        self.cancelled.set()
        return self.stage_manager.tool_kill_check()

    def read(self, relative):
        """Read full bounded text and record actual reference access through ReadTextFile."""
        path = self.file_path(relative)
        if path.stat().st_size > 200000:
            raise ValueError("Text exceeds the editor limit; use the artifact download action.")
        text = path.read_text(encoding="utf-8")
        stage = self.stage_manager.get_current_stage()
        canonical = next((key for key in stage.reference_files if key.replace("\\", "/") == relative), relative) if stage else relative
        self.reader.invoke({"path": canonical})
        return {"path": relative, "content": text, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "editable": self.editable(relative)}

    def file_path(self, relative):
        """Reject absolute paths, traversal, hidden control files and symbolic links."""
        parts = Path(relative).parts
        if not parts or Path(relative).is_absolute() or "\\" in relative or ":" in relative or any(p in {".", ".."} for p in relative.split("/")):
            raise ValueError("Use a workspace-relative file path without traversal.")
        root = Path(self.workspace)
        path = root
        for part in parts:
            if part.startswith(".") and part != ".formal_records.yaml":
                raise ValueError("Session control files are not exposed by the editor.")
            path = path / part
            if path.is_symlink():
                raise ValueError("Symbolic links are not allowed in session file operations.")
        path.resolve().relative_to(root)
        return path

    def editable(self, relative):
        """Limit human edits to authoring files, never runtime evidence or imported inputs."""
        path = self.file_path(relative)
        parts = Path(relative).parts
        if path.name in {self.dut_name + "_checker.sv", self.dut_name + "_wrapper.sv", "formal.tcl"}:
            return False
        return (parts[0] == "formal_out" and
                (len(parts) == 2 and (path.name == ".formal_records.yaml" or path.suffix == ".md")
                 or len(parts) == 3 and parts[1] == "tests" and path.suffix in {".py", ".sv", ".v", ".tcl"}))

    def write(self, relative, content, previous_hash):
        """Apply a reviewed full-file edit with a compare-and-swap content guard."""
        path = self.file_path(relative)
        if not self.editable(relative):
            raise ValueError("Only authoring documents and test/harness sources can be edited; evidence is read-only.")
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        if actual != previous_hash:
            raise ValueError("The file changed after it was opened; reload and review the difference.")
        if len(content.encode("utf-8")) > 200000:
            raise ValueError("Text exceeds the editor limit.")
        manager = self.stage_manager
        rewind_to = manager.stage_index
        if path.name == ".formal_records.yaml":
            from ucagent.lang.zh.skills.formal.lib.models import FormalRecords
            before = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
            after = yaml.safe_load(content)
            FormalRecords.model_validate(after)
            if after.get("dut") != self.dut_name:
                raise ValueError("The record DUT must match the immutable session DUT.")
            if after.get("run_results") != before.get("run_results"):
                raise ValueError("run_results is tool-derived and cannot be edited.")
            owners = {"planning": "requirement_analysis_and_planning", "basic_info": "dut_function_understanding",
                      "spec": "functional_specification_analysis", "extra_config": "script_generation",
                      "analysis": "environment_debugging_iteration", "bugs": "formal_execution",
                      "summary": "verification_review_and_summary"}
            for key, name in owners.items():
                if before.get(key) != after.get(key):
                    owner = next(i for i, stage in enumerate(manager.stages) if stage.name == name)
                    if key == "spec":
                        # Compare each authoring layer independently. Adding FCs
                        # must not invalidate reviewed FG metadata; implementing
                        # a property must not reopen its unchanged CK requirement.
                        layers = []
                        for document in (before, after):
                            specification = FormalRecords.model_validate(document).spec
                            spec = specification.model_dump(mode="json") if specification else {
                                "parameters": None, "whitebox_signals": None, "function_groups": []}
                            groups = spec.pop("function_groups")
                            group_layer = {**spec, "function_groups": [
                                {k: v for k, v in group.items() if k != "functions"} for group in groups]}
                            function_layer, check_layer, property_layer = [], [], []
                            for group in groups:
                                function_layer.append((group["id"], [
                                    {k: v for k, v in function.items() if k != "check_points"}
                                    for function in group["functions"]]))
                                for function in group["functions"]:
                                    identity = (group["id"], function["id"])
                                    check_layer.append((identity, [
                                        {k: v for k, v in point.items()
                                         if k not in {"sva_body", "sby_guard", "sby_trigger"}}
                                        for point in function["check_points"]]))
                                    property_layer.append((identity, function["check_points"]))
                            layers.append((group_layer, function_layer, check_layer, property_layer))
                        stage_names = ("dut_function_grouping", "function_point_definition",
                                       "check_point_design", "property_generation")
                        owner = next((next(i for i, stage in enumerate(manager.stages) if stage.name == stage_name)
                                      for level, stage_name in enumerate(stage_names)
                                      if layers[0][level] != layers[1][level]), manager.stage_index)
                    # A review annotation does not change the generated environment.
                    if key == "extra_config":
                        old = deepcopy(before.get(key) or {})
                        new = deepcopy(after.get(key) or {})
                        old.get("sby", {}).pop("review", None)
                        new.get("sby", {}).pop("review", None)
                        if old == new:
                            owner = next(i for i, stage in enumerate(manager.stages) if stage.name == "environment_debugging_iteration")
                    rewind_to = min(rewind_to, owner)
        elif path.suffix in {".sv", ".v", ".tcl", ".py"}:
            rewind_to = min(rewind_to, next(i for i, stage in enumerate(manager.stages) if stage.name == "property_generation"))
        publish_text(Path(self.workspace), path, content)
        if rewind_to < manager.stage_index:
            self.rewind(rewind_to)
        stage = self.stage_manager.get_current_stage()
        if stage:
            stage.check_pass = False
            stage._hum_check_passed = None
            stage._hum_check_msg = ""
        self.stage_manager.last_check_info = {}
        return {"path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def rewind(self, index):
        """Reopen reached work and invalidate downstream completion without deleting artifacts."""
        manager = self.stage_manager
        if not 0 <= index <= manager.stage_index or index >= len(manager.stages):
            raise ValueError("Only a reached stage can be reopened.")
        saved = self.checkpoint()
        info = saved["info"]
        info.update(stage_index=index, all_completed=False, time_end=None, is_agent_exit=False)
        info["stages_info"] = {key: value for key, value in info["stages_info"].items() if int(key) < index}
        self.__init__(self.workspace, self.options, saved)
