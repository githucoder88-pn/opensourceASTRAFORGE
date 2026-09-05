"""Workspace containment and secret redaction."""

from __future__ import annotations

import pytest

from astraforge.models.core import RiskLevel
from astraforge.policies.policy import Decision, Policy
from astraforge.security.capabilities import Capability
from astraforge.security.redaction import REDACTED, redact
from astraforge.security.workspace import Workspace, WorkspaceEscapeError, is_noise


class TestWorkspace:
    def test_resolves_relative_paths_inside_root(self, workspace: Workspace) -> None:
        assert workspace.resolve("a/b.txt").is_relative_to(workspace.root)

    @pytest.mark.parametrize(
        "escape", ["../outside.txt", "a/../../outside.txt", "/etc/passwd"]
    )
    def test_blocks_escapes(self, workspace: Workspace, escape: str) -> None:
        with pytest.raises(WorkspaceEscapeError):
            workspace.resolve(escape)

    def test_write_creates_parents_and_hashes(self, workspace: Workspace) -> None:
        path = workspace.write_text("deep/nested/f.txt", "hello")
        assert path.read_text() == "hello"
        assert len(workspace.sha256(path)) == 64

    def test_write_outside_workspace_is_blocked(self, workspace: Workspace) -> None:
        with pytest.raises(WorkspaceEscapeError):
            workspace.write_text("../pwned.txt", "x")


class TestSnapshots:
    def test_detects_created_and_modified_files(self, workspace: Workspace) -> None:
        before = workspace.snapshot()
        workspace.write_text("new.txt", "hello")
        assert workspace.changed_since(before, workspace.snapshot()) == ["new.txt"]

    def test_ignores_build_and_cache_noise(self, workspace: Workspace) -> None:
        """__pycache__ and friends must never pollute the artifact trail."""
        workspace.write_text("__pycache__/mod.cpython-311.pyc", "junk")
        workspace.write_text(".pytest_cache/v/cache/lastfailed", "junk")
        workspace.write_text("real_output.md", "content")
        assert list(workspace.snapshot()) == ["real_output.md"]

    @pytest.mark.parametrize(
        "path",
        ["__pycache__/a.pyc", "sub/.pytest_cache/x", "a.pyc", ".git/config"],
    )
    def test_noise_paths_are_recognised(self, path: str) -> None:
        assert is_noise(path)

    @pytest.mark.parametrize("path", ["report.md", "src/main.py", "data/a.csv"])
    def test_real_outputs_are_not_noise(self, path: str) -> None:
        assert not is_noise(path)


class TestRedaction:
    @pytest.mark.parametrize(
        "secret",
        [
            "sk-abcdefghijklmnopqrstuvwxyz123456",
            "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
            "AKIAIOSFODNN7EXAMPLE",
        ],
    )
    def test_known_key_shapes_are_removed(self, secret: str) -> None:
        assert secret not in redact(f"token is {secret} ok")
        assert REDACTED in redact(f"token is {secret} ok")

    def test_redacts_live_environment_secrets(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MY_SERVICE_TOKEN", "hunter2-super-secret")
        assert "hunter2-super-secret" not in redact("leaked hunter2-super-secret here")

    def test_recurses_into_containers(self) -> None:
        key = "sk-abcdefghijklmnopqrstuvwxyz123456"
        out = redact({"a": [key], "b": {"c": key}})
        assert out == {"a": [REDACTED], "b": {"c": REDACTED}}

    def test_leaves_ordinary_values_alone(self) -> None:
        assert redact({"n": 42, "s": "hello"}) == {"n": 42, "s": "hello"}


class TestPolicy:
    def test_allows_granted_low_risk(self) -> None:
        verdict = Policy().evaluate({Capability.FILESYSTEM_READ}, RiskLevel.LOW)
        assert verdict.decision is Decision.ALLOW

    def test_denies_ungranted_capability(self) -> None:
        verdict = Policy().evaluate({Capability.NETWORK_REQUEST}, RiskLevel.LOW)
        assert verdict.decision is Decision.DENY
        assert "network.request" in verdict.reason

    def test_high_risk_requires_approval(self) -> None:
        verdict = Policy().evaluate({Capability.SHELL_EXECUTE}, RiskLevel.HIGH)
        assert verdict.decision is Decision.REQUIRE_APPROVAL

    def test_autonomous_mode_auto_approves_but_still_enforces_grants(self) -> None:
        policy = Policy(autonomous=True)
        assert policy.evaluate({Capability.SHELL_EXECUTE}, RiskLevel.HIGH).allowed
        # Autonomy must never bypass a missing capability grant.
        assert not policy.evaluate({Capability.GITHUB_WRITE}, RiskLevel.LOW).allowed

    def test_read_only_policy_blocks_writes(self) -> None:
        assert not Policy.read_only().evaluate(
            {Capability.FILESYSTEM_WRITE}, RiskLevel.LOW
        ).allowed

    def test_grant_returns_a_new_policy(self) -> None:
        base = Policy.read_only()
        granted = base.grant(Capability.NETWORK_REQUEST)
        assert granted.evaluate({Capability.NETWORK_REQUEST}, RiskLevel.LOW).allowed
        assert not base.evaluate({Capability.NETWORK_REQUEST}, RiskLevel.LOW).allowed
