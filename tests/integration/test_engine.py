"""Engine guarantees.

These tests encode the promises AstraForge makes. If one of them breaks, the
project's central claim — verified work, not asserted work — is no longer true.
"""

from __future__ import annotations

from astraforge.core.approvals import ScriptedGate
from astraforge.models.core import (
    FailureClass,
    Goal,
    Plan,
    RiskLevel,
    RunStatus,
    Task,
    TaskStatus,
    VerificationSpec,
)
from astraforge.models.events import EventType
from astraforge.planning.static import StaticPlanner
from astraforge.policies.policy import Policy
from astraforge.security.capabilities import Capability


def _plan(*tasks: Task) -> Plan:
    return Plan(goal_id="g", tasks=list(tasks))


def _write(task_id: str, path: str, content: str, **kw: object) -> Task:
    return Task(
        task_id=task_id,
        description=f"write {path}",
        tool="fs.write",
        tool_input={"path": path, "content": content},
        **kw,  # type: ignore[arg-type]
    )


class TestHappyPath:
    def test_completes_and_verifies(self, make_engine, goal: Goal) -> None:
        task = _write(
            "t1",
            "out.md",
            "# Result\nbody",
            verification=[
                VerificationSpec(
                    verifier="file", params={"path": "out.md", "contains": ["# Result"]}
                )
            ],
        )
        result = make_engine(StaticPlanner(plan=_plan(task))).run(goal)

        assert result.ok
        assert result.run.status is RunStatus.COMPLETED
        assert result.tasks[0].status is TaskStatus.COMPLETED
        assert result.workspace.read_text("out.md").startswith("# Result")

    def test_records_artifacts_with_hashes(self, make_engine, goal: Goal) -> None:
        result = make_engine(StaticPlanner(plan=_plan(_write("t1", "a.md", "x")))).run(goal)
        artifact = result.run.artifacts[0]
        assert artifact.path == "a.md"
        assert len(artifact.sha256) == 64
        assert artifact.produced_by == "t1"
        assert artifact.media_type == "text/markdown"

    def test_rewriting_a_file_records_a_second_revision(
        self, make_engine, goal: Goal
    ) -> None:
        """Evidence must show that a file changed, and which task changed it."""
        plan = _plan(
            _write("t1", "a.md", "first"),
            _write("t2", "a.md", "second", depends_on=["t1"]),
        )
        result = make_engine(StaticPlanner(plan=plan)).run(goal)
        revisions = [a for a in result.run.artifacts if a.path == "a.md"]
        assert len(revisions) == 2
        assert revisions[0].sha256 != revisions[1].sha256
        assert [a.produced_by for a in revisions] == ["t1", "t2"]

    def test_emits_a_complete_event_trail(self, make_engine, goal: Goal) -> None:
        result = make_engine(StaticPlanner(plan=_plan(_write("t1", "a.md", "x")))).run(goal)
        types = [e.type for e in result.events.events]
        for expected in (
            EventType.RUN_STARTED,
            EventType.PLAN_CREATED,
            EventType.PLAN_VALIDATED,
            EventType.TASK_STARTED,
            EventType.TOOL_CALLED,
            EventType.TOOL_SUCCEEDED,
            EventType.ARTIFACT_CREATED,
            EventType.TASK_COMPLETED,
            EventType.RUN_COMPLETED,
        ):
            assert expected in types, f"missing event {expected}"


class TestVerificationIsAuthoritative:
    def test_a_successful_tool_with_failing_verification_does_not_complete(
        self, make_engine, goal: Goal
    ) -> None:
        """The defining guarantee: the tool succeeded, but the evidence disagreed."""
        task = _write(
            "t1",
            "out.md",
            "the wrong content",
            verification=[
                VerificationSpec(
                    verifier="file",
                    params={"path": "out.md", "contains": ["REQUIRED MARKER"]},
                )
            ],
        )
        result = make_engine(StaticPlanner(plan=_plan(task))).run(goal)

        assert not result.ok
        assert result.tasks[0].status is TaskStatus.FAILED
        attempt = result.tasks[0].attempts[-1]
        assert attempt.tool_call is not None and attempt.tool_call.ok  # tool was fine
        assert attempt.failure_class is FailureClass.VERIFICATION_FAILURE

    def test_unknown_verifier_fails_closed(self, make_engine, goal: Goal) -> None:
        task = _write(
            "t1",
            "a.md",
            "x",
            verification=[VerificationSpec(verifier="does_not_exist")],
        )
        result = make_engine(StaticPlanner(plan=_plan(task))).run(goal)
        assert result.tasks[0].status is TaskStatus.FAILED

    def test_a_task_without_verification_is_flagged_as_unverified(
        self, make_engine, goal: Goal
    ) -> None:
        result = make_engine(StaticPlanner(plan=_plan(_write("t1", "a.md", "x")))).run(goal)
        assert result.ok
        unverified = [
            e for e in result.events.events if e.payload.get("unverified") is True
        ]
        assert unverified, "an unverified task must be recorded as such"


class TestRetryAndRecovery:
    def test_retries_are_bounded_by_max_attempts(self, make_engine, goal: Goal) -> None:
        task = _write(
            "t1",
            "a.md",
            "x",
            max_attempts=3,
            verification=[
                VerificationSpec(verifier="file", params={"path": "never.md"})
            ],
        )
        result = make_engine(StaticPlanner(plan=_plan(task))).run(goal)
        assert result.tasks[0].attempt_count == 2  # capped by config limit of 2
        assert result.tasks[0].status is TaskStatus.FAILED

    def test_retries_never_loop_forever(self, make_engine, goal: Goal) -> None:
        engine = make_engine(
            StaticPlanner(
                plan=_plan(
                    Task(
                        task_id="t1",
                        description="always fails",
                        tool="shell.run",
                        tool_input={"command": ["python", "-c", "raise SystemExit(1)"]},
                        max_attempts=10,
                    )
                )
            )
        )
        engine.config.limits.max_task_attempts = 3
        result = engine.run(goal)
        assert result.tasks[0].attempt_count == 3

    def test_unrecoverable_failures_are_not_retried(self, make_engine, goal: Goal) -> None:
        engine = make_engine(StaticPlanner(plan=_plan(_write("t1", "a.md", "x"))))
        engine.policy = Policy(granted=frozenset({Capability.FILESYSTEM_READ}))
        result = engine.run(goal)
        assert result.tasks[0].attempt_count == 1
        assert result.tasks[0].attempts[0].failure_class is FailureClass.POLICY_BLOCK

    def test_tool_call_budget_terminates_the_run(self, make_engine, goal: Goal) -> None:
        plan = _plan(*[_write(f"t{i}", f"f{i}.md", "x") for i in range(5)])
        engine = make_engine(StaticPlanner(plan=plan))
        engine.config.limits.max_total_tool_calls = 2
        result = engine.run(goal)
        assert result.run.status is RunStatus.FAILED
        assert any("budget" in n for n in result.run.notes)


class TestDependencies:
    def test_tasks_run_in_dependency_order(self, make_engine, goal: Goal) -> None:
        plan = _plan(
            _write("t_second", "b.md", "b", depends_on=["t_first"]),
            _write("t_first", "a.md", "a"),
        )
        result = make_engine(StaticPlanner(plan=plan)).run(goal)
        order = [
            e.task_id
            for e in result.events.events
            if e.type is EventType.TASK_COMPLETED
        ]
        assert order == ["t_first", "t_second"]

    def test_dependents_of_a_failed_task_are_blocked_not_run(
        self, make_engine, goal: Goal
    ) -> None:
        plan = _plan(
            _write(
                "t_fail",
                "a.md",
                "x",
                verification=[VerificationSpec(verifier="file", params={"path": "no.md"})],
            ),
            _write("t_dependent", "b.md", "b", depends_on=["t_fail"]),
        )
        result = make_engine(StaticPlanner(plan=plan)).run(goal)
        statuses = {t.task_id: t.status for t in result.tasks}
        assert statuses["t_fail"] is TaskStatus.FAILED
        assert statuses["t_dependent"] is TaskStatus.BLOCKED
        assert not (result.workspace.root / "b.md").exists()

    def test_invalid_plans_are_rejected_before_execution(
        self, make_engine, goal: Goal
    ) -> None:
        plan = _plan(_write("t1", "a.md", "x", depends_on=["ghost"]))
        result = make_engine(StaticPlanner(plan=plan)).run(goal)
        assert result.run.status is RunStatus.FAILED
        assert not result.run.artifacts


class TestPolicyAndApproval:
    def _risky(self) -> Task:
        return Task(
            task_id="t_risky",
            description="run a high risk command",
            tool="shell.run",
            tool_input={"command": ["echo", "hello"]},
            risk=RiskLevel.HIGH,
        )

    def test_denied_capability_blocks_the_tool(self, make_engine, goal: Goal) -> None:
        engine = make_engine(StaticPlanner(plan=_plan(self._risky())))
        engine.policy = Policy(granted=frozenset({Capability.FILESYSTEM_READ}))
        result = engine.run(goal)
        assert result.tasks[0].status is TaskStatus.FAILED
        assert any(
            e.type is EventType.POLICY_BLOCKED for e in result.events.events
        )
        # The tool must never have been invoked.
        assert not any(e.type is EventType.TOOL_CALLED for e in result.events.events)

    def test_human_rejection_stops_the_task(self, make_engine, goal: Goal) -> None:
        engine = make_engine(StaticPlanner(plan=_plan(self._risky())))
        engine.policy = Policy()  # approval required at HIGH
        engine.approval_gate = ScriptedGate(default=False)
        result = engine.run(goal)
        assert result.tasks[0].attempts[0].failure_class is FailureClass.HUMAN_REJECTION
        assert any(e.type is EventType.APPROVAL_DENIED for e in result.events.events)

    def test_human_approval_allows_the_task(self, make_engine, goal: Goal) -> None:
        engine = make_engine(StaticPlanner(plan=_plan(self._risky())))
        engine.policy = Policy()
        engine.approval_gate = ScriptedGate(decisions={"t_risky": True})
        result = engine.run(goal)
        assert result.tasks[0].status is TaskStatus.COMPLETED
        assert any(e.type is EventType.APPROVAL_GRANTED for e in result.events.events)

    def test_approval_is_recorded_as_verifiable_evidence(
        self, make_engine, goal: Goal
    ) -> None:
        task = self._risky()
        task.verification = [VerificationSpec(verifier="human_approval")]
        engine = make_engine(StaticPlanner(plan=_plan(task)))
        engine.policy = Policy()
        engine.approval_gate = ScriptedGate(decisions={"t_risky": True})
        result = engine.run(goal)
        assert result.tasks[0].status is TaskStatus.COMPLETED

    def test_task_risk_escalates_beyond_the_tool_default(
        self, make_engine, goal: Goal
    ) -> None:
        """A LOW-risk tool used for a CRITICAL task must still be gated."""
        task = _write("t1", "a.md", "x", risk=RiskLevel.CRITICAL)
        engine = make_engine(StaticPlanner(plan=_plan(task)))
        engine.policy = Policy()
        engine.approval_gate = ScriptedGate(default=False)
        result = engine.run(goal)
        assert result.tasks[0].attempts[0].failure_class is FailureClass.HUMAN_REJECTION


class TestContainment:
    def test_a_plan_cannot_write_outside_the_workspace(
        self, make_engine, goal: Goal, tmp_path
    ) -> None:
        task = _write("t1", "../../escaped.txt", "pwned")
        result = make_engine(StaticPlanner(plan=_plan(task))).run(goal)
        assert result.tasks[0].status is TaskStatus.FAILED
        assert not (tmp_path / "escaped.txt").exists()

    def test_secrets_are_redacted_from_the_event_log(
        self, make_engine, goal: Goal, monkeypatch
    ) -> None:
        monkeypatch.setenv("DEMO_API_KEY", "sk-abcdefghijklmnopqrstuvwxyz123456")
        task = _write("t1", "a.md", "key sk-abcdefghijklmnopqrstuvwxyz123456")
        result = make_engine(StaticPlanner(plan=_plan(task))).run(goal)
        log = result.events.events
        serialised = " ".join(e.model_dump_json() for e in log)
        assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in serialised

    def test_subprocesses_do_not_inherit_secrets(
        self, make_engine, goal: Goal, monkeypatch
    ) -> None:
        monkeypatch.setenv("SUPER_SECRET_TOKEN", "leak-me-please")
        task = Task(
            task_id="t1",
            description="print the environment",
            tool="shell.run",
            tool_input={
                "command": ["python", "-c", "import os; print(sorted(os.environ))"]
            },
        )
        result = make_engine(StaticPlanner(plan=_plan(task))).run(goal)
        stdout = result.tasks[0].attempts[0].tool_call.output["stdout"]  # type: ignore[union-attr]
        assert "SUPER_SECRET_TOKEN" not in stdout


class TestPersistence:
    def test_the_run_is_reloadable_from_disk(self, make_engine, goal: Goal) -> None:
        engine = make_engine(StaticPlanner(plan=_plan(_write("t1", "a.md", "x"))))
        result = engine.run(goal)
        reloaded = engine.store.load_run(result.run.run_id)
        assert reloaded.run_id == result.run.run_id
        assert reloaded.status is result.run.status
        assert len(reloaded.artifacts) == len(result.run.artifacts)

    def test_events_are_persisted_as_jsonl(self, make_engine, goal: Goal) -> None:
        engine = make_engine(StaticPlanner(plan=_plan(_write("t1", "a.md", "x"))))
        result = engine.run(goal)
        on_disk = engine.store.load_events(result.run.run_id)
        assert len(on_disk) == len(result.events.events)

    def test_a_report_is_always_written(self, make_engine, goal: Goal) -> None:
        engine = make_engine(StaticPlanner(plan=_plan(_write("t1", "a.md", "x"))))
        result = engine.run(goal)
        report = engine.store.report_path(result.run.run_id).read_text()
        assert "# AstraForge run report" in report
        assert result.run.run_id in report

    def test_a_failed_run_still_produces_a_report(self, make_engine, goal: Goal) -> None:
        task = _write(
            "t1",
            "a.md",
            "x",
            verification=[VerificationSpec(verifier="file", params={"path": "no.md"})],
        )
        engine = make_engine(StaticPlanner(plan=_plan(task)))
        result = engine.run(goal)
        assert not result.ok
        report = engine.store.report_path(result.run.run_id).read_text()
        assert "FAIL" in report

    def test_runs_are_isolated_from_each_other(self, make_engine, goal: Goal) -> None:
        engine = make_engine(StaticPlanner(plan=_plan(_write("t1", "a.md", "x"))))
        first = engine.run(goal)
        second = engine.run(Goal(description="another goal"))
        assert first.run.run_id != second.run.run_id
        assert first.workspace.root != second.workspace.root


class TestRunTermination:
    """Audit regression: a cut-short run must not persist non-terminal statuses."""

    def test_budget_abort_cancels_unfinished_tasks(self, make_engine, goal: Goal) -> None:
        plan = _plan(*[_write(f"t{i}", f"f{i}.md", "x") for i in range(5)])
        engine = make_engine(StaticPlanner(plan=plan))
        engine.config.limits.max_total_tool_calls = 2
        result = engine.run(goal)

        assert result.run.status is RunStatus.FAILED
        stranded = [t.task_id for t in result.tasks if not t.status.terminal]
        assert not stranded, f"tasks left in a non-terminal state: {stranded}"

    def test_cancelled_state_survives_a_reload(self, make_engine, goal: Goal) -> None:
        """run.json must not claim a task is RUNNING after the process exited."""
        plan = _plan(*[_write(f"t{i}", f"f{i}.md", "x") for i in range(5)])
        engine = make_engine(StaticPlanner(plan=plan))
        engine.config.limits.max_total_tool_calls = 1
        result = engine.run(goal)

        reloaded = engine.store.load_run(result.run.run_id)
        assert reloaded.plan is not None
        assert all(t.status.terminal for t in reloaded.plan.tasks)
        assert any(t.status is TaskStatus.CANCELLED for t in reloaded.plan.tasks)


class TestApprovalVerifierGuidance:
    """Audit regression: `human_approval` on a low-risk task was a silent trap."""

    def _task(self, risk: RiskLevel) -> Task:
        return Task(
            task_id="t_approve",
            description="needs sign-off",
            tool="fs.write",
            tool_input={"path": "a.md", "content": "x"},
            risk=risk,
            verification=[VerificationSpec(verifier="human_approval")],
        )

    def test_low_risk_failure_explains_how_to_fix_it(
        self, make_engine, goal: Goal
    ) -> None:
        engine = make_engine(StaticPlanner(plan=_plan(self._task(RiskLevel.LOW))))
        result = engine.run(goal)

        failures = [
            f
            for a in result.tasks[0].attempts
            for v in a.verifications
            for f in v.failures
        ]
        assert failures
        message = " ".join(failures)
        # The message must name the cause and the remedy, not just the symptom.
        assert "approval threshold" in message
        assert "risk" in message and "approval_at_or_above" in message

    def test_high_risk_with_approval_passes(self, make_engine, goal: Goal) -> None:
        engine = make_engine(StaticPlanner(plan=_plan(self._task(RiskLevel.HIGH))))
        engine.policy = Policy()
        engine.approval_gate = ScriptedGate(decisions={"t_approve": True})
        assert engine.run(goal).tasks[0].status is TaskStatus.COMPLETED
