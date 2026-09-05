"""Human-in-the-loop approval gates."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ApprovalRequest:
    task_id: str
    tool: str
    risk: str
    reason: str
    summary: str


class ApprovalGate(ABC):
    """Decides whether a policy-gated action may proceed."""

    name: str = ""

    @abstractmethod
    def request(self, req: ApprovalRequest) -> bool:
        """Return True to approve, False to reject."""


class DenyAllGate(ApprovalGate):
    """Default for unattended execution: nothing risky happens silently."""

    name = "deny"

    def request(self, req: ApprovalRequest) -> bool:
        return False


class AutoApproveGate(ApprovalGate):
    """Approves everything. Only for trusted, sandboxed, non-interactive runs."""

    name = "auto"

    def request(self, req: ApprovalRequest) -> bool:
        return True


@dataclass
class ScriptedGate(ApprovalGate):
    """Approvals decided up front by task id. Makes approval flows testable."""

    decisions: dict[str, bool] = field(default_factory=dict)
    default: bool = False
    name: str = "scripted"

    def request(self, req: ApprovalRequest) -> bool:
        return self.decisions.get(req.task_id, self.default)


class ConsoleGate(ApprovalGate):
    """Prompts the operator on stdin. Used by the interactive CLI."""

    name = "console"

    def request(self, req: ApprovalRequest) -> bool:
        import typer

        typer.secho(
            f"\nApproval required for task {req.task_id} "
            f"(tool={req.tool}, risk={req.risk})",
            fg=typer.colors.YELLOW,
            bold=True,
        )
        typer.echo(f"  reason:  {req.reason}")
        typer.echo(f"  action:  {req.summary}")
        return typer.confirm("  approve?", default=False)
