"""Process isolation for tool execution.

The audit found a hole in the capability system. ``shell.run`` declares only
``shell.execute``, but a shell can read host files, write outside the workspace
and open network connections. So a policy that *denies* ``network.request``
still allowed a plan to run ``sh -c 'curl ...'`` — the capability was gated at
the front door while the shell held a key to the back one.

Path containment already stops writes through the ``fs.*`` tools, but it cannot
constrain a child process: once ``sh`` is running, the kernel, not AstraForge,
decides what it may touch.

This module adds the enforcement that was missing, using unprivileged Linux
namespaces plus POSIX resource limits. Both are applied in the child between
``fork`` and ``exec`` via ``preexec_fn``.

What is enforced
----------------

``network``
    A new empty network namespace (``CLONE_NEWNET``). The child gets no
    interfaces except loopback, so *no* egress is possible — this is a kernel
    guarantee, not a wrapper that can be argued with. Applied whenever the
    caller lacks the ``network.request`` capability.

``processes``, ``memory``, ``file size``, ``core dumps``
    ``RLIMIT_NPROC`` / ``RLIMIT_AS`` / ``RLIMIT_FSIZE`` / ``RLIMIT_CORE``, so a
    fork bomb, a memory balloon or a disk-filling loop is stopped by the kernel
    rather than by hoping the timeout fires first.

What is NOT enforced
--------------------

Filesystem *reads* of the host are still possible. Confining those needs a mount
namespace with a pivoted root, which requires either privileges or a helper such
as ``bwrap`` that is not guaranteed present. :func:`describe_isolation` reports
exactly what is active so documentation and reports can stay truthful rather
than claiming a sandbox that does not exist.

Availability
------------

Namespace isolation is Linux-only and needs unprivileged user namespaces
enabled. :func:`probe_support` detects this once, and callers degrade to
rlimits-only rather than failing. A missing sandbox must never silently look
like a working one, so the active level is recorded in the run's evidence.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import platform
import resource
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache

CLONE_NEWUSER = 0x10000000
CLONE_NEWNET = 0x40000000

#: Default ceilings. Generous enough for real builds and test suites, low enough
#: that a runaway process is stopped long before it destabilises the host.
DEFAULT_MAX_PROCESSES = 512
DEFAULT_MAX_MEMORY_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_MAX_FILE_BYTES = 512 * 1024 * 1024


class IsolationLevel(str, Enum):
    """How strongly a child process is confined."""

    #: No isolation applied (explicitly requested, or unsupported platform).
    NONE = "none"
    #: Resource limits only; namespaces unavailable.
    RLIMITS = "rlimits"
    #: Resource limits plus an empty network namespace.
    NETNS = "network-namespace"


@dataclass(frozen=True)
class SandboxSupport:
    """What this machine can actually enforce."""

    user_namespaces: bool
    network_namespaces: bool
    rlimits: bool
    reason: str = ""

    @property
    def best_level(self) -> IsolationLevel:
        if self.network_namespaces:
            return IsolationLevel.NETNS
        if self.rlimits:
            return IsolationLevel.RLIMITS
        return IsolationLevel.NONE


@dataclass(frozen=True)
class SandboxSpec:
    """Isolation requested for one execution."""

    #: Deny network egress. Ignored (with a recorded downgrade) if unsupported.
    deny_network: bool = True
    max_processes: int = DEFAULT_MAX_PROCESSES
    max_memory_bytes: int = DEFAULT_MAX_MEMORY_BYTES
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    #: Set False to opt out entirely (e.g. a tool that legitimately needs egress).
    enabled: bool = True

    @classmethod
    def unrestricted(cls) -> SandboxSpec:
        return cls(deny_network=False, enabled=False)


@dataclass
class SandboxReport:
    """What was actually applied, for the evidence trail."""

    level: IsolationLevel
    network_denied: bool
    limits: dict[str, int] = field(default_factory=dict)
    downgrades: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.level is IsolationLevel.NONE:
            return "no isolation applied"
        parts = [f"isolation={self.level.value}"]
        parts.append("network=denied" if self.network_denied else "network=allowed")
        if self.limits:
            parts.append("limits=" + ",".join(sorted(self.limits)))
        return " ".join(parts)


def _probe_child() -> int:
    """Attempt the unshare in a throwaway child; return 0 on success."""
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
    except OSError:
        return -1
    rc: int = libc.unshare(CLONE_NEWUSER | CLONE_NEWNET)
    return 0 if rc == 0 else (ctypes.get_errno() or -1)


@lru_cache(maxsize=1)
def probe_support() -> SandboxSupport:
    """Detect isolation support once per process.

    The probe runs in a forked child because ``unshare`` is irreversible for the
    calling process: testing it inline would put the engine itself into a
    network namespace and break the provider it needs to reach.
    """
    has_rlimits = hasattr(resource, "setrlimit")

    if platform.system() != "Linux":
        return SandboxSupport(
            False,
            False,
            has_rlimits,
            f"namespaces are Linux-only (this is {platform.system()})",
        )
    if not hasattr(os, "fork"):  # pragma: no cover - not reachable on Linux
        return SandboxSupport(False, False, has_rlimits, "os.fork unavailable")

    try:
        pid = os.fork()
    except OSError as exc:  # pragma: no cover - fork exhaustion
        return SandboxSupport(False, False, has_rlimits, f"fork failed: {exc}")

    if pid == 0:  # child
        os._exit(min(_probe_child() & 0xFF, 255))

    _, status = os.waitpid(pid, 0)
    code = os.waitstatus_to_exitcode(status)
    if code == 0:
        return SandboxSupport(True, True, has_rlimits)
    return SandboxSupport(
        False,
        False,
        has_rlimits,
        f"unprivileged user namespaces unavailable (errno {code}); "
        "network isolation is disabled",
    )


def build_preexec(
    spec: SandboxSpec, support: SandboxSupport
) -> tuple[Callable[[], None] | None, SandboxReport]:
    """Return a ``preexec_fn`` applying ``spec``, plus what it will enforce.

    The returned callable runs in the forked child before ``exec``. It must stay
    async-signal-safe in spirit: no logging, no allocation-heavy work, and any
    failure raises so the child dies rather than running unconfined.
    """
    report = SandboxReport(level=IsolationLevel.NONE, network_denied=False)

    if not spec.enabled:
        report.downgrades.append("isolation disabled by caller")
        return None, report

    want_netns = spec.deny_network
    can_netns = support.network_namespaces and want_netns
    if want_netns and not support.network_namespaces:
        report.downgrades.append(
            support.reason or "network namespaces unavailable on this platform"
        )

    limits: dict[str, int] = {}
    if support.rlimits:
        limits = {
            "processes": spec.max_processes,
            "memory_bytes": spec.max_memory_bytes,
            "file_bytes": spec.max_file_bytes,
        }

    if can_netns:
        report.level = IsolationLevel.NETNS
        report.network_denied = True
    elif limits:
        report.level = IsolationLevel.RLIMITS
    report.limits = limits

    if report.level is IsolationLevel.NONE:
        return None, report

    def _apply() -> None:  # pragma: no cover - executes in the forked child
        if can_netns:
            libc = ctypes.CDLL("libc.so.6", use_errno=True)
            if libc.unshare(CLONE_NEWUSER | CLONE_NEWNET) != 0:
                # Fail closed: never fall through to an unconfined exec.
                raise OSError(ctypes.get_errno(), "unshare failed; refusing to run unconfined")
            # A fresh netns has loopback DOWN. Local sockets are legitimate and
            # carry no egress risk, so bring it up when we are able to.
            with contextlib.suppress(OSError):
                _bring_up_loopback()
        if limits:
            resource.setrlimit(resource.RLIMIT_NPROC, (spec.max_processes, spec.max_processes))
            resource.setrlimit(
                resource.RLIMIT_AS, (spec.max_memory_bytes, spec.max_memory_bytes)
            )
            resource.setrlimit(
                resource.RLIMIT_FSIZE, (spec.max_file_bytes, spec.max_file_bytes)
            )
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    return _apply, report


def _bring_up_loopback() -> None:  # pragma: no cover - runs in the forked child
    """Set ``lo`` UP inside a new network namespace via SIOCSIFFLAGS."""
    import fcntl
    import socket
    import struct

    SIOCGIFFLAGS = 0x8913
    SIOCSIFFLAGS = 0x8914
    IFF_UP = 0x1

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        ifreq = struct.pack("16sh", b"lo", 0)
        flags = struct.unpack("16sh", fcntl.ioctl(sock.fileno(), SIOCGIFFLAGS, ifreq))[1]
        fcntl.ioctl(
            sock.fileno(), SIOCSIFFLAGS, struct.pack("16sh", b"lo", flags | IFF_UP)
        )
    finally:
        sock.close()


def describe_isolation() -> str:
    """Human-readable summary of what this machine can enforce."""
    support = probe_support()
    if support.network_namespaces:
        return (
            "network isolation: available (unprivileged user + network namespaces). "
            "Filesystem reads of the host are NOT confined."
        )
    return (
        f"network isolation: unavailable — {support.reason}. "
        "Resource limits still apply. Use the container image for stronger isolation."
    )


def run_isolated(
    argv: list[str],
    *,
    cwd: str | os.PathLike[str],
    env: dict[str, str],
    timeout_s: int,
    spec: SandboxSpec,
) -> tuple[subprocess.CompletedProcess[str], SandboxReport]:
    """Convenience wrapper used by tests; production callers use ``build_preexec``."""
    preexec, report = build_preexec(spec, probe_support())
    # argv list, never shell=True
    proc = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
        preexec_fn=preexec,
        stdin=subprocess.DEVNULL,
    )
    return proc, report


__all__ = [
    "DEFAULT_MAX_FILE_BYTES",
    "DEFAULT_MAX_MEMORY_BYTES",
    "DEFAULT_MAX_PROCESSES",
    "IsolationLevel",
    "SandboxReport",
    "SandboxSpec",
    "SandboxSupport",
    "build_preexec",
    "describe_isolation",
    "probe_support",
    "run_isolated",
]
