"""Verifier contract.

Verification is what separates AstraForge from "the model said it's done".
A verifier inspects the workspace and the tool output, and returns structured
:class:`~astraforge.models.core.VerificationResult` evidence.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from astraforge.models.core import (
    Evidence,
    VerificationResult,
    VerificationStatus,
)
from astraforge.security.workspace import Workspace
from astraforge.tools.base import ToolResult


@dataclass
class VerificationContext:
    """What a verifier is allowed to look at."""

    workspace: Workspace
    run_id: str
    task_id: str
    tool_result: ToolResult | None = None
    env: dict[str, str] | None = None


class Verifier(ABC):
    name: str = ""
    description: str = ""

    @abstractmethod
    def verify(
        self, params: dict[str, Any], ctx: VerificationContext
    ) -> VerificationResult:
        """Check the world and report structured evidence."""

    def run(self, params: dict[str, Any], ctx: VerificationContext) -> VerificationResult:
        """Verify, converting unexpected exceptions into a failure result."""
        try:
            return self.verify(dict(params), ctx)
        except Exception as exc:
            return self.failed([f"{type(exc).__name__}: {exc}"])

    # -- helpers ---------------------------------------------------------- #

    def passed(self, evidence: list[str], checks: int = 1) -> VerificationResult:
        return VerificationResult(
            verifier=self.name,
            status=VerificationStatus.PASSED,
            checks=checks,
            evidence=[Evidence(kind=self.name, summary=e) for e in evidence],
        )

    def failed(
        self, failures: list[str], evidence: list[str] | None = None, checks: int = 1
    ) -> VerificationResult:
        return VerificationResult(
            verifier=self.name,
            status=VerificationStatus.FAILED,
            checks=checks,
            failures=failures,
            evidence=[Evidence(kind=self.name, summary=e) for e in (evidence or [])],
        )

    def skipped(self, reason: str) -> VerificationResult:
        return VerificationResult(
            verifier=self.name,
            status=VerificationStatus.SKIPPED,
            evidence=[Evidence(kind=self.name, summary=reason)],
        )
