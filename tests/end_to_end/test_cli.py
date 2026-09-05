"""End-to-end tests driving the real CLI, including the flagship demo.

These are the tests that would catch "the README lies". They run the actual
Typer app against a temporary project directory.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from astraforge.cli.main import app

runner = CliRunner()
REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_PLAN = REPO_ROOT / "examples/software_engineering/plan.yaml"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An initialised AstraForge project in a temp directory."""
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init", "."]).exit_code == 0
    return tmp_path


def test_help_lists_the_documented_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("run", "inspect", "logs", "artifacts", "verify", "tools", "init"):
        assert command in result.stdout


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "astraforge" in result.stdout


class TestInit:
    def test_creates_config_and_gitignores_run_data(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["init", "."])
        assert result.exit_code == 0
        assert (tmp_path / "astraforge.yaml").exists()
        assert ".astraforge/" in (tmp_path / ".gitignore").read_text()

    def test_refuses_to_clobber_without_force(self, project: Path) -> None:
        assert runner.invoke(app, ["init", "."]).exit_code == 1
        assert runner.invoke(app, ["init", ".", "--force"]).exit_code == 0


class TestRun:
    def test_default_run_produces_verified_artifacts(self, project: Path) -> None:
        result = runner.invoke(app, ["run", "Write a short design note", "-y"])
        assert result.exit_code == 0, result.stdout
        assert "COMPLETED" in result.stdout

        runs = list((project / ".astraforge" / "runs").iterdir())
        assert len(runs) == 1
        assert (runs[0] / "report.md").exists()
        assert (runs[0] / "events.jsonl").exists()
        assert (runs[0] / "workspace" / "brief.md").exists()

    def test_empty_goal_is_rejected(self, project: Path) -> None:
        assert runner.invoke(app, ["run", "   ", "-y"]).exit_code != 0

    def test_dry_run_plans_without_executing(self, project: Path) -> None:
        result = runner.invoke(app, ["run", "Plan only please", "--dry-run"])
        assert result.exit_code == 0
        assert "task_brief" in result.stdout
        assert not (project / ".astraforge" / "runs").exists()

    def test_json_output_is_machine_readable(self, project: Path) -> None:
        result = runner.invoke(app, ["run", "A goal", "-y", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["status"] == "COMPLETED"
        assert payload["tasks_completed"] == payload["tasks_total"]
        assert payload["verification_checks"] > 0

    def test_conflicting_approval_flags_are_rejected(self, project: Path) -> None:
        result = runner.invoke(app, ["run", "x", "-y", "--no-approve"])
        assert result.exit_code == 1
        assert "mutually exclusive" in result.stdout

    def test_unknown_provider_is_a_clear_error(self, project: Path) -> None:
        result = runner.invoke(app, ["run", "x", "-y", "--provider", "nope"])
        assert result.exit_code == 2
        assert "unknown provider" in result.stdout

    def test_a_failing_run_exits_nonzero(self, project: Path, tmp_path: Path) -> None:
        """Exit codes must be usable in CI."""
        plan = tmp_path / "bad.yaml"
        plan.write_text(
            "tasks:\n"
            "  - task_id: t1\n"
            "    description: write a file\n"
            "    tool: fs.write\n"
            "    tool_input: {path: a.md, content: x}\n"
            "    verification:\n"
            "      - verifier: file\n"
            "        params: {path: never-created.md}\n"
        )
        result = runner.invoke(app, ["run", "Fail on purpose", "--plan", str(plan), "-y"])
        assert result.exit_code == 1
        assert "FAILED" in result.stdout


class TestFlagshipDemo:
    """The demo advertised in the README must actually work."""

    @pytest.mark.slow
    def test_fix_the_failing_test_suite(self, project: Path) -> None:
        result = runner.invoke(
            app,
            ["run", "Fix the failing statistics module", "--plan", str(DEMO_PLAN), "-y"],
        )
        assert result.exit_code == 0, result.stdout
        assert "6/6 tasks completed" in result.stdout

        workspace = next((project / ".astraforge" / "runs").iterdir()) / "workspace"
        # The bug was really fixed, in the file on disk.
        assert "ordered[middle - 1]" in (workspace / "stats.py").read_text()
        summary = json.loads((workspace / "fix-summary.json").read_text())
        assert summary["files_changed"] == ["stats.py"]

    @pytest.mark.slow
    def test_demo_is_deterministic_across_runs(self, project: Path) -> None:
        """Same plan, same artifacts: the demo is reproducible."""
        hashes = []
        for _ in range(2):
            result = runner.invoke(
                app, ["run", "Fix it", "--plan", str(DEMO_PLAN), "-y", "--json"]
            )
            assert result.exit_code == 0
            hashes.append(json.loads(result.stdout)["artifacts"])
        assert hashes[0] == hashes[1]


class TestInspection:
    @pytest.fixture
    def ran(self, project: Path) -> Path:
        assert runner.invoke(app, ["run", "Inspectable goal", "-y"]).exit_code == 0
        return project

    def test_runs_lists_the_run(self, ran: Path) -> None:
        result = runner.invoke(app, ["runs"])
        assert result.exit_code == 0
        assert "COMPLETED" in result.stdout

    def test_inspect_shows_the_report(self, ran: Path) -> None:
        result = runner.invoke(app, ["inspect", "latest"])
        assert result.exit_code == 0
        assert "AstraForge run report" in result.stdout

    def test_inspect_json_is_the_full_record(self, ran: Path) -> None:
        result = runner.invoke(app, ["inspect", "latest", "--json"])
        assert result.exit_code == 0
        assert "run_id" in result.stdout

    def test_logs_can_be_filtered(self, ran: Path) -> None:
        result = runner.invoke(app, ["logs", "latest", "-t", "verification"])
        assert result.exit_code == 0
        assert "verification." in result.stdout

    def test_logs_json_is_valid_jsonl(self, ran: Path) -> None:
        result = runner.invoke(app, ["logs", "latest", "--json"])
        assert result.exit_code == 0
        lines = [ln for ln in result.stdout.splitlines() if ln.startswith("{")]
        assert lines and all(json.loads(ln)["run_id"] for ln in lines)

    def test_artifacts_are_listed_with_hashes(self, ran: Path) -> None:
        result = runner.invoke(app, ["artifacts", "latest"])
        assert result.exit_code == 0
        assert "brief.md" in result.stdout

    def test_verify_passes_for_an_untouched_run(self, ran: Path) -> None:
        result = runner.invoke(app, ["verify", "latest"])
        assert result.exit_code == 0
        assert "match their recorded hashes" in result.stdout

    def test_verify_detects_tampering(self, ran: Path) -> None:
        """The evidence chain must notice if an artifact is modified."""
        workspace = next((ran / ".astraforge" / "runs").iterdir()) / "workspace"
        (workspace / "brief.md").write_text("I edited this after the fact")
        result = runner.invoke(app, ["verify", "latest"])
        assert result.exit_code == 1
        assert "hash mismatch" in result.stdout

    def test_verify_detects_a_deleted_artifact(self, ran: Path) -> None:
        workspace = next((ran / ".astraforge" / "runs").iterdir()) / "workspace"
        (workspace / "brief.md").unlink()
        result = runner.invoke(app, ["verify", "latest"])
        assert result.exit_code == 1
        assert "missing artifact" in result.stdout

    def test_unknown_run_id_is_a_clear_error(self, ran: Path) -> None:
        result = runner.invoke(app, ["inspect", "run_doesnotexist"])
        assert result.exit_code == 3
        assert "no such run" in result.stdout


def test_tools_command_shows_permissions(project: Path) -> None:
    result = runner.invoke(app, ["tools"])
    assert result.exit_code == 0
    assert "shell.execute" in result.stdout
    assert "granted capabilities" in result.stdout
