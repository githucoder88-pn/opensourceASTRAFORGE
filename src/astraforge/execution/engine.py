"""The AstraForge execution engine.

This is the core loop the whole project exists to make trustworthy::

    goal -> plan -> validate -> [policy -> tool -> verify -> retry] -> artifacts -> report

Invariants the engine enforces, regardless of what any model asserts:

* A task only reaches ``COMPLETED`` when every one of its verifiers passed.
* No tool runs before the policy has allowed it (or a human approved it).
* Every attempt, failure and recovery is recorded as an event.
* Retries are bounded by attempt, tool-call and wall-clock budgets.
* Nothing is written outside the run's workspace.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from astraforge.artifacts.collector import collect_artifact
from astraforge.core.approvals import ApprovalGate, ApprovalRequest, DenyAllGate
from astraforge.core.config import Config
from astraforge.events.bus import EventBus, JsonlEventSink, MemoryEventSink
from astraforge.models.core import (
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
    utcnow,
)
from astraforge.models.events import EventType
from astraforge.planning.base import Planner, PlanningError
from astraforge.policies.policy import Decision, Policy
from astraforge.providers.base import ModelProvider
from astraforge.security.redaction import redact
from astraforge.security.workspace import Workspace
from astraforge.storage.run_store import RunStore
from astraforge.tools.base import ToolContext, ToolResult
from astraforge.tools.registry import ToolRegistry
from astraforge.verification import VerifierRegistry
from astraforge.verification.base import VerificationContext


class BudgetExceeded(RuntimeError):
    """A run hit one of its hard limits."""


@dataclass
class Budget:
    """Hard limits that make the loop terminate."""

    max_total_tool_calls: int = 100
    max_runtime_s: int = 900
    started_at: float = field(default_factory=time.monotonic)
    tool_calls: int = 0

    def charge_tool_call(self) -> None:
        self.tool_calls += 1
        if self.tool_calls > self.max_total_tool_calls:
            raise BudgetExceeded(
                f"tool call budget exhausted ({self.max_total_tool_calls} calls)"
            )

    def check_time(self) -> None:
        elapsed = time.monotonic() - self.started_at
        if elapsed > self.max_runtime_s:
            raise BudgetExceeded(
                f"runtime budget exhausted ({self.max_runtime_s}s)"
            )


@dataclass
class RunResult:
    """What a completed (or failed) run returns to the caller."""

    run: Run
    events: MemoryEventSink
    workspace: Workspace
    report_path: str | None = None

    @property
    def ok(self) -> bool:
        return self.run.status is RunStatus.COMPLETED

    @property
    def tasks(self) -> list[Task]:
        return list(self.run.plan.tasks) if self.run.plan else []


class Engine:
    """Executes a goal end to end and records everything it did."""

    def __init__(
        self,
        *,
        config: Config | None = None,
        planner: Planner,
        tools: ToolRegistry,
        verifiers: VerifierRegistry,
        provider: ModelProvider | None = None,
        policy: Policy | None = None,
        store: RunStore | None = None,
        approval_gate: ApprovalGate | None = None,
    ) -> None:
        self.config = config or Config()
        self.planner = planner
        self.tools = tools
        self.verifiers = verifiers
        self.provider = provider
        self.policy = policy or self.config.security.policy()
        self.store = store or RunStore(self.config.storage_dir)
        self.approval_gate = approval_gate or DenyAllGate()

    # -- public API ------------------------------------------------------- #

    def run(self, goal: Goal) -> RunResult:
        """Plan and execute ``goal``, returning the auditable result."""
        run = Run(goal=goal, provider=self.provider.name if self.provider else "")
        self.store.create(run.run_id)
        workspace = Workspace(self.store.workspace_dir(run.run_id))

        memory = MemoryEventSink()
        jsonl = JsonlEventSink(self.store.events_path(run.run_id))
        bus = EventBus(run.run_id, [memory, jsonl])
        budget = Budget(
            max_total_tool_calls=self.config.limits.max_total_tool_calls,
            max_runtime_s=self.config.limits.max_runtime_s,
        )
        state: dict[str, str] = {}

        bus.emit(
            EventType.RUN_STARTED,
            f"run started for goal: {goal.description}",
            payload={"goal_id": goal.goal_id, "provider": run.provider},
        )

        try:
            run.plan = self._make_plan(goal, bus)
            run.status = RunStatus.RUNNING
            self._execute_plan(run, run.plan, workspace, bus, budget, state)
        except PlanningError as exc:
            run.status = RunStatus.FAILED
            run.notes.append(f"planning failed: {exc}")
            bus.emit(EventType.PLAN_REJECTED, str(exc))
            bus.emit(EventType.RUN_FAILED, "run failed during planning")
        except BudgetExceeded as exc:
            run.status = RunStatus.FAILED
            run.notes.append(str(exc))
            # Leave no task claiming to be RUNNING after the process stops: a
            # persisted non-terminal status is a lie about the world.
            self._cancel_unfinished(run.plan, bus, reason=str(exc))
            bus.emit(EventType.RUN_FAILED, str(exc))
        else:
            failed = [t for t in run.plan.tasks if t.status is not TaskStatus.COMPLETED]
            run.status = RunStatus.FAILED if failed else RunStatus.COMPLETED
            bus.emit(
                EventType.RUN_FAILED if failed else EventType.RUN_COMPLETED,
                (
                    f"{len(failed)} task(s) did not complete"
                    if failed
                    else "all tasks completed and verified"
                ),
                payload={"unfinished": [t.task_id for t in failed]},
            )

        run.finished_at = utcnow()
        # Pin the event chain to the run record. The chain proves recorded
        # history was not altered; these two fields additionally prove that no
        # events were dropped from the end.
        run.event_count = jsonl.chain_length
        run.event_chain_head = jsonl.chain_head
        self.store.save_run(run)

        from astraforge.reporting.report import build_report  # local: avoid cycle

        report = build_report(run, memory.events)
        path = self.store.save_report(run.run_id, report)
        self.store.save_run(run)
        return RunResult(run=run, events=memory, workspace=workspace, report_path=str(path))

    # -- planning --------------------------------------------------------- #

    def _make_plan(self, goal: Goal, bus: EventBus) -> Plan:
        plan = self.planner.plan(goal, self.tools)
        problems = plan.validate_graph()
        if problems:
            raise PlanningError("; ".join(problems))
        bus.emit(
            EventType.PLAN_CREATED,
            f"plan with {len(plan.tasks)} task(s)",
            actor=f"planner:{self.planner.name}",
            payload={"plan_id": plan.plan_id, "tasks": [t.task_id for t in plan.tasks]},
        )
        bus.emit(EventType.PLAN_VALIDATED, "task graph is acyclic and tools resolve")
        return plan

    # -- execution -------------------------------------------------------- #

    def _execute_plan(
        self,
        run: Run,
        plan: Plan,
        workspace: Workspace,
        bus: EventBus,
        budget: Budget,
        state: dict[str, str],
    ) -> None:
        """Run tasks in dependency order until nothing more can progress."""
        while True:
            budget.check_time()
            task = self._next_ready(plan)
            if task is None:
                break
            bus.emit(EventType.TASK_READY, task.description, task_id=task.task_id)
            self._execute_task(run, task, workspace, bus, budget, state)

        for task in plan.tasks:
            if task.status is TaskStatus.PENDING:
                task.status = TaskStatus.BLOCKED
                blockers = [
                    d
                    for d in task.depends_on
                    if plan.task(d).status is not TaskStatus.COMPLETED
                ]
                bus.emit(
                    EventType.TASK_BLOCKED,
                    f"blocked by unfinished dependencies: {', '.join(blockers)}",
                    task_id=task.task_id,
                    payload={"blocked_by": blockers},
                )

    @staticmethod
    def _cancel_unfinished(plan: Plan | None, bus: EventBus, reason: str) -> None:
        """Move every non-terminal task to CANCELLED when a run is cut short."""
        if plan is None:
            return
        for task in plan.tasks:
            if task.status.terminal:
                continue
            task.status = TaskStatus.CANCELLED
            bus.emit(
                EventType.RUN_CANCELLED,
                f"task cancelled: {reason}",
                task_id=task.task_id,
                payload={"reason": reason},
            )

    @staticmethod
    def _next_ready(plan: Plan) -> Task | None:
        for task in plan.tasks:
            if task.status is not TaskStatus.PENDING:
                continue
            deps = [plan.task(d) for d in task.depends_on]
            if all(d.status is TaskStatus.COMPLETED for d in deps):
                return task
            if any(d.status.terminal for d in deps):
                continue  # permanently blocked; handled after the loop
        return None

    def _execute_task(
        self,
        run: Run,
        task: Task,
        workspace: Workspace,
        bus: EventBus,
        budget: Budget,
        state: dict[str, str],
    ) -> None:
        max_attempts = min(task.max_attempts, self.config.limits.max_task_attempts)

        for attempt_no in range(1, max_attempts + 1):
            budget.check_time()
            task.status = TaskStatus.RUNNING if attempt_no == 1 else TaskStatus.RETRYING
            bus.emit(
                EventType.TASK_STARTED if attempt_no == 1 else EventType.TASK_RETRYING,
                f"attempt {attempt_no}/{max_attempts}: {task.description}",
                task_id=task.task_id,
                payload={"attempt": attempt_no, "tool": task.tool},
            )

            attempt = TaskAttempt(attempt=attempt_no)
            task.attempts.append(attempt)

            gate = self._authorize(task, bus, state)
            if gate is not None:
                attempt.failure_class, attempt.error = gate
                task.status = TaskStatus.FAILED
                bus.emit(
                    EventType.TASK_FAILED,
                    gate[1],
                    task_id=task.task_id,
                    payload={"failure_class": gate[0].value},
                )
                return  # policy failures are not retryable

            call, result = self._call_tool(task, workspace, bus, budget, run)
            attempt.tool_call = call

            if not result.ok:
                attempt.failure_class = result.failure_class or FailureClass.TOOL_FAILURE
                attempt.error = result.error
                if self._give_up(task, attempt, attempt_no, max_attempts, bus):
                    return
                continue

            self._collect_artifacts(run, task, result, workspace, bus)

            task.status = TaskStatus.VERIFYING
            verifications = self._verify(task, workspace, result, bus, run, state)
            attempt.verifications = verifications
            failed = [v for v in verifications if not v.passed]

            if failed:
                attempt.failure_class = FailureClass.VERIFICATION_FAILURE
                attempt.error = "; ".join(f for v in failed for f in v.failures)
                if self._give_up(task, attempt, attempt_no, max_attempts, bus):
                    return
                continue

            attempt.ok = True
            task.status = TaskStatus.COMPLETED
            bus.emit(
                EventType.TASK_COMPLETED,
                f"completed and verified on attempt {attempt_no}",
                task_id=task.task_id,
                payload={
                    "attempt": attempt_no,
                    "checks": sum(v.checks for v in verifications),
                },
            )
            return

    def _give_up(
        self,
        task: Task,
        attempt: TaskAttempt,
        attempt_no: int,
        max_attempts: int,
        bus: EventBus,
    ) -> bool:
        """Decide whether to stop retrying. Emits the appropriate event."""
        cls = attempt.failure_class
        unrecoverable = cls is not None and not cls.recoverable
        exhausted = attempt_no >= max_attempts
        if unrecoverable or exhausted:
            task.status = TaskStatus.FAILED
            bus.emit(
                EventType.TASK_FAILED,
                (
                    f"unrecoverable {cls.value if cls else 'failure'}: {attempt.error}"
                    if unrecoverable
                    else f"failed after {attempt_no} attempt(s): {attempt.error}"
                ),
                task_id=task.task_id,
                payload={
                    "failure_class": cls.value if cls else None,
                    "attempts": attempt_no,
                    "recoverable": bool(cls and cls.recoverable),
                },
            )
            return True
        return False

    # -- steps ------------------------------------------------------------ #

    def _authorize(
        self, task: Task, bus: EventBus, state: dict[str, str]
    ) -> tuple[FailureClass, str] | None:
        """Policy + approval check. Returns a failure tuple if the task may not run."""
        tool = self.tools.get(task.tool)
        risk = max(task.risk, tool.risk, key=lambda r: r.rank)
        verdict = self.policy.evaluate(tool.capabilities, risk)

        if verdict.decision is Decision.DENY:
            bus.emit(
                EventType.POLICY_BLOCKED,
                verdict.reason,
                task_id=task.task_id,
                payload={"tool": tool.name, "risk": risk.value},
            )
            return FailureClass.POLICY_BLOCK, f"policy denied {tool.name}: {verdict.reason}"

        if verdict.decision is Decision.REQUIRE_APPROVAL:
            bus.emit(
                EventType.APPROVAL_REQUIRED,
                verdict.reason,
                task_id=task.task_id,
                payload={"tool": tool.name, "risk": risk.value},
            )
            state[f"approval_requested:{task.task_id}"] = "yes"
            granted = self.approval_gate.request(
                ApprovalRequest(
                    task_id=task.task_id,
                    tool=tool.name,
                    risk=risk.value,
                    reason=verdict.reason,
                    summary=task.description,
                )
            )
            bus.emit(
                EventType.APPROVAL_GRANTED if granted else EventType.APPROVAL_DENIED,
                f"human {'approved' if granted else 'rejected'} {task.task_id}",
                actor=f"human:{self.approval_gate.name}",
                task_id=task.task_id,
            )
            if not granted:
                return FailureClass.HUMAN_REJECTION, f"human rejected {tool.name}"
            state[f"approval:{task.task_id}"] = "granted"
        return None

    def _call_tool(
        self,
        task: Task,
        workspace: Workspace,
        bus: EventBus,
        budget: Budget,
        run: Run,
    ) -> tuple[ToolCall, ToolResult]:
        tool = self.tools.get(task.tool)
        budget.charge_tool_call()
        bus.emit(
            EventType.TOOL_CALLED,
            f"calling {tool.name}",
            actor=f"tool:{tool.name}",
            task_id=task.task_id,
            payload={"input": redact(task.tool_input)},
        )
        ctx = ToolContext(
            workspace=workspace,
            run_id=run.run_id,
            task_id=task.task_id,
            env=self._tool_env(),
        )
        # Snapshot the workspace so files a tool creates indirectly - e.g. a
        # script run through shell.run that writes a report - are still
        # captured as artifacts. Tools cannot be trusted to declare everything
        # they produced, and undeclared output is exactly what goes missing
        # from an evidence trail.
        before = workspace.snapshot()
        result, duration = tool.execute(task.tool_input, ctx)
        if result.ok:
            declared = set(result.produced_paths)
            result.produced_paths.extend(
                path
                for path in workspace.changed_since(before, workspace.snapshot())
                if path not in declared
            )
        call = ToolCall(
            tool=tool.name,
            input=redact(task.tool_input),
            ok=result.ok,
            output=redact(result.output),
            error=redact(result.error) if result.error else None,
            failure_class=result.failure_class,
            duration_ms=duration,
            evidence=result.evidence,
        )
        bus.emit(
            EventType.TOOL_SUCCEEDED if result.ok else EventType.TOOL_FAILED,
            (
                f"{tool.name} succeeded in {duration}ms"
                if result.ok
                else f"{tool.name} failed: {call.error}"
            ),
            actor=f"tool:{tool.name}",
            task_id=task.task_id,
            payload={
                "duration_ms": duration,
                "failure_class": (
                    result.failure_class.value if result.failure_class else None
                ),
            },
        )
        return call, result

    @staticmethod
    def _tool_env() -> dict[str, str]:
        """Minimal environment handed to subprocesses — secrets are not forwarded."""
        import os

        keep = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT")
        return {k: v for k, v in os.environ.items() if k in keep}

    def _verify(
        self,
        task: Task,
        workspace: Workspace,
        result: ToolResult,
        bus: EventBus,
        run: Run,
        state: dict[str, str],
    ) -> list[VerificationResult]:
        if not task.verification:
            # An unverifiable task cannot be trusted; say so loudly in evidence.
            bus.emit(
                EventType.VERIFICATION_PASSED,
                "no verification declared for this task",
                task_id=task.task_id,
                payload={"unverified": True},
            )
            return [
                VerificationResult(
                    verifier="none",
                    status=VerificationStatus.SKIPPED,
                    checks=0,
                )
            ]

        ctx = VerificationContext(
            workspace=workspace,
            run_id=run.run_id,
            task_id=task.task_id,
            tool_result=result,
            env=state,
        )
        results: list[VerificationResult] = []
        for spec in task.verification:
            bus.emit(
                EventType.VERIFICATION_STARTED,
                spec.description or spec.verifier,
                actor=f"verifier:{spec.verifier}",
                task_id=task.task_id,
            )
            if not self.verifiers.has(spec.verifier):
                results.append(
                    VerificationResult(
                        verifier=spec.verifier,
                        status=VerificationStatus.FAILED,
                        failures=[f"unknown verifier: {spec.verifier}"],
                    )
                )
            else:
                results.append(self.verifiers.get(spec.verifier).run(spec.params, ctx))
            last = results[-1]
            outcome = (
                EventType.VERIFICATION_PASSED
                if last.passed
                else EventType.VERIFICATION_FAILED
            )
            bus.emit(
                outcome,
                (
                    f"{last.verifier}: {last.checks} check(s) passed"
                    if last.passed
                    else f"{last.verifier}: {'; '.join(last.failures)}"
                ),
                actor=f"verifier:{last.verifier}",
                task_id=task.task_id,
                payload={"status": last.status.value, "checks": last.checks},
            )
        return results

    def _collect_artifacts(
        self,
        run: Run,
        task: Task,
        result: ToolResult,
        workspace: Workspace,
        bus: EventBus,
    ) -> None:
        # Artifacts are keyed by (path, content hash). A task that rewrites a
        # file produces a NEW artifact record, so the report shows that the
        # file changed and which task changed it. Deduping by path alone would
        # hide exactly the evidence a reviewer needs.
        known = {(a.path, a.sha256) for a in run.artifacts}
        for rel in result.produced_paths:
            artifact = collect_artifact(workspace, rel, produced_by=task.task_id)
            if artifact is None or (artifact.path, artifact.sha256) in known:
                continue
            revision = sum(1 for a in run.artifacts if a.path == artifact.path)
            run.artifacts.append(artifact)
            known.add((artifact.path, artifact.sha256))
            bus.emit(
                EventType.ARTIFACT_CREATED,
                (
                    f"{artifact.path} ({artifact.bytes} bytes, {artifact.media_type})"
                    + (f" [revision {revision + 1}]" if revision else "")
                ),
                task_id=task.task_id,
                payload={
                    "sha256": artifact.sha256,
                    "path": artifact.path,
                    "revision": revision + 1,
                },
            )
