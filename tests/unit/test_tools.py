"""Tool contract, built-in tools and the registry."""

from __future__ import annotations

import pytest

from astraforge.models.core import FailureClass
from astraforge.tools.base import Tool, ToolContext, ToolError, ToolResult
from astraforge.tools.filesystem import ListDirTool, ReadFileTool, WriteFileTool
from astraforge.tools.interpreter import resolve_interpreter
from astraforge.tools.model import ModelGenerateTool
from astraforge.tools.registry import ToolRegistry
from astraforge.tools.shell import ShellTool


class _Boom(Tool):
    name = "boom"
    description = "always raises"

    def run(self, payload: dict[str, object], ctx: ToolContext) -> ToolResult:
        raise RuntimeError("kaboom")


class TestToolContract:
    def test_unexpected_exceptions_become_failures(self, tool_ctx: ToolContext) -> None:
        result, duration = _Boom().execute({}, tool_ctx)
        assert not result.ok
        assert result.failure_class is FailureClass.TOOL_FAILURE
        assert "kaboom" in (result.error or "")
        assert duration >= 0

    def test_missing_required_input_is_rejected(self, tool_ctx: ToolContext) -> None:
        result, _ = WriteFileTool().execute({"path": "a.txt"}, tool_ctx)
        assert not result.ok
        assert "content" in (result.error or "")

    def test_unknown_input_is_rejected(self) -> None:
        with pytest.raises(ToolError, match="unknown input"):
            WriteFileTool().validate_input(
                {"path": "a", "content": "b", "surprise": 1}
            )

    def test_wrong_type_is_rejected(self) -> None:
        with pytest.raises(ToolError, match="must be string"):
            WriteFileTool().validate_input({"path": 42, "content": "b"})

    def test_describe_exposes_permissions(self) -> None:
        described = ShellTool().describe()
        assert described["capabilities"] == ["shell.execute"]
        assert described["reversible"] is False
        assert described["risk"] == "HIGH"


class TestFilesystemTools:
    def test_write_then_read_round_trip(self, tool_ctx: ToolContext) -> None:
        write, _ = WriteFileTool().execute(
            {"path": "notes/a.md", "content": "hello"}, tool_ctx
        )
        assert write.ok
        assert write.produced_paths == ["notes/a.md"]
        assert len(write.output["sha256"]) == 64

        read, _ = ReadFileTool().execute({"path": "notes/a.md"}, tool_ctx)
        assert read.ok
        assert read.output["content"] == "hello"

    def test_write_outside_workspace_is_an_authorization_failure(
        self, tool_ctx: ToolContext
    ) -> None:
        result, _ = WriteFileTool().execute(
            {"path": "../escape.txt", "content": "x"}, tool_ctx
        )
        assert not result.ok
        assert result.failure_class is FailureClass.AUTHORIZATION_FAILURE

    def test_reading_a_missing_file_is_an_environment_failure(
        self, tool_ctx: ToolContext
    ) -> None:
        result, _ = ReadFileTool().execute({"path": "nope.txt"}, tool_ctx)
        assert result.failure_class is FailureClass.ENVIRONMENT_FAILURE

    def test_list_finds_written_files(self, tool_ctx: ToolContext) -> None:
        WriteFileTool().execute({"path": "x/y.txt", "content": "1"}, tool_ctx)
        result, _ = ListDirTool().execute({}, tool_ctx)
        assert result.ok
        assert "x/y.txt" in result.output["entries"]


class TestShellTool:
    def test_successful_command(self, tool_ctx: ToolContext) -> None:
        result, _ = ShellTool().execute({"command": ["echo", "hi"]}, tool_ctx)
        assert result.ok
        assert "hi" in result.output["stdout"]

    def test_nonzero_exit_is_a_failure(self, tool_ctx: ToolContext) -> None:
        result, _ = ShellTool().execute(
            {"command": ["python", "-c", "raise SystemExit(3)"]}, tool_ctx
        )
        assert not result.ok
        assert result.output["exit_code"] == 3

    def test_expected_nonzero_exit_is_a_success(self, tool_ctx: ToolContext) -> None:
        """Plans need to assert that something genuinely fails."""
        result, _ = ShellTool().execute(
            {"command": ["python", "-c", "raise SystemExit(1)"], "expect_exit_code": 1},
            tool_ctx,
        )
        assert result.ok

    def test_missing_binary_is_an_environment_failure(
        self, tool_ctx: ToolContext
    ) -> None:
        result, _ = ShellTool().execute(
            {"command": ["definitely-not-a-real-binary-xyz"]}, tool_ctx
        )
        assert result.failure_class is FailureClass.ENVIRONMENT_FAILURE

    def test_timeout_is_classified(self, tool_ctx: ToolContext) -> None:
        result, _ = ShellTool().execute(
            {"command": ["python", "-c", "import time; time.sleep(5)"], "timeout_s": 1},
            tool_ctx,
        )
        assert result.failure_class is FailureClass.TIMEOUT

    def test_no_shell_interpretation(self, tool_ctx: ToolContext) -> None:
        """`;` must be an argument, never a command separator."""
        result, _ = ShellTool().execute(
            {"command": ["echo", "a; echo pwned"]}, tool_ctx
        )
        assert result.ok
        # The whole string is echoed verbatim as ONE argument. A shell would
        # instead have run a second `echo pwned` and printed "a" then "pwned".
        assert result.output["stdout"] == "a; echo pwned\n"

    def test_output_is_redacted(self, tool_ctx: ToolContext) -> None:
        result, _ = ShellTool().execute(
            {
                "command": [
                    "python",
                    "-c",
                    "print('sk-abcdefghijklmnopqrstuvwxyz123456')",
                ]
            },
            tool_ctx,
        )
        assert "sk-abcdefghij" not in result.output["stdout"]

    def test_python_resolves_to_the_running_interpreter(self) -> None:
        import sys

        assert resolve_interpreter(["python", "-c", "1"])[0] == sys.executable
        assert resolve_interpreter(["echo", "hi"]) == ["echo", "hi"]
        assert resolve_interpreter([]) == []


class TestModelTool:
    def test_generates_and_saves(self, tool_ctx: ToolContext, provider) -> None:
        result, _ = ModelGenerateTool(provider).execute(
            {"prompt": "hello", "save_to": "out.md"}, tool_ctx
        )
        assert result.ok
        assert result.output["provider"] == "echo"
        assert result.produced_paths == ["out.md"]
        assert tool_ctx.workspace.read_text("out.md") == result.output["text"]

    def test_echo_provider_is_deterministic(self, tool_ctx: ToolContext, provider) -> None:
        first, _ = ModelGenerateTool(provider).execute({"prompt": "same"}, tool_ctx)
        second, _ = ModelGenerateTool(provider).execute({"prompt": "same"}, tool_ctx)
        assert first.output["text"] == second.output["text"]


class TestRegistry:
    def test_lookup_and_listing(self, tools: ToolRegistry) -> None:
        assert tools.has("fs.write")
        assert "shell.run" in tools.names()
        assert len(tools.describe()) == len(tools)

    def test_unknown_tool_error_lists_alternatives(self, tools: ToolRegistry) -> None:
        with pytest.raises(KeyError, match="available"):
            tools.get("fs.nope")

    def test_duplicate_registration_is_rejected(self) -> None:
        registry = ToolRegistry([WriteFileTool()])
        with pytest.raises(ValueError, match="already registered"):
            registry.register(WriteFileTool())

    def test_nameless_tool_is_rejected(self) -> None:
        class Nameless(_Boom):
            name = ""

        with pytest.raises(ValueError, match="must define a name"):
            ToolRegistry([Nameless()])
