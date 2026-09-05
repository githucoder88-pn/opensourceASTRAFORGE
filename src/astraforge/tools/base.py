"""The tool contract.

A tool is the only way AstraForge affects the world. Every tool declares its
input schema, required capabilities, risk level, reversibility and timeout, so
the engine can enforce policy *before* anything happens.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from astraforge.models.core import Evidence, FailureClass, RiskLevel
from astraforge.security.capabilities import Capability
from astraforge.security.workspace import Workspace


@dataclass
class ToolContext:
    """Everything a tool is allowed to touch."""

    workspace: Workspace
    run_id: str
    task_id: str
    env: dict[str, str] = field(default_factory=dict)
    #: Capabilities the policy granted for this call. A tool that can exceed its
    #: own declared capabilities (a shell can open sockets) uses this to confine
    #: itself to what was actually authorised.
    granted: frozenset[Capability] = field(default_factory=frozenset)

    def has(self, capability: Capability) -> bool:
        """True if ``capability`` was granted for this call."""
        return capability in self.granted


@dataclass
class ToolResult:
    """Structured tool outcome. Tools report failure, they do not raise for it."""

    ok: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    failure_class: FailureClass | None = None
    evidence: list[Evidence] = field(default_factory=list)
    produced_paths: list[str] = field(default_factory=list)

    @classmethod
    def success(
        cls,
        output: dict[str, Any] | None = None,
        *,
        evidence: list[Evidence] | None = None,
        produced_paths: list[str] | None = None,
    ) -> ToolResult:
        return cls(
            ok=True,
            output=output or {},
            evidence=evidence or [],
            produced_paths=produced_paths or [],
        )

    @classmethod
    def failure(
        cls,
        error: str,
        failure_class: FailureClass = FailureClass.TOOL_FAILURE,
        *,
        output: dict[str, Any] | None = None,
        evidence: list[Evidence] | None = None,
    ) -> ToolResult:
        return cls(
            ok=False,
            error=error,
            failure_class=failure_class,
            output=output or {},
            evidence=evidence or [],
        )


class ToolError(Exception):
    """Raised for programmer errors (bad schema), not for expected failures."""


class Tool(ABC):
    """Base class for all tools."""

    name: str = ""
    description: str = ""
    capabilities: frozenset[Capability] = frozenset()
    risk: RiskLevel = RiskLevel.LOW
    reversible: bool = True
    timeout_s: int = 60
    input_schema: dict[str, Any] = {}

    def validate_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Minimal JSON-Schema-subset validation.

        Only ``required``/``properties``/``type`` are honoured. A full JSON
        Schema engine is a dependency the core does not need yet; tool inputs
        are produced by the planner and re-validated by the tool itself.
        """
        schema = self.input_schema or {}
        props: dict[str, Any] = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in payload:
                raise ToolError(f"{self.name}: missing required input {key!r}")
        unknown = sorted(set(payload) - set(props)) if props else []
        if unknown:
            raise ToolError(f"{self.name}: unknown input(s): {', '.join(unknown)}")
        types: dict[str, type | tuple[type, ...]] = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        for key, value in payload.items():
            expected = props.get(key, {}).get("type")
            if expected and expected in types and not isinstance(value, types[expected]):
                raise ToolError(
                    f"{self.name}: input {key!r} must be {expected}, "
                    f"got {type(value).__name__}"
                )
        return payload

    @abstractmethod
    def run(self, payload: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Execute the tool. Must not raise for expected failures."""

    def execute(self, payload: dict[str, Any], ctx: ToolContext) -> tuple[ToolResult, int]:
        """Validate, run and time the tool. Returns ``(result, duration_ms)``."""
        started = time.perf_counter()
        try:
            validated = self.validate_input(dict(payload))
            result = self.run(validated, ctx)
        except ToolError as exc:
            result = ToolResult.failure(str(exc), FailureClass.INVALID_OUTPUT)
        except TimeoutError as exc:
            result = ToolResult.failure(str(exc), FailureClass.TIMEOUT)
        except PermissionError as exc:
            result = ToolResult.failure(str(exc), FailureClass.AUTHORIZATION_FAILURE)
        except Exception as exc:
            result = ToolResult.failure(
                f"{type(exc).__name__}: {exc}", FailureClass.TOOL_FAILURE
            )
        return result, int((time.perf_counter() - started) * 1000)

    def describe(self) -> dict[str, Any]:
        """Machine-readable metadata, also used to brief the planner model."""
        return {
            "name": self.name,
            "description": self.description,
            "capabilities": sorted(c.value for c in self.capabilities),
            "risk": self.risk.value,
            "reversible": self.reversible,
            "timeout_s": self.timeout_s,
            "input_schema": self.input_schema,
        }
