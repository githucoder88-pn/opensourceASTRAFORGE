"""Core typed state objects for AstraForge."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    """Timezone-aware current time (UTC)."""
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    """Short, human-scannable identifier such as ``task_9f3a1c2b``."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class StrictModel(BaseModel):
    """Base model: reject unknown fields so malformed model output fails loudly."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        return _RISK_ORDER[self]


_RISK_ORDER = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

    @property
    def terminal(self) -> bool:
        return self in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}


class RunStatus(str, Enum):
    PLANNING = "PLANNING"
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class VerificationStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class FailureClass(str, Enum):
    TOOL_FAILURE = "TOOL_FAILURE"
    TIMEOUT = "TIMEOUT"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    TEST_FAILURE = "TEST_FAILURE"
    ENVIRONMENT_FAILURE = "ENVIRONMENT_FAILURE"
    AUTHORIZATION_FAILURE = "AUTHORIZATION_FAILURE"
    DEPENDENCY_FAILURE = "DEPENDENCY_FAILURE"
    MODEL_FAILURE = "MODEL_FAILURE"
    VERIFICATION_FAILURE = "VERIFICATION_FAILURE"
    POLICY_BLOCK = "POLICY_BLOCK"
    HUMAN_REJECTION = "HUMAN_REJECTION"

    @property
    def recoverable(self) -> bool:
        """Whether a bounded retry has any chance of changing the outcome."""
        return self not in {
            FailureClass.AUTHORIZATION_FAILURE,
            FailureClass.POLICY_BLOCK,
            FailureClass.HUMAN_REJECTION,
            FailureClass.DEPENDENCY_FAILURE,
        }


# --------------------------------------------------------------------------- #
# Goal / Plan / Task
# --------------------------------------------------------------------------- #


class Goal(StrictModel):
    """What the user wants to accomplish."""

    goal_id: str = Field(default_factory=lambda: new_id("goal"))
    description: str
    constraints: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class VerificationSpec(StrictModel):
    """Declarative request for a verifier, resolved by the verification registry."""

    verifier: str
    params: dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class Task(StrictModel):
    """A single unit of work in the plan graph."""

    task_id: str = Field(default_factory=lambda: new_id("task"))
    description: str
    tool: str
    tool_input: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    expected_output: str = ""
    verification: list[VerificationSpec] = Field(default_factory=list)
    risk: RiskLevel = RiskLevel.LOW
    max_attempts: int = 2
    status: TaskStatus = TaskStatus.PENDING
    attempts: list[TaskAttempt] = Field(default_factory=list)

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)


class Plan(StrictModel):
    """Structured execution strategy derived from a goal."""

    plan_id: str = Field(default_factory=lambda: new_id("plan"))
    goal_id: str
    assumptions: list[str] = Field(default_factory=list)
    objectives: list[str] = Field(default_factory=list)
    tasks: list[Task] = Field(default_factory=list)
    risk: RiskLevel = RiskLevel.LOW
    created_at: datetime = Field(default_factory=utcnow)

    def task(self, task_id: str) -> Task:
        for t in self.tasks:
            if t.task_id == task_id:
                return t
        raise KeyError(f"unknown task: {task_id}")

    def validate_graph(self) -> list[str]:
        """Return a list of structural problems; empty means the plan is sane."""
        problems: list[str] = []
        ids = [t.task_id for t in self.tasks]
        if not ids:
            problems.append("plan contains no tasks")
        duplicates = {i for i in ids if ids.count(i) > 1}
        problems += [f"duplicate task id: {d}" for d in sorted(duplicates)]
        known = set(ids)
        for t in self.tasks:
            problems += [
                f"task {t.task_id} depends on unknown task {dep}"
                for dep in t.depends_on
                if dep not in known
            ]
        if not problems and self._has_cycle():
            problems.append("task graph contains a dependency cycle")
        return problems

    def _has_cycle(self) -> bool:
        edges = {t.task_id: list(t.depends_on) for t in self.tasks}
        state: dict[str, int] = {}

        def visit(node: str) -> bool:
            if state.get(node) == 1:
                return True
            if state.get(node) == 2:
                return False
            state[node] = 1
            for dep in edges.get(node, []):
                if visit(dep):
                    return True
            state[node] = 2
            return False

        return any(visit(node) for node in edges)


# --------------------------------------------------------------------------- #
# Execution results
# --------------------------------------------------------------------------- #


class Evidence(StrictModel):
    """A single auditable statement about what was observed."""

    kind: str
    summary: str
    detail: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class ToolCall(StrictModel):
    """Record of one tool invocation."""

    call_id: str = Field(default_factory=lambda: new_id("call"))
    tool: str
    input: dict[str, Any] = Field(default_factory=dict)
    ok: bool = False
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    failure_class: FailureClass | None = None
    duration_ms: int = 0
    evidence: list[Evidence] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utcnow)


class VerificationResult(StrictModel):
    """Structured verifier output — never a bare boolean."""

    verifier: str
    status: VerificationStatus
    checks: int = 0
    failures: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status is not VerificationStatus.FAILED


class TaskAttempt(StrictModel):
    """One execution attempt of a task, including its verification round."""

    attempt: int
    tool_call: ToolCall | None = None
    verifications: list[VerificationResult] = Field(default_factory=list)
    ok: bool = False
    failure_class: FailureClass | None = None
    error: str | None = None
    finished_at: datetime = Field(default_factory=utcnow)


class Artifact(StrictModel):
    """A produced output with metadata, addressed by content hash."""

    artifact_id: str = Field(default_factory=lambda: new_id("art"))
    name: str
    path: str
    kind: str = "file"
    media_type: str = "application/octet-stream"
    bytes: int = 0
    sha256: str = ""
    produced_by: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class Run(StrictModel):
    """The complete auditable record of one goal execution."""

    run_id: str = Field(default_factory=lambda: new_id("run"))
    goal: Goal
    plan: Plan | None = None
    status: RunStatus = RunStatus.PLANNING
    artifacts: list[Artifact] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    provider: str = ""
    human_interventions: int = 0
    notes: list[str] = Field(default_factory=list)

    @property
    def duration_s(self) -> float:
        end = self.finished_at or utcnow()
        return round((end - self.started_at).total_seconds(), 3)
