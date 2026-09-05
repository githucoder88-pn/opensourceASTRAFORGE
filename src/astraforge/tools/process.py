"""Bounded subprocess execution.

``subprocess.run(capture_output=True)`` buffers the *entire* output stream in
memory before returning. A task that emits gigabytes therefore exhausts RAM and
kills the engine before any truncation can happen — the failure is an
unclassified crash with no captured evidence, which is the worst possible
outcome for a system whose product is evidence.

This module streams both pipes through a bounded ring buffer instead: memory is
capped regardless of how much the child writes, the process is killed once it
exceeds the cap, and the truncation is reported as evidence rather than hidden.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from astraforge.security.sandbox import (
    SandboxReport,
    SandboxSpec,
    build_preexec,
    probe_support,
)

#: Per-stream capture limit. Output beyond this is discarded, keeping the tail.
DEFAULT_MAX_CAPTURE = 20_000

#: Hard limit on bytes read from a stream before the child is killed outright.
#: Generous enough for legitimate chatty builds, small enough to never OOM.
DEFAULT_MAX_STREAM_BYTES = 50 * 1024 * 1024


class OutputLimitExceeded(RuntimeError):
    """A child process produced more output than the hard stream limit allows."""


@dataclass
class ProcessResult:
    """Outcome of a bounded subprocess execution."""

    exit_code: int
    stdout: str
    stderr: str
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    #: What isolation was actually applied, for the evidence trail.
    sandbox: SandboxReport | None = None

    @property
    def truncated(self) -> bool:
        return self.stdout_truncated or self.stderr_truncated


class _BoundedReader(threading.Thread):
    """Drains a pipe, keeping only the last ``max_capture`` characters."""

    def __init__(
        self,
        stream: object,
        max_capture: int,
        max_bytes: int,
        on_limit: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(daemon=True)
        self._stream = stream
        self._max_capture = max_capture
        self._max_bytes = max_bytes
        self._on_limit = on_limit
        self._chunks: list[bytes] = []
        self._kept = 0
        self.total_bytes = 0
        self.truncated = False
        self.limit_exceeded = False

    def run(self) -> None:
        read = getattr(self._stream, "read", None)
        if read is None:  # pragma: no cover - defensive
            return
        try:
            while True:
                chunk = read(8192)
                if not chunk:
                    break
                self.total_bytes += len(chunk)
                if self.total_bytes > self._max_bytes:
                    self.limit_exceeded = True
                    self.truncated = True
                    # Kill immediately: merely stopping the read would leave the
                    # main thread blocked in wait() until the timeout expires.
                    if self._on_limit is not None:
                        self._on_limit()
                    break
                self._chunks.append(chunk)
                self._kept += len(chunk)
                # Keep the buffer near the capture limit; we only need the tail.
                while self._kept > self._max_capture * 4 and len(self._chunks) > 1:
                    self._kept -= len(self._chunks.pop(0))
                    self.truncated = True
        except (ValueError, OSError):  # pragma: no cover - pipe closed on kill
            pass

    def text(self) -> str:
        raw = b"".join(self._chunks)
        decoded = raw.decode("utf-8", errors="replace")
        if len(decoded) > self._max_capture:
            self.truncated = True
            return decoded[-self._max_capture :]
        return decoded


def run_bounded(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_s: int,
    max_capture: int = DEFAULT_MAX_CAPTURE,
    max_stream_bytes: int = DEFAULT_MAX_STREAM_BYTES,
    sandbox: SandboxSpec | None = None,
) -> ProcessResult:
    """Run ``argv`` with bounded memory use.

    Raises :class:`subprocess.TimeoutExpired` on timeout, :class:`FileNotFoundError`
    if the binary is missing, and :class:`OutputLimitExceeded` if the child floods
    a stream past ``max_stream_bytes``.
    """
    # Isolation is applied in the forked child, before exec. If it cannot be
    # applied the child raises and dies rather than running unconfined.
    preexec, sandbox_report = build_preexec(
        sandbox if sandbox is not None else SandboxSpec.unrestricted(),
        probe_support(),
    )

    # argv list, never shell=True
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        preexec_fn=preexec,
    )

    def _terminate() -> None:
        """Kill the whole process group so children do not outlive the parent."""
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        with contextlib.suppress(ProcessLookupError, OSError):
            proc.kill()

    out_reader = _BoundedReader(proc.stdout, max_capture, max_stream_bytes, _terminate)
    err_reader = _BoundedReader(proc.stderr, max_capture, max_stream_bytes, _terminate)
    out_reader.start()
    err_reader.start()

    try:
        exit_code = proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _terminate()
        proc.wait()
        out_reader.join(timeout=5)
        err_reader.join(timeout=5)
        raise
    finally:
        for pipe in (proc.stdout, proc.stderr):
            if pipe is not None:
                with contextlib.suppress(OSError):
                    pipe.close()

    out_reader.join(timeout=5)
    err_reader.join(timeout=5)

    if out_reader.limit_exceeded or err_reader.limit_exceeded:
        _terminate()
        raise OutputLimitExceeded(
            f"command produced more than {max_stream_bytes} bytes of output "
            f"and was terminated: {' '.join(argv)}"
        )

    return ProcessResult(
        exit_code=exit_code,
        stdout=out_reader.text(),
        stderr=err_reader.text(),
        stdout_truncated=out_reader.truncated,
        stderr_truncated=err_reader.truncated,
        sandbox=sandbox_report,
    )
