"""Configuration validation, run storage, memory and the event bus."""

from __future__ import annotations

import pytest

from astraforge.core.config import Config, ConfigError
from astraforge.events.bus import EventBus, JsonlEventSink, MemoryEventSink
from astraforge.memory.store import MemoryScope, MemoryStore
from astraforge.models.core import Goal, RiskLevel, Run, RunStatus
from astraforge.models.events import EventType
from astraforge.security.capabilities import Capability
from astraforge.storage.run_store import RunStore


class TestConfig:
    def test_defaults_are_offline_and_safe(self) -> None:
        config = Config()
        assert config.model.provider == "echo"
        assert config.security.approval_at_or_above is RiskLevel.HIGH
        policy = config.security.policy()
        assert Capability.NETWORK_REQUEST not in policy.granted
        assert Capability.GITHUB_WRITE not in policy.granted

    def test_missing_file_falls_back_to_defaults(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        assert Config.load().project == "astraforge-project"

    def test_explicit_missing_file_is_an_error(self, tmp_path) -> None:
        with pytest.raises(ConfigError, match="not found"):
            Config.load(tmp_path / "nope.yaml")

    def test_unknown_keys_are_rejected(self, tmp_path) -> None:
        path = tmp_path / "c.yaml"
        path.write_text("projct: typo\n")
        with pytest.raises(ConfigError, match="invalid configuration"):
            Config.load(path)

    def test_invalid_yaml_is_reported_clearly(self, tmp_path) -> None:
        path = tmp_path / "c.yaml"
        path.write_text("a: [unclosed\n")
        with pytest.raises(ConfigError, match="not valid YAML"):
            Config.load(path)

    def test_invalid_capability_lists_valid_options(self) -> None:
        config = Config.model_validate({"security": {"capabilities": ["fs.everything"]}})
        with pytest.raises(ConfigError, match="Valid capabilities"):
            config.security.policy()

    def test_limits_are_bounded(self, tmp_path) -> None:
        path = tmp_path / "c.yaml"
        path.write_text("limits:\n  max_task_attempts: 0\n")
        with pytest.raises(ConfigError):
            Config.load(path)

    def test_round_trips_through_yaml(self) -> None:
        import yaml

        original = Config(project="demo", planner="model")
        assert Config.model_validate(yaml.safe_load(original.to_yaml())) == original

    def test_config_never_contains_secret_values(self) -> None:
        """Only the NAME of an env var may be configured, never its value."""
        text = Config(
            model={"provider": "openai", "api_key_env": "OPENAI_API_KEY"}  # type: ignore[arg-type]
        ).to_yaml()
        assert "api_key_env: OPENAI_API_KEY" in text
        assert "api_key:" not in text.replace("api_key_env:", "")


class TestRunStore:
    def test_save_and_load(self, tmp_path) -> None:
        store = RunStore(tmp_path)
        run = Run(goal=Goal(description="g"), status=RunStatus.COMPLETED)
        store.create(run.run_id)
        store.save_run(run)
        assert store.load_run(run.run_id).goal.description == "g"

    def test_missing_run_raises(self, tmp_path) -> None:
        with pytest.raises(FileNotFoundError):
            RunStore(tmp_path).load_run("run_nope")

    def test_resolves_latest_and_prefixes(self, tmp_path) -> None:
        store = RunStore(tmp_path)
        ids = []
        for i in range(3):
            run = Run(goal=Goal(description=f"g{i}"))
            store.create(run.run_id)
            store.save_run(run)
            ids.append(run.run_id)
        assert store.resolve("latest") in ids
        assert store.resolve(ids[0]) == ids[0]
        assert store.resolve(ids[0][:8]) == ids[0]

    def test_resolve_reports_no_runs(self, tmp_path) -> None:
        with pytest.raises(FileNotFoundError, match="no runs"):
            RunStore(tmp_path).resolve("latest")

    def test_ambiguous_prefix_is_an_error(self, tmp_path) -> None:
        store = RunStore(tmp_path)
        for _ in range(2):
            run = Run(goal=Goal(description="g"))
            store.create(run.run_id)
            store.save_run(run)
        with pytest.raises(ValueError, match="ambiguous"):
            store.resolve("run_")


class TestEventBus:
    def test_fans_out_to_sinks(self, tmp_path) -> None:
        memory, jsonl = MemoryEventSink(), JsonlEventSink(tmp_path / "e.jsonl")
        bus = EventBus("run_1", [memory, jsonl])
        bus.emit(EventType.RUN_STARTED, "go")
        assert len(memory.events) == 1
        assert jsonl.read()[0].message == "go"

    def test_a_broken_sink_does_not_break_the_run(self, capsys) -> None:
        class Broken:
            def handle(self, event: object) -> None:
                raise RuntimeError("sink is down")

        memory = MemoryEventSink()
        bus = EventBus("run_1", [Broken(), memory])
        bus.emit(EventType.RUN_STARTED, "still works")
        assert len(memory.events) == 1  # the good sink still received it
        assert "sink is down" in capsys.readouterr().err


class TestMemory:
    def test_scopes_are_separate_and_deletable(self, tmp_path) -> None:
        store = MemoryStore(tmp_path)
        store.set(MemoryScope.PROJECT, "lang", "python")
        store.set(MemoryScope.PREFERENCES, "lang", "rust")
        assert store.get(MemoryScope.PROJECT, "lang") == "python"
        assert store.get(MemoryScope.PREFERENCES, "lang") == "rust"

        assert store.delete(MemoryScope.PROJECT, "lang") is True
        assert store.delete(MemoryScope.PROJECT, "lang") is False
        assert store.get(MemoryScope.PROJECT, "lang") is None

    def test_nothing_is_stored_implicitly(self, tmp_path) -> None:
        store = MemoryStore(tmp_path)
        assert store.all(MemoryScope.PROJECT) == {}
        assert not store.path(MemoryScope.PROJECT).exists()

    def test_clear_removes_the_whole_scope(self, tmp_path) -> None:
        store = MemoryStore(tmp_path)
        store.set(MemoryScope.WORKFLOWS, "k", "v")
        store.clear(MemoryScope.WORKFLOWS)
        assert store.all(MemoryScope.WORKFLOWS) == {}
