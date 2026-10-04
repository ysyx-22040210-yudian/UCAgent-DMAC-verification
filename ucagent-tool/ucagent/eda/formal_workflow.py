"""Select engine-specific guidance without replacing the original formal stage tree."""

from copy import deepcopy
from pathlib import Path

import yaml


def select_formal_engine(config: dict) -> dict:
    """Specialize the canonical formal stages for the explicitly selected engine."""
    engine = config.get("runtime_options", {}).get("formal_engine")
    if engine is None or engine == "formalmc":
        return config
    if engine != "sby":
        raise ValueError("runtime_options.formal_engine must be formalmc or sby for the guided formal workflow")
    resource = Path(__file__).parents[1] / "lang/zh/config/formal_sby_overlay.yaml"
    overlay = yaml.safe_load(resource.read_text(encoding="utf-8"))
    result = deepcopy(config)
    stages = result.get("stage", [])
    if [stage["name"] for stage in stages] != list(overlay["stages"]):
        raise ValueError("SBY guided mode requires the complete canonical formal.yaml stage list")
    # Stage order, substage hierarchy and optional-branch conditions stay authoritative.
    for stage in stages:
        overrides = overlay["stages"][stage["name"]]
        stage.update(overrides)
        stage["skill_list"] = ["formal/sby"]
        stage["force_use_skill"] = False
        for child in stage.get("stage", []):
            child["skill_list"] = []
            child["task"] = [overlay["spec_task"]]
        stage["reference_files"] = ["{OUT}/.formal_records.yaml", "Guide_Doc/sby_workflow.md", "{DUT}/*.sv", "{DUT}/*.v"]
    result["mission"] = overlay["mission"]
    result["hooks"] = overlay["hooks"]
    result["guide_doc"] = {"path": "{GUIDE_DOC}", "source": "Formal_SBY_Doc", "enable": True}
    result["template"] = "formal_sby"
    result["template_overwrite"].update(LOG_FILE="sby_evidence.json", FANIN_REP="sby_coverage.json")
    # Full-SVA/COI-specific reviewer prompts must not leak into the native-Yosys path.
    result["vmanager"]["llm_suggestion"] = overlay["llm_suggestion"]
    return result
