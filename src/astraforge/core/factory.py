"""Assemble an :class:`~astraforge.execution.engine.Engine` from configuration.

Keeping wiring in one place means the CLI, tests, examples and any future web
server all build the engine identically.
"""

from __future__ import annotations

from pathlib import Path

from astraforge.core.approvals import (
    ApprovalGate,
    AutoApproveGate,
    ConsoleGate,
    DenyAllGate,
)
from astraforge.core.config import Config, ConfigError
from astraforge.execution.engine import Engine
from astraforge.models.core import Goal
from astraforge.planning.base import Planner
from astraforge.planning.heuristic import HeuristicPlanner
from astraforge.planning.model import ModelPlanner
from astraforge.planning.static import StaticPlanner
from astraforge.providers import get_provider
from astraforge.providers.base import ModelProvider
from astraforge.storage.run_store import RunStore
from astraforge.tools import default_registry
from astraforge.tools.registry import ToolRegistry
from astraforge.verification import VerifierRegistry, default_verifiers

_GATES: dict[str, type[ApprovalGate]] = {
    "console": ConsoleGate,
    "deny": DenyAllGate,
    "auto": AutoApproveGate,
}


def build_provider(config: Config) -> ModelProvider:
    """Instantiate the configured provider."""
    return get_provider(config.model.provider, config.model.name, **config.model.options())


def build_planner(
    config: Config, provider: ModelProvider, verifiers: VerifierRegistry
) -> Planner:
    """Instantiate the configured planner."""
    if config.planner == "model":
        return ModelPlanner(provider, verifier_names=verifiers.names())
    if config.planner == "static":
        if not config.plan_file:
            raise ConfigError("planner: static requires `plan_file` to be set")
        path = Path(config.plan_file)
        if not path.exists():
            raise ConfigError(f"plan_file not found: {path}")
        return StaticPlanner(path=path)
    return HeuristicPlanner()


def build_engine(
    config: Config,
    *,
    planner: Planner | None = None,
    tools: ToolRegistry | None = None,
    approval_gate: ApprovalGate | None = None,
) -> Engine:
    """Build a fully wired engine from ``config``."""
    provider = build_provider(config)
    verifiers = default_verifiers()
    registry = tools or default_registry(provider)
    return Engine(
        config=config,
        planner=planner or build_planner(config, provider, verifiers),
        tools=registry,
        verifiers=verifiers,
        provider=provider,
        policy=config.security.policy(),
        store=RunStore(config.storage_dir),
        approval_gate=approval_gate or _GATES[config.security.approval_gate](),
    )


def make_goal(
    description: str,
    constraints: list[str] | None = None,
    success_criteria: list[str] | None = None,
) -> Goal:
    """Create a :class:`Goal`, rejecting empty descriptions early."""
    text = description.strip()
    if not text:
        raise ValueError("goal description must not be empty")
    return Goal(
        description=text,
        constraints=constraints or [],
        success_criteria=success_criteria or [],
    )
