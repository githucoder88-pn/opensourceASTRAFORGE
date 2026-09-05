"""Verifiers must produce structured evidence and fail when reality disagrees."""

from __future__ import annotations

from astraforge.models.core import VerificationStatus
from astraforge.security.workspace import Workspace
from astraforge.tools.base import ToolResult
from astraforge.verification import default_verifiers
from astraforge.verification.base import VerificationContext, Verifier
from astraforge.verification.verifiers import (
    CommandVerifier,
    FileVerifier,
    HumanApprovalVerifier,
    SchemaVerifier,
    TestVerifier,
    ToolOutputVerifier,
)


class TestFileVerifier:
    def test_passes_for_matching_file(
        self, workspace: Workspace, verify_ctx: VerificationContext
    ) -> None:
        workspace.write_text("r.md", "# Report\nfindings here")
        result = FileVerifier().run(
            {"path": "r.md", "contains": ["# Report"], "matches": [r"^findings"]},
            verify_ctx,
        )
        assert result.status is VerificationStatus.PASSED
        assert result.checks == 4
        assert result.evidence

    def test_fails_when_file_is_absent(self, verify_ctx: VerificationContext) -> None:
        result = FileVerifier().run({"path": "ghost.md"}, verify_ctx)
        assert result.status is VerificationStatus.FAILED
        assert "does not exist" in result.failures[0]

    def test_fails_on_missing_content(
        self, workspace: Workspace, verify_ctx: VerificationContext
    ) -> None:
        workspace.write_text("r.md", "nothing useful")
        result = FileVerifier().run(
            {"path": "r.md", "contains": ["REQUIRED"]}, verify_ctx
        )
        assert result.status is VerificationStatus.FAILED

    def test_fails_when_file_is_too_small(
        self, workspace: Workspace, verify_ctx: VerificationContext
    ) -> None:
        workspace.write_text("r.md", "x")
        result = FileVerifier().run({"path": "r.md", "min_bytes": 100}, verify_ctx)
        assert result.status is VerificationStatus.FAILED


class TestCommandVerifier:
    def test_passes_on_expected_exit_code(self, verify_ctx: VerificationContext) -> None:
        result = CommandVerifier().run(
            {"command": ["python", "-c", "print('ok')"], "stdout_contains": ["ok"]},
            verify_ctx,
        )
        assert result.status is VerificationStatus.PASSED

    def test_fails_on_unexpected_exit_code(self, verify_ctx: VerificationContext) -> None:
        result = CommandVerifier().run(
            {"command": ["python", "-c", "raise SystemExit(2)"]}, verify_ctx
        )
        assert result.status is VerificationStatus.FAILED

    def test_stdout_excludes_catches_environment_errors(
        self, verify_ctx: VerificationContext
    ) -> None:
        """Guards the false positive where a broken env looks like a test failure."""
        result = CommandVerifier().run(
            {
                "command": ["python", "-c", "print('No module named pytest')"],
                "stdout_excludes": ["No module named"],
            },
            verify_ctx,
        )
        assert result.status is VerificationStatus.FAILED

    def test_missing_binary_fails_cleanly(self, verify_ctx: VerificationContext) -> None:
        result = CommandVerifier().run({"command": ["no-such-binary-xyz"]}, verify_ctx)
        assert result.status is VerificationStatus.FAILED


class TestTestVerifier:
    def test_reports_pytest_summary(
        self, workspace: Workspace, verify_ctx: VerificationContext
    ) -> None:
        workspace.write_text("test_x.py", "def test_a():\n    assert True\n")
        result = TestVerifier().run(
            {"command": ["python", "-m", "pytest", "-q", "test_x.py"]}, verify_ctx
        )
        assert result.status is VerificationStatus.PASSED
        assert any("pytest: 1 passed" in e.summary for e in result.evidence)

    def test_detects_a_genuinely_failing_suite(
        self, workspace: Workspace, verify_ctx: VerificationContext
    ) -> None:
        workspace.write_text("test_y.py", "def test_a():\n    assert False\n")
        result = TestVerifier().run(
            {"command": ["python", "-m", "pytest", "-q", "test_y.py"]}, verify_ctx
        )
        assert result.status is VerificationStatus.FAILED


class TestSchemaVerifier:
    def test_passes_for_valid_json_with_keys(
        self, workspace: Workspace, verify_ctx: VerificationContext
    ) -> None:
        workspace.write_text("d.json", '{"a": 1, "b": 2}')
        result = SchemaVerifier().run(
            {"path": "d.json", "required_keys": ["a", "b"]}, verify_ctx
        )
        assert result.status is VerificationStatus.PASSED

    def test_fails_on_invalid_json(
        self, workspace: Workspace, verify_ctx: VerificationContext
    ) -> None:
        workspace.write_text("d.json", "{not json")
        result = SchemaVerifier().run({"path": "d.json"}, verify_ctx)
        assert result.status is VerificationStatus.FAILED

    def test_fails_on_missing_key(
        self, workspace: Workspace, verify_ctx: VerificationContext
    ) -> None:
        workspace.write_text("d.json", '{"a": 1}')
        result = SchemaVerifier().run(
            {"path": "d.json", "required_keys": ["a", "missing"]}, verify_ctx
        )
        assert result.status is VerificationStatus.FAILED


class TestToolOutputVerifier:
    def test_skips_without_a_tool_result(self, verify_ctx: VerificationContext) -> None:
        assert (
            ToolOutputVerifier().run({}, verify_ctx).status is VerificationStatus.SKIPPED
        )

    def test_checks_output_values(self, verify_ctx: VerificationContext) -> None:
        verify_ctx.tool_result = ToolResult.success({"exit_code": 0, "path": "a/b.md"})
        assert (
            ToolOutputVerifier()
            .run(
                {"output_equals": {"exit_code": 0}, "output_contains": {"path": "b.md"}},
                verify_ctx,
            )
            .status
            is VerificationStatus.PASSED
        )

    def test_fails_when_the_tool_failed(self, verify_ctx: VerificationContext) -> None:
        verify_ctx.tool_result = ToolResult.failure("nope")
        assert (
            ToolOutputVerifier().run({}, verify_ctx).status is VerificationStatus.FAILED
        )


class TestHumanApproval:
    def test_requires_a_recorded_approval(self, verify_ctx: VerificationContext) -> None:
        assert (
            HumanApprovalVerifier().run({}, verify_ctx).status
            is VerificationStatus.FAILED
        )
        verify_ctx.env = {"approval:task_test": "granted"}
        assert (
            HumanApprovalVerifier().run({}, verify_ctx).status
            is VerificationStatus.PASSED
        )


class _Exploding(Verifier):
    name = "exploding"

    def verify(self, params, ctx):  # type: ignore[no-untyped-def]
        raise RuntimeError("verifier bug")


def test_a_broken_verifier_fails_closed(verify_ctx: VerificationContext) -> None:
    """A verifier that crashes must never be treated as a pass."""
    result = _Exploding().run({}, verify_ctx)
    assert result.status is VerificationStatus.FAILED
    assert "verifier bug" in result.failures[0]


def test_default_registry_contents() -> None:
    registry = default_verifiers()
    assert set(registry.names()) == {
        "command",
        "file",
        "human_approval",
        "schema",
        "tests",
        "tool_output",
    }
