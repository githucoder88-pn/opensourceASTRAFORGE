"""Deterministic template planner — the zero-configuration default.

It does not pretend to understand the goal. It produces an honest, small task
graph that any goal can be decomposed into: record the goal, draft an approach
document with whatever provider is configured, and verify that the artifacts
actually exist and are non-trivial.

Its value is that ``astraforge run "..."`` works offline, produces real
verified artifacts, and gives new users a plan they can copy into a file and
edit. For goal-aware decomposition, use :class:`~astraforge.planning.model.ModelPlanner`.
"""

from __future__ import annotations

import textwrap

from astraforge.models.core import Goal, Plan, RiskLevel, Task, VerificationSpec
from astraforge.planning.base import Planner, ensure_valid
from astraforge.tools.registry import ToolRegistry

BRIEF = "brief.md"
APPROACH = "approach.md"


class HeuristicPlanner(Planner):
    """Builds a fixed three-task graph around the user's goal."""

    name = "heuristic"

    def plan(self, goal: Goal, tools: ToolRegistry) -> Plan:
        criteria = "\n".join(f"- {c}" for c in goal.success_criteria) or "- (none stated)"
        constraints = "\n".join(f"- {c}" for c in goal.constraints) or "- (none stated)"
        brief = textwrap.dedent(
            f"""\
            # Goal brief

            {goal.description}

            ## Constraints
            {constraints}

            ## Success criteria
            {criteria}

            Goal id: `{goal.goal_id}`
            """
        )

        record = Task(
            task_id="task_brief",
            description="Record the goal, constraints and success criteria as a brief.",
            tool="fs.write",
            tool_input={"path": BRIEF, "content": brief},
            expected_output=f"{BRIEF} containing the goal statement",
            verification=[
                VerificationSpec(
                    verifier="file",
                    params={"path": BRIEF, "min_bytes": 20, "contains": ["# Goal brief"]},
                    description="brief exists and states the goal",
                )
            ],
        )

        tasks = [record]
        if tools.has("model.generate"):
            tasks.append(
                Task(
                    task_id="task_approach",
                    description="Draft an approach document for the goal.",
                    tool="model.generate",
                    tool_input={
                        "system": (
                            "You are a senior engineer. Produce a concise, concrete "
                            "Markdown plan: assumptions, steps, risks, and how each "
                            "step would be verified."
                        ),
                        "prompt": f"Goal: {goal.description}\n\nConstraints:\n{constraints}",
                        "save_to": APPROACH,
                    },
                    depends_on=[record.task_id],
                    expected_output=f"{APPROACH} with a written approach",
                    verification=[
                        VerificationSpec(
                            verifier="file",
                            params={"path": APPROACH, "min_bytes": 40},
                            description="approach document was written and is non-trivial",
                        ),
                        VerificationSpec(
                            verifier="tool_output",
                            params={"output_contains": {"path": APPROACH}},
                            description="model tool reported the expected output path",
                        ),
                    ],
                )
            )

        tasks.append(
            Task(
                task_id="task_inventory",
                description="Inventory the artifacts produced in the workspace.",
                tool="fs.list",
                tool_input={"path": "."},
                depends_on=[t.task_id for t in tasks],
                expected_output="a listing of every file produced",
                verification=[
                    VerificationSpec(
                        verifier="tool_output",
                        params={"output_contains": {"entries": BRIEF}},
                        description="the brief appears in the workspace inventory",
                    )
                ],
            )
        )

        plan = Plan(
            goal_id=goal.goal_id,
            assumptions=[
                "The goal can be advanced by producing written artifacts in the workspace.",
                "No network access or external credentials are required.",
            ],
            objectives=[
                "Capture the goal in a durable, reviewable form.",
                "Produce a verified approach artifact.",
            ],
            tasks=tasks,
            risk=RiskLevel.LOW,
        )
        return ensure_valid(plan, tools)
