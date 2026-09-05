"""Schema and task-graph validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from astraforge.models.core import (
    FailureClass,
    Goal,
    Plan,
    RiskLevel,
    Task,
    TaskStatus,
)


def _task(task_id: str, deps: list[str] | None = None) -> Task:
    return Task(
        task_id=task_id, description="t", tool="fs.write", depends_on=deps or []
    )


def test_risk_levels_are_ordered() -> None:
    assert RiskLevel.LOW.rank < RiskLevel.MEDIUM.rank < RiskLevel.HIGH.rank
    assert RiskLevel.HIGH.rank < RiskLevel.CRITICAL.rank


def test_terminal_statuses() -> None:
    assert TaskStatus.COMPLETED.terminal
    assert TaskStatus.FAILED.terminal
    assert not TaskStatus.RUNNING.terminal
    assert not TaskStatus.PENDING.terminal


@pytest.mark.parametrize(
    ("failure", "recoverable"),
    [
        (FailureClass.TIMEOUT, True),
        (FailureClass.TEST_FAILURE, True),
        (FailureClass.POLICY_BLOCK, False),
        (FailureClass.HUMAN_REJECTION, False),
        (FailureClass.AUTHORIZATION_FAILURE, False),
    ],
)
def test_failure_recoverability(failure: FailureClass, recoverable: bool) -> None:
    assert failure.recoverable is recoverable


def test_unknown_fields_are_rejected() -> None:
    """Malformed model output must fail loudly, not be silently accepted."""
    with pytest.raises(ValidationError):
        Goal.model_validate({"description": "x", "totally_made_up": 1})


def test_valid_graph_has_no_problems() -> None:
    plan = Plan(goal_id="g", tasks=[_task("a"), _task("b", ["a"])])
    assert plan.validate_graph() == []


def test_detects_dangling_dependency() -> None:
    plan = Plan(goal_id="g", tasks=[_task("a", ["nope"])])
    assert any("unknown task nope" in p for p in plan.validate_graph())


def test_detects_duplicate_task_ids() -> None:
    plan = Plan(goal_id="g", tasks=[_task("a"), _task("a")])
    assert any("duplicate" in p for p in plan.validate_graph())


def test_detects_cycle() -> None:
    plan = Plan(goal_id="g", tasks=[_task("a", ["b"]), _task("b", ["a"])])
    assert any("cycle" in p for p in plan.validate_graph())


def test_detects_self_cycle() -> None:
    plan = Plan(goal_id="g", tasks=[_task("a", ["a"])])
    assert any("cycle" in p for p in plan.validate_graph())


def test_empty_plan_is_invalid() -> None:
    assert any("no tasks" in p for p in Plan(goal_id="g").validate_graph())


def test_task_lookup_raises_for_unknown_id() -> None:
    plan = Plan(goal_id="g", tasks=[_task("a")])
    assert plan.task("a").task_id == "a"
    with pytest.raises(KeyError):
        plan.task("missing")
