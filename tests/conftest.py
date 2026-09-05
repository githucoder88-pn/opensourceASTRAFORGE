"""Shared fixtures. Every test is deterministic and offline."""

from __future__ import annotations

from pathlib import Path

import pytest

from astraforge.core.approvals import AutoApproveGate
from astraforge.core.config import Config
from astraforge.execution.engine import Engine
from astraforge.models.core import Goal
from astraforge.planning.base import Planner
from astraforge.providers.echo import EchoProvider
from astraforge.security.workspace import Workspace
from astraforge.storage.run_store import RunStore
from astraforge.tools import default_registry
from astraforge.tools.base import ToolContext
from astraforge.tools.registry import ToolRegistry
from astraforge.verification import default_verifiers
from astraforge.verification.base import VerificationContext


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path / "workspace")


@pytest.fixture
def provider() -> EchoProvider:
    return EchoProvider()


@pytest.fixture
def tools(provider: EchoProvider) -> ToolRegistry:
    return default_registry(provider)


@pytest.fixture
def tool_ctx(workspace: Workspace) -> ToolContext:
    import os

    return ToolContext(
        workspace=workspace,
        run_id="run_test",
        task_id="task_test",
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
    )


@pytest.fixture
def verify_ctx(workspace: Workspace) -> VerificationContext:
    return VerificationContext(workspace=workspace, run_id="run_test", task_id="task_test")


@pytest.fixture
def goal() -> Goal:
    return Goal(description="Test goal for the AstraForge engine")


@pytest.fixture
def make_engine(tmp_path: Path, provider: EchoProvider, tools: ToolRegistry):
    """Factory building an engine rooted in an isolated temp directory."""

    def _make(planner: Planner, **overrides: object) -> Engine:
        config = Config(storage_dir=str(tmp_path / ".astraforge"))
        return Engine(
            config=config,
            planner=planner,
            tools=tools,
            verifiers=default_verifiers(),
            provider=provider,
            store=RunStore(config.storage_dir),
            approval_gate=AutoApproveGate(),
            **overrides,  # type: ignore[arg-type]
        )

    return _make
