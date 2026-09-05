"""The proof-of-work report must reflect reality, including failures."""

from __future__ import annotations

from astraforge.models.core import (
    Artifact,
    Evidence,
    FailureClass,
    Goal,
    Plan,
    Run,
    RunStatus,
    Task,
    TaskAttempt,
    TaskStatus,
    ToolCall,
    VerificationResult,
    VerificationStatus,
)
from astraforge.models.events import Event, EventType
from astraforge.reporting.report import build_report, summarise


def _run() -> Run:
    completed = Task(
        task_id="t_ok",
        description="write the report",
        tool="fs.write",
        status=TaskStatus.COMPLETED,
        attempts=[
            TaskAttempt(
                attempt=1,
                ok=False,
                failure_class=FailureClass.VERIFICATION_FAILURE,
                error="missing marker",
            ),
            TaskAttempt(
                attempt=2,
                ok=True,
                tool_call=ToolCall(
                    tool="fs.write",
                    ok=True,
                    duration_ms=5,
                    evidence=[Evidence(kind="file.written", summary="wrote r.md")],
                ),
                verifications=[
                    VerificationResult(
                        verifier="file",
                        status=VerificationStatus.PASSED,
                        checks=3,
                        evidence=[Evidence(kind="file", summary="r.md exists")],
                    )
                ],
            ),
        ],
    )
    failed = Task(
        task_id="t_bad",
        description="run the tests",
        tool="shell.run",
        status=TaskStatus.FAILED,
        attempts=[
            TaskAttempt(
                attempt=1,
                failure_class=FailureClass.TEST_FAILURE,
                error="2 tests failed",
                verifications=[
                    VerificationResult(
                        verifier="tests",
                        status=VerificationStatus.FAILED,
                        checks=1,
                        failures=["pytest exited 1"],
                    )
                ],
            )
        ],
    )
    return Run(
        goal=Goal(description="Demo goal", success_criteria=["tests pass"]),
        plan=Plan(goal_id="g", tasks=[completed, failed], assumptions=["a1"]),
        status=RunStatus.FAILED,
        provider="echo",
        artifacts=[
            Artifact(name="r.md", path="r.md", bytes=10, sha256="a" * 64, produced_by="t_ok")
        ],
    )


def _events() -> list[Event]:
    return [
        Event(run_id="r", type=t)
        for t in (
            EventType.RUN_STARTED,
            EventType.TOOL_CALLED,
            EventType.TOOL_CALLED,
            EventType.VERIFICATION_FAILED,
            EventType.APPROVAL_GRANTED,
            EventType.RUN_FAILED,
        )
    ]


class TestSummarise:
    def test_counts_are_accurate(self) -> None:
        stats = summarise(_run(), _events())
        assert stats["tasks_total"] == 2
        assert stats["tasks_completed"] == 1
        assert stats["tasks_failed"] == 1
        assert stats["tool_calls"] == 2
        assert stats["verification_checks"] == 4
        assert stats["human_interventions"] == 1
        assert stats["recovered_failures"] == 1  # t_ok succeeded on attempt 2
        assert stats["artifacts"] == 1


class TestReport:
    def test_report_does_not_hide_failures(self) -> None:
        report = build_report(_run(), _events())
        assert "FAIL" in report
        assert "t_bad" in report
        assert "pytest exited 1" in report
        assert "TEST_FAILURE" in report

    def test_report_shows_retry_and_recovery(self) -> None:
        report = build_report(_run(), _events())
        assert "Attempt 1" in report and "Attempt 2" in report
        assert "missing marker" in report

    def test_report_includes_evidence_and_hashes(self) -> None:
        report = build_report(_run(), _events())
        assert "r.md exists" in report
        assert "aaaaaaaaaaaaaaaa" in report

    def test_report_states_the_goal_and_criteria(self) -> None:
        report = build_report(_run(), _events())
        assert "Demo goal" in report
        assert "tests pass" in report

    def test_a_run_with_no_artifacts_says_so(self) -> None:
        run = Run(goal=Goal(description="g"))
        assert "No artifacts were produced" in build_report(run, [])

    def test_report_is_valid_markdown_structure(self) -> None:
        report = build_report(_run(), _events())
        assert report.startswith("# AstraForge run report")
        for heading in ("## Summary", "## Tasks", "## Artifacts"):
            assert heading in report
