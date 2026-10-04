"""Pytest adapter for executing generated Picker bindings through UnityTest."""

from __future__ import annotations

from pathlib import Path

from .base import ToolchainAdapter
from ..models import CommandSpec, RunRequest


class PytestAdapter(ToolchainAdapter):
    """Construct one isolated, JUnit-producing UnityTest pytest invocation."""

    name = "pytest"
    required_tools = ("python",)

    def build_test_request(
        self,
        *,
        workspace: Path,
        output_dir: Path,
        test_path: Path,
        picker_output_dir: Path,
        dut_package: Path,
        seed: int,
        suite: str | None = None,
        waveform: str = "none",
        dut_name: str | None = None,
        run_id: str | None = None,
        timeout_seconds: float = 3600,
    ) -> RunRequest:
        """Build an argv-only pytest request tied to immutable tests and bindings."""

        if (
            test_path.is_absolute()
            or not test_path.parts
            or any(part in {"", ".", ".."} or part.startswith("-") for part in test_path.parts)
        ):
            raise ValueError("test_path must be a normalized workspace-relative path")
        for label, value in (
            ("picker_output_dir", picker_output_dir),
            ("dut_package", dut_package),
        ):
            if (
                value.is_absolute()
                or not value.parts
                or any(part in {"", ".", ".."} or part.startswith("-") for part in value.parts)
            ):
                raise ValueError(f"{label} must be a normalized workspace-relative path")
        if seed <= 0:
            raise ValueError("UnityTest seed must be positive")
        if waveform not in {"none", "vcd", "fst", "fsdb"}:
            raise ValueError("UnityTest waveform must be one of: none, vcd, fst, fsdb")
        report = Path("pytest-report.xml")
        artifacts = [report]
        if waveform != "none":
            if not dut_name:
                raise ValueError("dut_name is required when a UnityTest waveform is enabled")
            artifacts.append(Path(f"{dut_name}.{waveform}"))
        values = {
            "workspace": workspace,
            "output_dir": output_dir,
            "command": CommandSpec(
                argv=[
                    "python",
                    "-m",
                    "pytest",
                    "-p",
                    "no:cacheprovider",
                    "-q",
                    "-s",
                    "--tb=short",
                    f"--junitxml={{SESSION_DIR}}/{report.as_posix()}",
                    f"{{WORKSPACE}}/{test_path.as_posix()}",
                ],
                tool="python",
                cwd=Path("{SESSION_DIR}"),
                env={
                    "PYTHONHASHSEED": str(seed),
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONPATH": f"{{WORKSPACE}}/{picker_output_dir.as_posix()}",
                    "UCAGENT_TEST_SEED": str(seed),
                },
                timeout_seconds=timeout_seconds,
            ),
            "input_paths": [test_path, dut_package],
            "artifact_paths": artifacts,
            "result_paths": [report],
            "parser": "pytest",
            "test_name": test_path.as_posix(),
            "suite": suite,
            "seed": seed,
            "metadata": {
                "adapter": self.name,
                "phase": "unitytest",
                "picker_output_dir": picker_output_dir.as_posix(),
                "seed_environment": "UCAGENT_TEST_SEED",
                "waveform": waveform,
            },
        }
        if run_id is not None:
            values["run_id"] = run_id
        return RunRequest(**values)
