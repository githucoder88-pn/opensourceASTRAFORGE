"""Planner that executes a plan authored by a human.

This is the reproducible path: the plan is a checked-in file, so an example can
be re-run byte-for-byte with no model in the loop. It is what the test suite and
the ``examples/`` directory use.
"""

from __future__ import annotations

from pathlib import Path

from astraforge.models.core import Goal, Plan
from astraforge.planning.base import Planner, ensure_valid, load_plan_file
from astraforge.tools.registry import ToolRegistry


class StaticPlanner(Planner):
    """Returns a pre-authored plan loaded from disk or supplied in code."""

    name = "static"

    def __init__(self, plan: Plan | None = None, path: str | Path | None = None) -> None:
        if (plan is None) == (path is None):
            raise ValueError("provide exactly one of `plan` or `path`")
        self._plan = plan
        self._path = path

    def plan(self, goal: Goal, tools: ToolRegistry) -> Plan:
        plan = (
            self._plan.model_copy(deep=True, update={"goal_id": goal.goal_id})
            if self._plan is not None
            else load_plan_file(self._path, goal)  # type: ignore[arg-type]
        )
        return ensure_valid(plan, tools)
