"""Verification engine: evidence, not claims."""

from __future__ import annotations

from astraforge.verification.base import VerificationContext, Verifier
from astraforge.verification.verifiers import (
    CommandVerifier,
    FileVerifier,
    HumanApprovalVerifier,
    SchemaVerifier,
    TestVerifier,
    ToolOutputVerifier,
)


class VerifierRegistry:
    """Name -> verifier, resolved from a task's ``VerificationSpec``."""

    def __init__(self, verifiers: list[Verifier] | None = None) -> None:
        self._verifiers: dict[str, Verifier] = {}
        for verifier in verifiers or []:
            self.register(verifier)

    def register(self, verifier: Verifier) -> None:
        if not verifier.name:
            raise ValueError(f"{type(verifier).__name__} must define a name")
        self._verifiers[verifier.name] = verifier

    def get(self, name: str) -> Verifier:
        try:
            return self._verifiers[name]
        except KeyError:
            raise KeyError(
                f"unknown verifier {name!r}; available: "
                f"{', '.join(sorted(self._verifiers))}"
            ) from None

    def has(self, name: str) -> bool:
        return name in self._verifiers

    def names(self) -> list[str]:
        return sorted(self._verifiers)


def default_verifiers() -> VerifierRegistry:
    """The built-in deterministic verifier set."""
    return VerifierRegistry(
        [
            FileVerifier(),
            CommandVerifier(),
            TestVerifier(),
            SchemaVerifier(),
            ToolOutputVerifier(),
            HumanApprovalVerifier(),
        ]
    )


__all__ = [
    "CommandVerifier",
    "FileVerifier",
    "HumanApprovalVerifier",
    "SchemaVerifier",
    "TestVerifier",
    "ToolOutputVerifier",
    "VerificationContext",
    "Verifier",
    "VerifierRegistry",
    "default_verifiers",
]
