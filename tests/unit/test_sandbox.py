"""Process isolation.

Regression suite for an audit finding: ``shell.run`` declares only
``shell.execute``, but a shell can open sockets. A policy that denied
``network.request`` therefore still allowed ``sh -c "curl ..."`` to reach the
internet — the capability was checked at the front door while the shell held a
key to the back one.

These tests assert the kernel-enforced behaviour, not merely that a flag was set.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path

import pytest

from astraforge.models.core import RiskLevel
from astraforge.policies.policy import Policy
from astraforge.security.capabilities import Capability
from astraforge.security.sandbox import (
    IsolationLevel,
    SandboxSpec,
    build_preexec,
    describe_isolation,
    probe_support,
    run_isolated,
)
from astraforge.tools.base import ToolContext
from astraforge.tools.shell import ShellTool

#: Connects to a public resolver by IP, so DNS is not a confounder.
NET_PROBE = (
    "import socket\n"
    "try:\n"
    "    s = socket.socket(); s.settimeout(4); s.connect(('1.1.1.1', 53)); s.close()\n"
    "    print('REACHED')\n"
    "except Exception:\n"
    "    print('BLOCKED')"
)

needs_netns = pytest.mark.skipif(
    not probe_support().network_namespaces,
    reason="unprivileged network namespaces unavailable on this machine",
)
linux_only = pytest.mark.skipif(platform.system() != "Linux", reason="Linux-only")


class TestSupportProbe:
    def test_probe_is_cached_and_consistent(self) -> None:
        assert probe_support() is probe_support()

    def test_probe_does_not_isolate_the_calling_process(self) -> None:
        """unshare is irreversible, so the probe must run in a forked child.

        If it leaked, the engine itself would lose network access and could no
        longer reach a model provider.
        """
        import socket

        probe_support()
        sock = socket.socket()
        sock.settimeout(4)
        try:
            sock.connect(("1.1.1.1", 53))
        except OSError:
            pytest.skip("no outbound network in this environment")
        finally:
            sock.close()

    def test_description_is_honest_about_filesystem(self) -> None:
        """Docs must not imply a filesystem sandbox that does not exist."""
        text = describe_isolation()
        if probe_support().network_namespaces:
            assert "NOT confined" in text
        else:
            assert "unavailable" in text


class TestSpecToReport:
    def test_disabled_spec_applies_nothing(self) -> None:
        preexec, report = build_preexec(SandboxSpec.unrestricted(), probe_support())
        assert preexec is None
        assert report.level is IsolationLevel.NONE

    def test_unsupported_namespaces_downgrade_and_say_why(self) -> None:
        """A missing sandbox must never look like a working one."""
        from astraforge.security.sandbox import SandboxSupport

        support = SandboxSupport(False, False, True, reason="namespaces unavailable here")
        _, report = build_preexec(SandboxSpec(deny_network=True), support)
        assert report.level is IsolationLevel.RLIMITS
        assert report.network_denied is False
        assert report.downgrades and "unavailable" in report.downgrades[0]

    @needs_netns
    def test_denying_network_selects_the_namespace_level(self) -> None:
        _, report = build_preexec(SandboxSpec(deny_network=True), probe_support())
        assert report.level is IsolationLevel.NETNS
        assert report.network_denied is True
        assert not report.downgrades


@linux_only
class TestKernelEnforcement:
    @needs_netns
    def test_network_is_actually_blocked(self, tmp_path: Path) -> None:
        proc, report = run_isolated(
            [sys.executable, "-c", NET_PROBE],
            cwd=tmp_path,
            env={"PATH": "/usr/bin:/bin"},
            timeout_s=30,
            spec=SandboxSpec(deny_network=True),
        )
        assert "BLOCKED" in proc.stdout
        assert report.network_denied

    def test_network_works_when_allowed(self, tmp_path: Path) -> None:
        proc, _ = run_isolated(
            [sys.executable, "-c", NET_PROBE],
            cwd=tmp_path,
            env={"PATH": "/usr/bin:/bin"},
            timeout_s=30,
            spec=SandboxSpec(deny_network=False),
        )
        if "BLOCKED" in proc.stdout:
            pytest.skip("no outbound network in this environment")
        assert "REACHED" in proc.stdout

    @needs_netns
    def test_ordinary_work_still_functions_inside_the_sandbox(
        self, tmp_path: Path
    ) -> None:
        """Isolation is useless if it breaks legitimate tasks."""
        script = (
            "import pathlib, json\n"
            "p = pathlib.Path('out.json'); p.write_text(json.dumps({'n': sum(range(100))}))\n"
            "print('wrote', p.read_text())"
        )
        proc, _ = run_isolated(
            [sys.executable, "-c", script],
            cwd=tmp_path,
            env={"PATH": "/usr/bin:/bin"},
            timeout_s=30,
            spec=SandboxSpec(deny_network=True),
        )
        assert proc.returncode == 0, proc.stderr
        assert "4950" in proc.stdout
        assert (tmp_path / "out.json").is_file()

    @needs_netns
    def test_subprocesses_still_work_inside_the_sandbox(self, tmp_path: Path) -> None:
        """Test runners spawn children; the process limit must not be too tight."""
        script = (
            "import subprocess, sys\n"
            "r = subprocess.run([sys.executable, '-c', \"print('child ok')\"],"
            " capture_output=True, text=True)\n"
            "print(r.stdout.strip())"
        )
        proc, _ = run_isolated(
            [sys.executable, "-c", script],
            cwd=tmp_path,
            env={"PATH": "/usr/bin:/bin"},
            timeout_s=30,
            spec=SandboxSpec(deny_network=True),
        )
        assert proc.returncode == 0, proc.stderr
        assert "child ok" in proc.stdout


@linux_only
class TestFailClosed:
    """If isolation cannot be applied, the child must die, not run unconfined."""

    @needs_netns
    def test_unshare_failure_kills_the_child(self, tmp_path: Path) -> None:
        import subprocess

        from astraforge.security import sandbox as sb

        spec = SandboxSpec(deny_network=True)
        preexec, report = build_preexec(spec, probe_support())
        assert preexec is not None
        assert report.network_denied

        # Simulate the kernel refusing the unshare at exec time.
        class _FailingLibc:
            def unshare(self, _flags: int) -> int:
                return -1

        original = sb.ctypes.CDLL
        sb.ctypes.CDLL = lambda *a, **k: _FailingLibc()  # type: ignore[assignment]
        try:
            with pytest.raises(subprocess.SubprocessError):
                subprocess.run(
                    [sys.executable, "-c", "print('SHOULD NOT RUN')"],
                    cwd=tmp_path,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                    preexec_fn=preexec,
                )
        finally:
            sb.ctypes.CDLL = original  # type: ignore[assignment]


class TestShellToolHonoursCapabilities:
    """The end-to-end property: the grant controls the kernel behaviour."""

    def _ctx(self, tmp_path: Path, granted: frozenset[Capability]) -> ToolContext:
        from astraforge.security.workspace import Workspace

        return ToolContext(
            workspace=Workspace(tmp_path),
            run_id="run_x",
            task_id="task_x",
            env={"PATH": "/usr/bin:/bin"},
            granted=granted,
        )

    @linux_only
    @needs_netns
    def test_shell_cannot_reach_network_without_the_grant(self, tmp_path: Path) -> None:
        ctx = self._ctx(tmp_path, frozenset({Capability.SHELL_EXECUTE}))
        result, _ = ShellTool().execute(
            {"command": [sys.executable, "-c", NET_PROBE]}, ctx
        )
        assert result.ok, result.error
        assert "BLOCKED" in result.output["stdout"]
        assert result.output["isolation"] == IsolationLevel.NETNS.value

    @linux_only
    def test_shell_reaches_network_with_the_grant(self, tmp_path: Path) -> None:
        ctx = self._ctx(
            tmp_path, frozenset({Capability.SHELL_EXECUTE, Capability.NETWORK_REQUEST})
        )
        result, _ = ShellTool().execute(
            {"command": [sys.executable, "-c", NET_PROBE]}, ctx
        )
        assert result.ok, result.error
        if "BLOCKED" in result.output["stdout"]:
            pytest.skip("no outbound network in this environment")
        assert "REACHED" in result.output["stdout"]

    def test_isolation_is_recorded_as_evidence(self, tmp_path: Path) -> None:
        """A reader of the report must be able to see what was enforced."""
        ctx = self._ctx(tmp_path, frozenset({Capability.SHELL_EXECUTE}))
        result, _ = ShellTool().execute(
            {"command": [sys.executable, "-c", "print('hi')"]}, ctx
        )
        assert result.ok
        assert any(e.kind == "sandbox.applied" for e in result.evidence)

    def test_default_policy_does_not_grant_network(self) -> None:
        """Guards the premise: if this ever changes, the tests above are moot."""
        assert Capability.NETWORK_REQUEST not in Policy().granted
        verdict = Policy().evaluate({Capability.NETWORK_REQUEST}, RiskLevel.LOW)
        assert verdict.decision.value == "deny"
