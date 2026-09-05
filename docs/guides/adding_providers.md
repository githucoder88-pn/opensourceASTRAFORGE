# Adding a model provider

Model-specific code lives in `src/astraforge/providers/` and nowhere else.
Adding a provider means implementing one method.

## The contract

```python
from typing import Any

from astraforge.providers.base import (
    Completion,
    Message,
    ModelProvider,
    ProviderCapabilities,
    ProviderError,
)


class AnthropicProvider(ModelProvider):
    """Anthropic Messages API."""

    name = "anthropic"

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        api_key_env: str = "ANTHROPIC_API_KEY",
        **options: Any,
    ) -> None:
        super().__init__(model, **options)
        self.api_key_env = api_key_env

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            streaming=True, json_mode=False, tool_calling=True,
            max_context_tokens=200_000,
        )

    def available(self) -> bool:
        """Usable right now? Checked without raising."""
        import os
        if not os.environ.get(self.api_key_env):
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    def complete(self, messages: list[Message], **kwargs: Any) -> Completion:
        import os
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise ProviderError(
                "anthropic not installed; pip install astraforge[anthropic]"
            ) from exc

        key = os.environ.get(self.api_key_env)
        if not key:
            raise ProviderError(f"{self.api_key_env} is not set")

        # Anthropic takes the system prompt separately from the turns.
        system = "\n".join(m.content for m in messages if m.role == "system")
        turns = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role != "system"
        ]

        try:
            response = Anthropic(api_key=key).messages.create(
                model=self.model,
                system=system or None,
                messages=turns,
                max_tokens=kwargs.pop("max_tokens", 4096),
                **kwargs,
            )
        except Exception as exc:            # normalise SDK errors
            raise ProviderError(f"{type(exc).__name__}: {exc}") from exc

        return Completion(
            text="".join(b.text for b in response.content if b.type == "text"),
            model=self.model,
            provider=self.name,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
```

## Register it

```python
# src/astraforge/providers/__init__.py
PROVIDERS: dict[str, Callable[..., ModelProvider]] = {
    "echo": EchoProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
}
```

Or at runtime, without modifying AstraForge:

```python
from astraforge.providers import register_provider
register_provider("my-provider", MyProvider)
```

Then:

```yaml
model:
  provider: anthropic
  name: claude-sonnet-4-20250514
  api_key_env: ANTHROPIC_API_KEY
```

## Rules

### Optional dependencies stay optional

Import the SDK **inside** the method, and add an extra in `pyproject.toml`:

```toml
[project.optional-dependencies]
anthropic = ["anthropic>=0.40"]
```

The core must install with four dependencies and no vendor SDKs.

### Normalise errors to `ProviderError`

The engine classifies `ProviderError` as `MODEL_FAILURE` and can retry. Leaking
raw SDK exceptions breaks that.

### Never log or embed keys

Read from the environment by name. Do not put a key in `Completion.raw`, and do
not include it in error messages.

### Report usage honestly

Populate `input_tokens`/`output_tokens` when the API provides them. Cost
tracking (v0.3) depends on it. Leave them at 0 rather than guessing.

### Discover, do not assume

`capabilities()` and `available()` exist so callers can degrade gracefully.
Never assume JSON mode or tool calling exists.

## Local models

You may not need a new provider at all. `OpenAIProvider` works with any
OpenAI-compatible server:

```yaml
model:
  provider: openai
  name: llama3.1
  base_url: http://localhost:11434/v1   # Ollama
  api_key_env: OLLAMA_API_KEY           # often any non-empty value
```

Confirmed to work with this shape: Ollama, vLLM, LM Studio, llama.cpp server.

## Testing

Never call a real API in tests. Use a canned provider:

```python
class _CannedProvider(ModelProvider):
    name = "canned"

    def __init__(self, text: str) -> None:
        super().__init__("canned-1")
        self.text = text

    def complete(self, messages, **kwargs):
        return Completion(text=self.text, model=self.model, provider=self.name)
```

`tests/unit/test_planning.py` uses exactly this to test plan parsing against
malformed, fenced and hostile model output. Test your prompt-shape translation
(e.g. system-message handling) and your error normalisation — those are where
provider bugs actually live.
