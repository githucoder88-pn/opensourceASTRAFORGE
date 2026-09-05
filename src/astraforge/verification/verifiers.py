"""Built-in deterministic verifiers."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from typing import Any

from astraforge.models.core import Evidence, VerificationResult
from astraforge.tools.interpreter import resolve_interpreter
from astraforge.verification.base import VerificationContext, Verifier


class FileVerifier(Verifier):
    """Assert a file exists and optionally check size and content."""

    name = "file"
    description = (
        "Checks that `path` exists, is non-empty (min_bytes), and optionally "
        "contains `contains` substrings or matches `matches` regexes."
    )

    def verify(self, params: dict[str, Any], ctx: VerificationContext) -> VerificationResult:
        rel = params["path"]
        path = ctx.workspace.resolve(rel)
        failures: list[str] = []
        evidence: list[str] = []
        checks = 1

        if not path.is_file():
            return self.failed([f"expected file does not exist: {rel}"])
        size = path.stat().st_size
        evidence.append(f"{rel} exists ({size} bytes)")

        min_bytes = int(params.get("min_bytes", 1))
        checks += 1
        if size < min_bytes:
            failures.append(f"{rel} is {size} bytes, expected at least {min_bytes}")

        text: str | None = None
        needles = params.get("contains") or []
        patterns = params.get("matches") or []
        if needles or patterns:
            text = path.read_text(encoding="utf-8", errors="replace")
        for needle in needles:
            checks += 1
            if needle in (text or ""):
                evidence.append(f"{rel} contains {needle!r}")
            else:
                failures.append(f"{rel} does not contain {needle!r}")
        for pattern in patterns:
            checks += 1
            if re.search(pattern, text or "", re.MULTILINE):
                evidence.append(f"{rel} matches /{pattern}/")
            else:
                failures.append(f"{rel} does not match /{pattern}/")

        return (
            self.failed(failures, evidence, checks)
            if failures
            else self.passed(evidence, checks)
        )


class CommandVerifier(Verifier):
    """Run a command and assert its exit code (and optionally its output)."""

    name = "command"
    description = "Runs `command` and asserts exit code and optional output substrings."

    def verify(self, params: dict[str, Any], ctx: VerificationContext) -> VerificationResult:
        raw = params["command"]
        argv = resolve_interpreter(
            [str(a) for a in raw] if isinstance(raw, list) else shlex.split(str(raw))
        )
        cwd = ctx.workspace.resolve(params.get("cwd", "."))
        expected = int(params.get("expect_exit_code", 0))
        timeout = int(params.get("timeout_s", 300))
        try:
            proc = subprocess.run(
                argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
            )
        except FileNotFoundError:
            return self.failed([f"command not found: {argv[0]}"])
        except subprocess.TimeoutExpired:
            return self.failed([f"verification command timed out after {timeout}s"])

        combined = (proc.stdout + proc.stderr).strip()
        failures: list[str] = []
        checks = 1
        evidence = [f"`{' '.join(argv)}` exited {proc.returncode}"]
        if combined:
            evidence.append(f"output: {combined[-400:]}")
        if proc.returncode != expected:
            failures.append(
                f"`{' '.join(argv)}` exited {proc.returncode}, expected {expected}: "
                f"{combined[-800:]}"
            )
        for needle in params.get("stdout_contains") or []:
            checks += 1
            if needle in combined:
                evidence.append(f"output contains {needle!r}")
            else:
                failures.append(f"output does not contain {needle!r}")
        # Guards against false positives: an environment error and a genuine
        # test failure can both exit non-zero, so plans can rule the former out.
        for needle in params.get("stdout_excludes") or []:
            checks += 1
            if needle in combined:
                failures.append(f"output unexpectedly contains {needle!r}")
            else:
                evidence.append(f"output does not contain {needle!r}")
        return (
            self.failed(failures, evidence, checks)
            if failures
            else self.passed(evidence, checks)
        )


class TestVerifier(CommandVerifier):
    """Run a test suite. Defaults to pytest, and surfaces its summary line."""

    name = "tests"
    description = "Runs a test command (default: pytest -q) and reports the summary."

    def verify(self, params: dict[str, Any], ctx: VerificationContext) -> VerificationResult:
        params = dict(params)
        params.setdefault("command", ["python", "-m", "pytest", "-q"])
        result = super().verify(params, ctx)
        result.verifier = self.name
        blob = " ".join(
            [f"{e.summary} {e.detail}" for e in result.evidence] + result.failures
        )
        match = re.search(r"\d+ (?:passed|failed)(?:, \d+ (?:passed|failed))*", blob)
        if match:
            result.evidence.append(
                Evidence(kind=self.name, summary=f"pytest: {match.group(0)}")
            )
        return result


class SchemaVerifier(Verifier):
    """Assert a JSON file parses and contains required top-level keys."""

    name = "schema"
    description = "Parses `path` as JSON and checks `required_keys` are present."

    def verify(self, params: dict[str, Any], ctx: VerificationContext) -> VerificationResult:
        rel = params["path"]
        path = ctx.workspace.resolve(rel)
        if not path.is_file():
            return self.failed([f"file does not exist: {rel}"])
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return self.failed([f"{rel} is not valid JSON: {exc}"])
        evidence = [f"{rel} is valid JSON ({type(data).__name__})"]
        failures: list[str] = []
        required = params.get("required_keys") or []
        checks = 1 + len(required)
        for key in required:
            if isinstance(data, dict) and key in data:
                evidence.append(f"key present: {key}")
            else:
                failures.append(f"missing required key: {key}")
        return (
            self.failed(failures, evidence, checks)
            if failures
            else self.passed(evidence, checks)
        )


class ToolOutputVerifier(Verifier):
    """Assert something about the tool result of the task being verified."""

    name = "tool_output"
    description = "Checks the task's tool succeeded and its output contains expectations."

    def verify(self, params: dict[str, Any], ctx: VerificationContext) -> VerificationResult:
        result = ctx.tool_result
        if result is None:
            return self.skipped("no tool result available for this task")
        if not result.ok:
            return self.failed([f"tool reported failure: {result.error}"])
        failures: list[str] = []
        evidence = ["tool reported success"]
        checks = 1
        for key, expected in (params.get("output_equals") or {}).items():
            checks += 1
            actual = result.output.get(key)
            if actual == expected:
                evidence.append(f"output.{key} == {expected!r}")
            else:
                failures.append(f"output.{key} is {actual!r}, expected {expected!r}")
        for key, needle in (params.get("output_contains") or {}).items():
            checks += 1
            if needle in str(result.output.get(key, "")):
                evidence.append(f"output.{key} contains {needle!r}")
            else:
                failures.append(f"output.{key} does not contain {needle!r}")
        return (
            self.failed(failures, evidence, checks)
            if failures
            else self.passed(evidence, checks)
        )


class HumanApprovalVerifier(Verifier):
    """Records that a human approved the result.

    The engine resolves approvals through the approval gate before the task
    runs; this verifier turns that decision into evidence in the report.
    """

    name = "human_approval"
    description = "Requires a recorded human approval for the task."

    def verify(self, params: dict[str, Any], ctx: VerificationContext) -> VerificationResult:
        env = ctx.env or {}
        key = f"approval:{ctx.task_id}"
        if env.get(key) == "granted":
            return self.passed([f"human approval recorded for {ctx.task_id}"])
        return self.failed([f"no human approval recorded for {ctx.task_id}"])
