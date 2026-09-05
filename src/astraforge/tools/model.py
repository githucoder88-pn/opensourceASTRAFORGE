"""Tool that invokes the configured model provider.

Reasoning is a tool like any other: it is policy-checked, timed, evidenced and
logged. Deterministic tasks (file writes, test runs, checksums) must not go
through here.
"""

from __future__ import annotations

from typing import Any

from astraforge.models.core import Evidence, FailureClass, RiskLevel
from astraforge.providers.base import Message, ModelProvider, ProviderError
from astraforge.security.capabilities import Capability
from astraforge.security.redaction import redact
from astraforge.tools.base import Tool, ToolContext, ToolResult


class ModelGenerateTool(Tool):
    """Generate text with the run's model provider, optionally saving it to a file."""

    name = "model.generate"
    description = (
        "Ask the configured model provider for text. Optionally write the result "
        "to a workspace file via `save_to`."
    )
    capabilities = frozenset({Capability.MODEL_INVOKE, Capability.FILESYSTEM_WRITE})
    risk = RiskLevel.LOW
    timeout_s = 120
    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "system": {"type": "string"},
            "save_to": {"type": "string"},
        },
    }

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def run(self, payload: dict[str, Any], ctx: ToolContext) -> ToolResult:
        messages = []
        if system := payload.get("system"):
            messages.append(Message("system", str(system)))
        messages.append(Message("user", str(payload["prompt"])))
        try:
            completion = self.provider.complete(messages)
        except ProviderError as exc:
            return ToolResult.failure(str(exc), FailureClass.MODEL_FAILURE)

        text = redact(completion.text)
        output: dict[str, Any] = {
            "text": text,
            "provider": completion.provider,
            "model": completion.model,
            "input_tokens": completion.input_tokens,
            "output_tokens": completion.output_tokens,
        }
        evidence = [
            Evidence(
                kind="model.completion",
                summary=(
                    f"{completion.provider}:{completion.model} produced "
                    f"{len(text)} chars"
                ),
                detail=text[:2000],
                data={"output_tokens": completion.output_tokens},
            )
        ]
        produced: list[str] = []
        if save_to := payload.get("save_to"):
            path = ctx.workspace.write_text(str(save_to), text)
            rel = ctx.workspace.relative(path)
            produced.append(rel)
            output["path"] = rel
            evidence.append(
                Evidence(kind="file.written", summary=f"saved completion to {rel}")
            )
        return ToolResult.success(output, evidence=evidence, produced_paths=produced)
