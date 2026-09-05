"""Planners, and the hard validation applied to model-generated plans."""

from __future__ import annotations

import json

import pytest

from astraforge.models.core import Goal
from astraforge.planning.base import PlanningError, load_plan_file
from astraforge.planning.heuristic import HeuristicPlanner
from astraforge.planning.model import ModelPlanner
from astraforge.planning.static import StaticPlanner
from astraforge.providers.base import Completion, Message, ModelProvider, ProviderError
from astraforge.tools.registry import ToolRegistry
from astraforge.verification import default_verifiers


class _CannedProvider(ModelProvider):
    """Returns a fixed string, so planner validation can be tested exactly."""

    name = "canned"

    def __init__(self, text: str) -> None:
        super().__init__("canned-1")
        self.text = text

    def complete(self, messages: list[Message], **kwargs: object) -> Completion:
        return Completion(text=self.text, model=self.model, provider=self.name)


class _BrokenProvider(ModelProvider):
    name = "broken"

    def complete(self, messages: list[Message], **kwargs: object) -> Completion:
        raise ProviderError("upstream is down")


VALID_PLAN = {
    "assumptions": ["a"],
    "objectives": ["o"],
    "tasks": [
        {
            "task_id": "task_one",
            "description": "write a file",
            "tool": "fs.write",
            "tool_input": {"path": "a.md", "content": "x"},
            "verification": [{"verifier": "file", "params": {"path": "a.md"}}],
        }
    ],
}


class TestHeuristicPlanner:
    def test_produces_a_valid_verified_graph(
        self, goal: Goal, tools: ToolRegistry
    ) -> None:
        plan = HeuristicPlanner().plan(goal, tools)
        assert plan.validate_graph() == []
        assert plan.goal_id == goal.goal_id
        assert all(t.verification for t in plan.tasks), "every task must be verifiable"

    def test_embeds_the_goal_text_in_the_brief(self, tools: ToolRegistry) -> None:
        goal = Goal(description="Ship a widget", constraints=["no network"])
        plan = HeuristicPlanner().plan(goal, tools)
        content = plan.tasks[0].tool_input["content"]
        assert "Ship a widget" in content
        assert "no network" in content

    def test_omits_the_model_task_when_no_model_tool_exists(
        self, goal: Goal
    ) -> None:
        from astraforge.tools import default_registry

        plan = HeuristicPlanner().plan(goal, default_registry(provider=None))
        assert not any(t.tool == "model.generate" for t in plan.tasks)
        assert plan.validate_graph() == []


class TestModelPlanner:
    def _planner(self, text: str) -> ModelPlanner:
        return ModelPlanner(_CannedProvider(text), default_verifiers().names())

    def test_parses_a_valid_plan(self, goal: Goal, tools: ToolRegistry) -> None:
        plan = self._planner(json.dumps(VALID_PLAN)).plan(goal, tools)
        assert [t.task_id for t in plan.tasks] == ["task_one"]

    def test_tolerates_code_fences_and_surrounding_prose(
        self, goal: Goal, tools: ToolRegistry
    ) -> None:
        text = f"Sure!\n```json\n{json.dumps(VALID_PLAN)}\n```\nHope that helps."
        assert self._planner(text).plan(goal, tools).tasks

    def test_rejects_non_json_output(self, goal: Goal, tools: ToolRegistry) -> None:
        with pytest.raises(PlanningError, match="no JSON object"):
            self._planner("I'd rather not.").plan(goal, tools)

    def test_rejects_malformed_json(self, goal: Goal, tools: ToolRegistry) -> None:
        with pytest.raises(PlanningError, match="invalid JSON"):
            self._planner('{"tasks": [,]}').plan(goal, tools)

    def test_rejects_a_plan_referencing_an_unknown_tool(
        self, goal: Goal, tools: ToolRegistry
    ) -> None:
        bad = json.loads(json.dumps(VALID_PLAN))
        bad["tasks"][0]["tool"] = "rm.everything"
        with pytest.raises(PlanningError, match="unknown tool"):
            self._planner(json.dumps(bad)).plan(goal, tools)

    def test_rejects_a_cyclic_plan(self, goal: Goal, tools: ToolRegistry) -> None:
        bad = json.loads(json.dumps(VALID_PLAN))
        bad["tasks"][0]["depends_on"] = ["task_one"]
        with pytest.raises(PlanningError, match="cycle"):
            self._planner(json.dumps(bad)).plan(goal, tools)

    def test_rejects_schema_violations(self, goal: Goal, tools: ToolRegistry) -> None:
        bad = json.loads(json.dumps(VALID_PLAN))
        bad["tasks"][0]["risk"] = "APOCALYPTIC"
        with pytest.raises(PlanningError, match="schema"):
            self._planner(json.dumps(bad)).plan(goal, tools)

    def test_surfaces_provider_errors(self, goal: Goal, tools: ToolRegistry) -> None:
        planner = ModelPlanner(_BrokenProvider("x"))
        with pytest.raises(PlanningError, match="upstream is down"):
            planner.plan(goal, tools)


class TestStaticPlanner:
    def test_loads_a_yaml_plan(self, tmp_path, goal: Goal, tools: ToolRegistry) -> None:
        import yaml

        path = tmp_path / "plan.yaml"
        path.write_text(yaml.safe_dump(VALID_PLAN))
        plan = StaticPlanner(path=path).plan(goal, tools)
        assert plan.tasks[0].task_id == "task_one"
        assert plan.goal_id == goal.goal_id

    def test_loads_a_json_plan(self, tmp_path, goal: Goal, tools: ToolRegistry) -> None:
        path = tmp_path / "plan.json"
        path.write_text(json.dumps(VALID_PLAN))
        assert StaticPlanner(path=path).plan(goal, tools).tasks

    def test_requires_exactly_one_source(self) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            StaticPlanner()

    def test_rejects_a_non_mapping_plan_file(self, tmp_path, goal: Goal) -> None:
        path = tmp_path / "plan.yaml"
        path.write_text("- just\n- a list\n")
        with pytest.raises(PlanningError, match="mapping"):
            load_plan_file(path, goal)


def test_the_shipped_example_plan_is_valid(tools: ToolRegistry, goal: Goal) -> None:
    """The flagship demo plan must always load and validate."""
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "examples/software_engineering/plan.yaml"
    plan = StaticPlanner(path=path).plan(goal, tools)
    assert len(plan.tasks) == 6
    assert all(t.verification for t in plan.tasks)


class TestPlanFileSafety:
    """Audit regression: plan files are untrusted input."""

    def test_yaml_cannot_execute_code(self, tmp_path, goal: Goal) -> None:
        """safe_load must refuse object construction, cleanly."""
        marker = tmp_path / "pwned.txt"
        path = tmp_path / "evil.yaml"
        path.write_text(
            f"!!python/object/apply:os.system ['touch {marker}']\n", encoding="utf-8"
        )
        with pytest.raises(PlanningError):
            load_plan_file(path, goal)
        assert not marker.exists(), "plan file executed code"

    def test_malformed_yaml_raises_planning_error_not_a_parser_error(
        self, tmp_path, goal: Goal
    ) -> None:
        """Callers handle PlanningError; a leaked yaml.YAMLError would crash them."""
        path = tmp_path / "bad.yaml"
        path.write_text("tasks: [unclosed\n", encoding="utf-8")
        with pytest.raises(PlanningError, match="not valid YAML"):
            load_plan_file(path, goal)

    def test_malformed_json_raises_planning_error(self, tmp_path, goal: Goal) -> None:
        path = tmp_path / "bad.json"
        path.write_text('{"tasks": [,]}', encoding="utf-8")
        with pytest.raises(PlanningError, match="not valid JSON"):
            load_plan_file(path, goal)

    def test_missing_plan_file_raises_planning_error(self, tmp_path, goal: Goal) -> None:
        with pytest.raises(PlanningError, match="cannot read plan file"):
            load_plan_file(tmp_path / "nope.yaml", goal)
