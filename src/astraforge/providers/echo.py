"""Deterministic offline provider.

``echo`` exists so the entire system — planning, execution, verification,
reporting and the test suite — runs with no API key, no network and no
nondeterminism. It is the default provider and the reason the demo is
reproducible on any machine.
"""

from __future__ import annotations

import hashlib
from typing import Any

from astraforge.providers.base import (
    Completion,
    Message,
    ModelProvider,
    ProviderCapabilities,
)


class EchoProvider(ModelProvider):
    """Returns a deterministic, content-addressed summary of the prompt."""

    name = "echo"

    def __init__(self, model: str = "echo-1", **options: Any) -> None:
        super().__init__(model, **options)

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(json_mode=False, max_context_tokens=32_000)

    def complete(self, messages: list[Message], **kwargs: Any) -> Completion:
        prompt = "\n".join(f"{m.role}: {m.content}" for m in messages)
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
        user = next(
            (m.content for m in reversed(messages) if m.role == "user"), ""
        ).strip()
        text = (
            f"[echo:{digest}] Deterministic offline response.\n\n"
            f"Request:\n{user}\n"
        )
        return Completion(
            text=text,
            model=self.model,
            provider=self.name,
            input_tokens=len(prompt.split()),
            output_tokens=len(text.split()),
            raw={"digest": digest},
        )
