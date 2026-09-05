"""Planner contract and plan (de)serialisation."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from astraforge.models.core import Goal, Plan
from astraforge.tools.registry import ToolRegistry


class PlanningError(RuntimeError):
    """A plan could not be produced or is structurally invalid."""


class Planner(ABC):
    """Turns a goal into a validated task graph."""

    name: str = ""

    @abstractmethod
    def plan(self, goal: Goal, tools: ToolRegistry) -> Plan:
        """Produce a plan. Implementations should call :func:`ensure_valid`."""


def ensure_valid(plan: Plan, tools: ToolRegistry) -> Plan:
    """Reject plans with cycles, dangling dependencies or unknown tools."""
    problems = plan.validate_graph()
    problems += [
        f"task {t.task_id} references unknown tool {t.tool!r}"
        for t in plan.tasks
        if not tools.has(t.tool)
    ]
    if problems:
        raise PlanningError("invalid plan: " + "; ".join(problems))
    return plan


def plan_from_mapping(data: dict[str, Any], goal: Goal) -> Plan:
    """Build a :class:`Plan` from a plain mapping (JSON/YAML/model output)."""
    payload = dict(data)
    payload["goal_id"] = goal.goal_id
    payload.pop("plan_id", None)
    try:
        return Plan.model_validate(payload)
    except ValidationError as exc:
        raise PlanningError(f"plan does not match schema: {exc}") from exc


def load_plan_file(path: str | Path, goal: Goal) -> Plan:
    """Load a plan from a ``.json``, ``.yaml`` or ``.yml`` file."""
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    data = json.loads(text) if file.suffix == ".json" else yaml.safe_load(text)
    if not isinstance(data, dict):
        raise PlanningError(f"{file} must contain a mapping at the top level")
    return plan_from_mapping(data, goal)
