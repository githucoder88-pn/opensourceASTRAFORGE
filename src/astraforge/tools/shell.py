"""Shell execution, confined to the workspace and bounded by a timeout.

This tool intentionally does *not* use ``shell=True``: commands are given as an
argument list, so there is no shell metacharacter interpretation and no
accidental command chaining from model-generated strings.
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

MAX_CAPTURE = 20_000


class ShellTool(Tool):
    """Run a command (argv list or simple string) inside the workspace."""

    name = "shell.run"
    description = (
        "Run a command inside the workspace. Provide argv as a list, or a simple "
        "command string which is split with shlex (no shell metacharacters)."
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
            proc = subprocess.run(
                argv,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env={**ctx.env, "PATH": ctx.env.get("PATH", "/usr/bin:/bin")},
            )
        except FileNotFoundError:
            return ToolResult.failure(
                f"command not found: {argv[0]}", FailureClass.ENVIRONMENT_FAILURE
            )
        except subprocess.TimeoutExpired:
            return ToolResult.failure(
                f"command timed out after {timeout}s: {' '.join(argv)}",
                FailureClass.TIMEOUT,
            )

        stdout = redact(proc.stdout[-MAX_CAPTURE:])
        stderr = redact(proc.stderr[-MAX_CAPTURE:])
        output = {
            "argv": argv,
            "exit_code": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }
        evidence = [
            Evidence(
                kind="command.executed",
                summary=f"`{' '.join(argv)}` exited {proc.returncode}",
                detail=(stdout or stderr)[-2000:],
                data={"exit_code": proc.returncode},
            )
        ]
        if proc.returncode != expected:
            return ToolResult.failure(
                f"command exited {proc.returncode} (expected {expected})",
                FailureClass.TOOL_FAILURE,
                output=output,
                evidence=evidence,
            )
        return ToolResult.success(output, evidence=evidence)
