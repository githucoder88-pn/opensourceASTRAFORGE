"""Every shipped example must actually run. Reproducibility is a claim we test.

If an example breaks, users discover the project by watching it fail, so these
run the real plans through the real engine.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from astraforge.core.approvals import AutoApproveGate
from astraforge.core.config import Config
from astraforge.execution.engine import Engine, RunResult
from astraforge.models.core import Goal
from astraforge.planning.static import StaticPlanner
from astraforge.providers.echo import EchoProvider
from astraforge.storage.run_store import RunStore
from astraforge.tools import default_registry
from astraforge.verification import default_verifiers

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _run_example(name: str, goal_text: str, tmp_path: Path) -> RunResult:
    config = Config(storage_dir=str(tmp_path / ".astraforge"))
    provider = EchoProvider()
    engine = Engine(
        config=config,
        planner=StaticPlanner(path=EXAMPLES / name / "plan.yaml"),
        tools=default_registry(provider),
        verifiers=default_verifiers(),
        provider=provider,
        store=RunStore(config.storage_dir),
        approval_gate=AutoApproveGate(),
    )
    return engine.run(Goal(description=goal_text))


@pytest.mark.slow
class TestSoftwareEngineeringExample:
    def test_completes_all_tasks(self, tmp_path: Path) -> None:
        result = _run_example(
            "software_engineering", "Fix the failing statistics module", tmp_path
        )
        assert result.ok, [t.attempts[-1].error for t in result.tasks if not t.attempts[-1].ok]
        assert len(result.tasks) == 6

    def test_the_bug_is_really_fixed(self, tmp_path: Path) -> None:
        result = _run_example("software_engineering", "Fix the bug", tmp_path)
        source = result.workspace.read_text("stats.py")
        assert "ordered[middle - 1] + ordered[middle]" in source

        # Import the produced module and check the actual behaviour.
        namespace: dict[str, object] = {}
        exec(compile(source, "stats.py", "exec"), namespace)  # noqa: S102
        median = namespace["median"]
        assert median([1, 2, 3, 4]) == 2.5  # type: ignore[operator]
        assert median([5, 1, 3]) == 3  # type: ignore[operator]

    def test_the_failure_was_genuinely_reproduced_first(self, tmp_path: Path) -> None:
        """The demo must prove the bug existed, not just that tests pass now."""
        result = _run_example("software_engineering", "Fix the bug", tmp_path)
        reproduce = next(t for t in result.tasks if t.task_id == "task_reproduce_failure")
        evidence = " ".join(
            e.summary
            for a in reproduce.attempts
            for v in a.verifications
            for e in v.evidence
        )
        assert "FAILED (failures=1)" in evidence
        assert "Ran 3 tests" in evidence
        assert "2 != 2.5" in evidence  # the actual wrong value the bug produced


@pytest.mark.slow
class TestDataAnalysisExample:
    def test_finds_the_planted_anomalies(self, tmp_path: Path) -> None:
        result = _run_example("data_analysis", "Analyse the sensor readings", tmp_path)
        assert result.ok
        findings = json.loads(result.workspace.read_text("findings.json"))
        assert findings["anomaly_count"] == 2
        temperatures = {a["temperature_c"] for a in findings["anomalies"]}
        assert temperatures == {91.7, -40.5}

    def test_indirect_outputs_are_captured_as_artifacts(self, tmp_path: Path) -> None:
        """Files written by a subprocess must still land in the evidence trail."""
        result = _run_example("data_analysis", "Analyse the readings", tmp_path)
        paths = {a.path for a in result.run.artifacts}
        assert {"report.md", "findings.json", "chart.txt"} <= paths
        assert all(len(a.sha256) == 64 for a in result.run.artifacts)


@pytest.mark.slow
class TestResearchExample:
    def test_completes_with_all_claims_cited(self, tmp_path: Path) -> None:
        result = _run_example("research", "Summarise verification approaches", tmp_path)
        assert result.ok
        assert "[S1]" in result.workspace.read_text("synthesis.md")

    def test_the_citation_checker_actually_rejects_uncited_claims(
        self, tmp_path: Path
    ) -> None:
        """A verifier that cannot fail is worthless; prove this one can."""
        import subprocess
        import sys

        result = _run_example("research", "Summarise verification approaches", tmp_path)
        synthesis = result.workspace.resolve("synthesis.md")
        synthesis.write_text(
            synthesis.read_text() + "\n- A fabricated claim with no source.\n"
        )
        proc = subprocess.run(
            [sys.executable, "check_citations.py"],
            cwd=result.workspace.root,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 1
        assert "UNCITED" in proc.stdout

    def test_the_checker_rejects_fabricated_source_ids(self, tmp_path: Path) -> None:
        import subprocess
        import sys

        result = _run_example("research", "Summarise verification approaches", tmp_path)
        synthesis = result.workspace.resolve("synthesis.md")
        synthesis.write_text(
            synthesis.read_text() + "\n- A claim citing a source that does not exist [S99].\n"
        )
        proc = subprocess.run(
            [sys.executable, "check_citations.py"],
            cwd=result.workspace.root,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 1
        assert "UNKNOWN SOURCE: S99" in proc.stdout


def test_examples_need_no_optional_dependencies() -> None:
    """Examples must run from a bare `pip install astraforge`.

    Regression guard: the flagship demo originally invoked pytest, which is a
    dev-only extra. It passed in the development environment and failed on a
    clean install. Example plans may only rely on the standard library.
    """
    import yaml

    forbidden = ("pytest", "numpy", "pandas", "matplotlib", "requests", "scipy")
    for plan_path in sorted(EXAMPLES.glob("*/plan.yaml")):
        text = yaml.safe_dump(yaml.safe_load(plan_path.read_text(encoding="utf-8")))
        commands = [
            line
            for line in text.splitlines()
            if "command" in line or "python" in line
        ]
        for package in forbidden:
            offending = [line for line in commands if package in line]
            assert not offending, (
                f"{plan_path.relative_to(EXAMPLES.parent)} invokes {package!r}, "
                f"which is not a runtime dependency: {offending}"
            )


def test_every_example_directory_ships_a_readme() -> None:
    for directory in sorted(p for p in EXAMPLES.iterdir() if p.is_dir()):
        assert (directory / "README.md").exists(), f"{directory.name} needs a README.md"
