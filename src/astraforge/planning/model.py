"""Model-driven planner.

The model is asked for JSON matching the :class:`~astraforge.models.core.Plan`
schema. Its output is treated as untrusted input: it is parsed, schema-validated
and graph-validated, and every referenced tool must exist. A malformed plan is a
planning failure, never something the engine tries to execute anyway.
"""

from __future__ import annotations

import json
import re
from typing import Any

from astraforge.models.core import Goal, Plan
from astraforge.planning.base import (
    Planner,
    PlanningError,
    ensure_valid,
    plan_from_mapping,
)
from astraforge.providers.base import Message, ModelProvider, ProviderError
from astraforge.tools.registry import ToolRegistry

SYSTEM_PROMPT = """\
You are the planner for AstraForge, a goal-execution engine.

Return ONLY a JSON object with this shape:

{
  "assumptions": [string],
  "objectives": [string],
  "risk": "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
  "tasks": [
    {
      "task_id": "task_snake_case",
      "description": string,
      "tool": <one of the available tool names>,
      "tool_input": object matching that tool's input schema,
      "depends_on": [task_id],
      "expected_output": string,
      "verification": [
        {"verifier": <verifier name>, "params": object, "description": string}
      ],
      "risk": "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
      "max_attempts": integer
    }
  ]
}

Rules:
- Use only the listed tools and verifiers.
- Every task must have at least one verification that could actually fail.
- Prefer deterministic tools over model generation when the work is mechanical.
- The task graph must be acyclic and dependencies must reference declared task ids.
- All file paths are workspace-relative. Never use absolute paths.
- Output JSON only. No prose, no code fences.
"""


class ModelPlanner(Planner):
    """Asks a :class:`ModelProvider` for a plan and validates it hard."""

    name = "model"

    def __init__(
        self, provider: ModelProvider, verifier_names: list[str] | None = None
    ) -> None:
        self.provider = provider
        self.verifier_names = verifier_names or []

    def plan(self, goal: Goal, tools: ToolRegistry) -> Plan:
        prompt = self._prompt(goal, tools)
        try:
            completion = self.provider.complete(
                [Message("system", SYSTEM_PROMPT), Message("user", prompt)]
            )
        except ProviderError as exc:
            raise PlanningError(f"planner provider failed: {exc}") from exc

        data = self._extract_json(completion.text)
        plan = plan_from_mapping(data, goal)
        return ensure_valid(plan, tools)

    def _prompt(self, goal: Goal, tools: ToolRegistry) -> str:
        return json.dumps(
            {
                "goal": goal.description,
                "constraints": goal.constraints,
                "success_criteria": goal.success_criteria,
                "available_tools": tools.describe(),
                "available_verifiers": self.verifier_names,
            },
            indent=2,
        )

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        """Pull the first JSON object out of a completion, tolerating code fences."""
        cleaned = re.sub(r"^\s*```(?:json)?|```\s*$", "", text.strip(), flags=re.MULTILINE)
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise PlanningError(
                "planner returned no JSON object. First 200 chars: "
                f"{cleaned[:200]!r}"
            )
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise PlanningError(f"planner returned invalid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise PlanningError("planner JSON must be an object")
        return data
