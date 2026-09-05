"""Shell execution, confined to the workspace and bounded by a timeout.

This tool does **not** use ``shell=True``: commands are given as an argument
list, so the tool itself never interprets shell metacharacters. Note that a plan
may still invoke a shell explicitly (``["sh", "-c", "..."]``); the guarantee is
that AstraForge does not add an interpreter you did not ask for, not that a
shell can never run. See ``docs/concepts/safety.md``.

Output is captured through a bounded reader so a runaway command cannot exhaust
memory — see :mod:`astraforge.tools.process`.
"""

from __future__ import annotations

import shlex
import subprocess
from typing import Any

from astraforge.models.core import Evidence, FailureClass, RiskLevel
from astraforge.security.capabilities import Capability
from astraforge.security.redaction import redact
from astraforge.tools.base import Tool, ToolContext, ToolResult
from astraforge.tools.interpreter import resolve_interpreter
from astraforge.tools.process import (
    DEFAULT_MAX_CAPTURE,
    OutputLimitExceeded,
    run_bounded,
)

MAX_CAPTURE = DEFAULT_MAX_CAPTURE


class ShellTool(Tool):
    """Run a command (argv list or simple string) inside the workspace."""

    name = "shell.run"
    description = (
        "Run a command inside the workspace. Provide argv as a list, or a simple "
        "command string which is split with shlex."
    )
    capabilities = frozenset({Capability.SHELL_EXECUTE})
    risk = RiskLevel.HIGH
    reversible = False
    timeout_s = 300
    input_schema = {
        "type": "object",
        "required": ["command"],
        "properties": {
            "command": {"description": "argv list or command string"},
            "cwd": {"type": "string"},
            "timeout_s": {"type": "integer"},
            "expect_exit_code": {"type": "integer"},
        },
    }

    def run(self, payload: dict[str, Any], ctx: ToolContext) -> ToolResult:
        raw = payload["command"]
        argv = [str(a) for a in raw] if isinstance(raw, list) else shlex.split(str(raw))
        if not argv:
            return ToolResult.failure("empty command", FailureClass.INVALID_OUTPUT)
        argv = resolve_interpreter(argv)
        cwd = ctx.workspace.resolve(payload.get("cwd", "."))
        timeout = int(payload.get("timeout_s", self.timeout_s))
        expected = int(payload.get("expect_exit_code", 0))

        try:
            proc = run_bounded(
                argv,
                cwd=cwd,
                env={**ctx.env, "PATH": ctx.env.get("PATH", "/usr/bin:/bin")},
                timeout_s=timeout,
            )
        except FileNotFoundError:
            return ToolResult.failure(
                f"command not found: {redact(argv[0])}", FailureClass.ENVIRONMENT_FAILURE
            )
        except PermissionError:
            return ToolResult.failure(
                f"not executable: {redact(argv[0])}", FailureClass.ENVIRONMENT_FAILURE
            )
        except subprocess.TimeoutExpired:
            return ToolResult.failure(
                f"command timed out after {timeout}s: {redact(' '.join(argv))}",
                FailureClass.TIMEOUT,
            )
        except OutputLimitExceeded as exc:
            return ToolResult.failure(str(exc), FailureClass.ENVIRONMENT_FAILURE)

        stdout = redact(proc.stdout)
        stderr = redact(proc.stderr)
        # argv is echoed into evidence, the event log and the report, so a
        # credential passed as an argument must be redacted like any output.
        shown_argv = redact(argv)
        shown = " ".join(shown_argv)
        output = {
            "argv": shown_argv,
            "exit_code": proc.exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "truncated": proc.truncated,
        }
        evidence = [
            Evidence(
                kind="command.executed",
                summary=f"`{shown}` exited {proc.exit_code}",
                detail=(stdout or stderr)[-2000:],
                data={"exit_code": proc.exit_code},
            )
        ]
        if proc.truncated:
            evidence.append(
                Evidence(
                    kind="command.truncated",
                    summary=(
                        f"output exceeded {MAX_CAPTURE} characters; "
                        "only the tail was captured"
                    ),
                )
            )
        if proc.exit_code != expected:
            return ToolResult.failure(
                f"command exited {proc.exit_code} (expected {expected})",
                FailureClass.TOOL_FAILURE,
                output=output,
                evidence=evidence,
            )
        return ToolResult.success(output, evidence=evidence)
