"""Model provider abstraction.

Model-specific logic lives here and nowhere else. The engine only ever sees
:class:`ModelProvider`, so adding a provider never requires touching planning,
execution or verification.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProviderCapabilities:
    """Discovered, not assumed. Callers must degrade gracefully."""

    streaming: bool = False
    json_mode: bool = False
    tool_calling: bool = False
    max_context_tokens: int | None = None


@dataclass
class Message:
    role: str
    content: str


@dataclass
class Completion:
    text: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


class ProviderError(RuntimeError):
    """Provider could not produce a completion."""


class ModelProvider(ABC):
    """Minimal text-completion contract every provider implements."""

    name: str = ""

    def __init__(self, model: str, **options: Any) -> None:
        self.model = model
        self.options = options

    @abstractmethod
    def complete(self, messages: list[Message], **kwargs: Any) -> Completion:
        """Return a completion for ``messages`` or raise :class:`ProviderError`."""

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    def available(self) -> bool:
        """Whether this provider is usable right now (credentials, deps, ...)."""
        return True

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"{type(self).__name__}(model={self.model!r})"
