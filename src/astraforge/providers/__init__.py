"""Model providers. See :mod:`astraforge.providers.base` for the contract."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from astraforge.providers.base import (
    Completion,
    Message,
    ModelProvider,
    ProviderCapabilities,
    ProviderError,
)
from astraforge.providers.echo import EchoProvider
from astraforge.providers.openai_provider import OpenAIProvider

#: Provider name -> factory. Third parties can register their own at runtime.
PROVIDERS: dict[str, Callable[..., ModelProvider]] = {
    "echo": EchoProvider,
    "openai": OpenAIProvider,
}


def register_provider(name: str, factory: Callable[..., ModelProvider]) -> None:
    """Register an additional provider implementation."""
    PROVIDERS[name] = factory


def get_provider(name: str, model: str | None = None, **options: Any) -> ModelProvider:
    """Instantiate a provider by name."""
    try:
        factory = PROVIDERS[name]
    except KeyError:
        raise KeyError(
            f"unknown provider {name!r}; available: {', '.join(sorted(PROVIDERS))}"
        ) from None
    return factory(model, **options) if model else factory(**options)


__all__ = [
    "PROVIDERS",
    "Completion",
    "EchoProvider",
    "Message",
    "ModelProvider",
    "OpenAIProvider",
    "ProviderCapabilities",
    "ProviderError",
    "get_provider",
    "register_provider",
]
