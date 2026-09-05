"""Structured events: the append-only spine of an AstraForge run."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field

from astraforge.models.core import StrictModel, new_id, utcnow


class EventType(str, Enum):
    RUN_STARTED = "run.started"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"
    PLAN_CREATED = "plan.created"
    PLAN_VALIDATED = "plan.validated"
    PLAN_REJECTED = "plan.rejected"
    TASK_READY = "task.ready"
    TASK_STARTED = "task.started"
    TASK_BLOCKED = "task.blocked"
    TASK_RETRYING = "task.retrying"
    TASK_FAILED = "task.failed"
    TASK_COMPLETED = "task.completed"
    TOOL_CALLED = "tool.called"
    TOOL_SUCCEEDED = "tool.succeeded"
    TOOL_FAILED = "tool.failed"
    VERIFICATION_STARTED = "verification.started"
    VERIFICATION_PASSED = "verification.passed"
    VERIFICATION_FAILED = "verification.failed"
    ARTIFACT_CREATED = "artifact.created"
    POLICY_BLOCKED = "policy.blocked"
    APPROVAL_REQUIRED = "approval.required"
    APPROVAL_GRANTED = "approval.granted"
    APPROVAL_DENIED = "approval.denied"


class Event(StrictModel):
    """One immutable, machine-readable fact about a run."""

    event_id: str = Field(default_factory=lambda: new_id("evt"))
    run_id: str
    timestamp: datetime = Field(default_factory=utcnow)
    type: EventType
    actor: str = "engine"
    task_id: str | None = None
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
