"""OpenAI-compatible provider.

Implemented against the OpenAI Chat Completions HTTP shape, which is also
spoken by many local servers (Ollama, vLLM, llama.cpp, LM Studio) via
``base_url``. The ``openai`` SDK is an optional extra; this module imports it
lazily so the core package has no hard dependency on it.
"""

from __future__ import annotations

import os
from typing import Any

from astraforge.providers.base import (
    Completion,
    Message,
    ModelProvider,
    ProviderCapabilities,
    ProviderError,
)


class OpenAIProvider(ModelProvider):
    """Chat-completions provider. Requires the ``llm`` extra and an API key."""

    name = "openai"

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key_env: str = "OPENAI_API_KEY",
        base_url: str | None = None,
        **options: Any,
    ) -> None:
        super().__init__(model, **options)
        self.api_key_env = api_key_env
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL")

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(streaming=True, json_mode=True, tool_calling=True)

    def available(self) -> bool:
        if not os.environ.get(self.api_key_env):
            return False
        try:
            import openai  # noqa: F401
        except ImportError:
            return False
        return True

    def _client(self) -> Any:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ProviderError(
                "openai package not installed; install with `pip install astraforge[llm]`"
            ) from exc
        key = os.environ.get(self.api_key_env)
        if not key:
            raise ProviderError(f"{self.api_key_env} is not set")
        return OpenAI(api_key=key, base_url=self.base_url)

    def complete(self, messages: list[Message], **kwargs: Any) -> Completion:
        client = self._client()
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[{"role": m.role, "content": m.content} for m in messages],
                **kwargs,
            )
        except Exception as exc:
            raise ProviderError(f"{type(exc).__name__}: {exc}") from exc
        usage = getattr(response, "usage", None)
        return Completion(
            text=response.choices[0].message.content or "",
            model=self.model,
            provider=self.name,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )
