"""Resource bounds on subprocess execution.

Regression suite for an audit finding: ``subprocess.run(capture_output=True)``
buffers the entire output stream in memory, so a runaway command OOM-killed the
engine before any truncation could apply. The failure surfaced as an
unclassified crash with zero captured evidence — the worst outcome for a system
whose product is evidence.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from astraforge.tools.base import ToolContext
from astraforge.tools.process import (
    OutputLimitExceeded,
    run_bounded,
)
from astraforge.tools.shell import ShellTool
from astraforge.verification.base import VerificationContext
from astraforge.verification.verifiers import CommandVerifier


def _env() -> dict[str, str]:
    import os

    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}


class TestRunBounded:
    def test_captures_normal_output(self, tmp_path: Path) -> None:
        result = run_bounded(
            [sys.executable, "-c", "print('hello')"],
            cwd=tmp_path,
            env=_env(),
            timeout_s=30,
        )
        assert result.exit_code == 0
        assert "hello" in result.stdout
        assert not result.truncated

    def test_captures_stderr_and_exit_code(self, tmp_path: Path) -> None:
        result = run_bounded(
            [
                sys.executable,
                "-c",
                "import sys; sys.stderr.write('bad'); sys.exit(3)",
            ],
            cwd=tmp_path,
            env=_env(),
            timeout_s=30,
        )
        assert result.exit_code == 3
        assert "bad" in result.stderr

    @pytest.mark.slow
    def test_memory_is_bounded_for_large_output(self, tmp_path: Path) -> None:
        """20MB of output must not be retained: only `max_capture` chars survive."""
        result = run_bounded(
            [
                sys.executable,
                "-c",
                "import sys\nfor _ in range(200): sys.stdout.write('x' * 100_000)",
            ],
            cwd=tmp_path,
            env=_env(),
            timeout_s=120,
            max_capture=1000,
        )
        assert result.exit_code == 0
        assert len(result.stdout) <= 1000
        assert result.stdout_truncated

    def test_truncation_keeps_the_tail(self, tmp_path: Path) -> None:
        """The tail matters: errors appear at the end of a log, not the start."""
        result = run_bounded(
            [sys.executable, "-c", "[print(f'line {i}') for i in range(20000)]"],
            cwd=tmp_path,
            env=_env(),
            timeout_s=60,
            max_capture=2000,
        )
        assert result.stdout.rstrip().endswith("line 19999")
        assert result.stdout_truncated

    @pytest.mark.slow
    def test_hard_limit_terminates_a_flooding_process(self, tmp_path: Path) -> None:
        """An unbounded writer is killed rather than allowed to exhaust memory."""
        with pytest.raises(OutputLimitExceeded):
            run_bounded(
                [
                    sys.executable,
                    "-c",
                    "import sys\nwhile True: sys.stdout.write('x' * 100_000)",
                ],
                cwd=tmp_path,
                env=_env(),
                timeout_s=120,
                max_stream_bytes=1_000_000,
            )

    def test_timeout_raises(self, tmp_path: Path) -> None:
        with pytest.raises(subprocess.TimeoutExpired):
            run_bounded(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                cwd=tmp_path,
                env=_env(),
                timeout_s=1,
            )

    def test_binary_output_does_not_crash(self, tmp_path: Path) -> None:
        """Non-UTF-8 bytes must be replaced, not raise a decode error."""
        result = run_bounded(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdout.buffer.write(bytes(range(256)))",
            ],
            cwd=tmp_path,
            env=_env(),
            timeout_s=30,
        )
        assert result.exit_code == 0
        assert isinstance(result.stdout, str)

    def test_stdin_is_closed_so_a_command_cannot_hang(self, tmp_path: Path) -> None:
        """A command reading stdin must hit EOF rather than block until timeout."""
        result = run_bounded(
            [sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"],
            cwd=tmp_path,
            env=_env(),
            timeout_s=10,
        )
        assert result.exit_code == 0
        assert "''" in result.stdout


class TestShellToolBounds:
    def test_runaway_output_is_classified_not_crashed(self, tool_ctx: ToolContext) -> None:
        result, _ = ShellTool().execute(
            {
                "command": [sys.executable, "-c", "[print('y' * 1000) for _ in range(3000)]"],
                "timeout_s": 120,
            },
            tool_ctx,
        )
        assert result.ok
        assert len(result.output["stdout"]) <= 20_000
        assert result.output["truncated"] is True

    def test_truncation_is_reported_as_evidence(self, tool_ctx: ToolContext) -> None:
        """Silent truncation would be a lie by omission in the report."""
        result, _ = ShellTool().execute(
            {"command": [sys.executable, "-c", "[print('z' * 1000) for _ in range(3000)]"]},
            tool_ctx,
        )
        assert any(e.kind == "command.truncated" for e in result.evidence)

    def test_secrets_in_command_arguments_are_redacted(
        self, tool_ctx: ToolContext
    ) -> None:
        """Audit finding: argv is echoed into evidence, the event log and the
        report, so a credential passed as an argument must be redacted too."""
        secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
        result, _ = ShellTool().execute(
            {"command": [sys.executable, "-c", "print(1)", "--token", secret]},
            tool_ctx,
        )
        assert result.ok
        assert secret not in " ".join(result.output["argv"])
        assert secret not in " ".join(e.summary + e.detail for e in result.evidence)

    def test_secrets_in_arguments_are_redacted_on_failure(
        self, tool_ctx: ToolContext
    ) -> None:
        secret = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
        result, _ = ShellTool().execute(
            {"command": ["definitely-not-real-binary", secret]}, tool_ctx
        )
        assert not result.ok
        assert secret not in (result.error or "")

    def test_binary_output_is_handled(self, tool_ctx: ToolContext) -> None:
        result, _ = ShellTool().execute(
            {
                "command": [
                    sys.executable,
                    "-c",
                    "import sys; sys.stdout.buffer.write(bytes(range(256)))",
                ]
            },
            tool_ctx,
        )
        assert result.ok, result.error


class TestVerifierBounds:
    def test_command_verifier_survives_large_output(
        self, verify_ctx: VerificationContext
    ) -> None:
        result = CommandVerifier().run(
            {
                "command": [sys.executable, "-c", "[print('q' * 1000) for _ in range(3000)]"],
                "expect_exit_code": 0,
            },
            verify_ctx,
        )
        assert result.passed

    def test_command_verifier_does_not_leak_secrets(
        self, verify_ctx: VerificationContext, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verifier subprocess output goes into the report; it must be redacted."""
        monkeypatch.setenv("AUDIT_TEST_API_KEY", "sk-abcdefghijklmnopqrstuvwxyz123456")
        result = CommandVerifier().run(
            {
                "command": [
                    sys.executable,
                    "-c",
                    "print('sk-abcdefghijklmnopqrstuvwxyz123456')",
                ],
                "expect_exit_code": 1,  # force failure so output lands in `failures`
            },
            verify_ctx,
        )
        blob = " ".join(result.failures) + " ".join(e.summary for e in result.evidence)
        assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in blob

    def test_verifier_redacts_secrets_in_command_arguments(
        self, verify_ctx: VerificationContext
    ) -> None:
        secret = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234"
        result = CommandVerifier().run(
            {
                "command": [sys.executable, "-c", "print(1)", "--key", secret],
                "expect_exit_code": 1,  # force failure so argv lands in `failures`
            },
            verify_ctx,
        )
        blob = " ".join(result.failures) + " ".join(e.summary for e in result.evidence)
        assert secret not in blob

    def test_verifier_subprocess_does_not_inherit_secrets(
        self, verify_ctx: VerificationContext, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AUDIT_SECRET_TOKEN", "leak-me-please-1234")
        result = CommandVerifier().run(
            {
                "command": [sys.executable, "-c", "import os; print(sorted(os.environ))"],
                "stdout_excludes": ["AUDIT_SECRET_TOKEN"],
            },
            verify_ctx,
        )
        assert result.passed, result.failures
