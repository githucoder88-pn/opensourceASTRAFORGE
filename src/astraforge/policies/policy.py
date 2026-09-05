"""Bounded autonomy.

A :class:`Policy` answers one question before every tool call: *may this run,
must a human approve it, or is it forbidden?* The answer depends on the tool's
declared capabilities and risk level, never on what the model asserts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from astraforge.models.core import RiskLevel
from astraforge.security.capabilities import Capability


class Decision(str, Enum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


@dataclass(frozen=True)
class PolicyDecision:
    decision: Decision
    reason: str

    @property
    def allowed(self) -> bool:
        return self.decision is Decision.ALLOW


DEFAULT_CAPABILITIES: frozenset[Capability] = frozenset(
    {
        Capability.FILESYSTEM_READ,
        Capability.FILESYSTEM_WRITE,
        Capability.SHELL_EXECUTE,
        Capability.MODEL_INVOKE,
    }
)


@dataclass
class Policy:
    """Capability allowlist plus a risk threshold above which humans decide.

    Defaults are deliberately conservative: local filesystem and shell inside
    the workspace are allowed, while network, GitHub writes and browser
    interaction must be granted explicitly.
    """

    granted: frozenset[Capability] = field(default=DEFAULT_CAPABILITIES)
    approval_at_or_above: RiskLevel = RiskLevel.HIGH
    autonomous: bool = False
    """If True, approval-requiring actions are auto-approved (CI / unattended use)."""

    @classmethod
    def permissive(cls) -> Policy:
        """Every capability granted. Intended for trusted local experiments."""
        return cls(granted=frozenset(Capability), approval_at_or_above=RiskLevel.CRITICAL)

    @classmethod
    def read_only(cls) -> Policy:
        return cls(
            granted=frozenset({Capability.FILESYSTEM_READ, Capability.MODEL_INVOKE}),
            approval_at_or_above=RiskLevel.MEDIUM,
        )

    def grant(self, *capabilities: Capability) -> Policy:
        return Policy(
            granted=self.granted | frozenset(capabilities),
            approval_at_or_above=self.approval_at_or_above,
            autonomous=self.autonomous,
        )

    def evaluate(
        self, capabilities: frozenset[Capability] | set[Capability], risk: RiskLevel
    ) -> PolicyDecision:
        missing = sorted(c.value for c in set(capabilities) - set(self.granted))
        if missing:
            return PolicyDecision(
                Decision.DENY, f"missing capability grant: {', '.join(missing)}"
            )
        if risk.rank >= self.approval_at_or_above.rank:
            if self.autonomous:
                return PolicyDecision(
                    Decision.ALLOW, f"risk {risk.value} auto-approved (autonomous mode)"
                )
            return PolicyDecision(
                Decision.REQUIRE_APPROVAL,
                f"risk {risk.value} at or above approval threshold "
                f"{self.approval_at_or_above.value}",
            )
        return PolicyDecision(Decision.ALLOW, f"risk {risk.value} within policy")
