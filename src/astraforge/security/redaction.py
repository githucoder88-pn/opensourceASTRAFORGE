"""Secret redaction applied to everything that leaves the process.

AstraForge writes tool output into event logs, reports and artifacts. Those are
exactly the places a leaked API key would end up committed to Git, so redaction
happens at the boundary rather than being left to individual tools.
"""

from __future__ import annotations

import os
import re
from typing import Any

REDACTED = "[REDACTED]"

_SENSITIVE_ENV_HINT = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE)

_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:sk|rk)-[A-Za-z0-9_-]{16,}\b"),          # OpenAI-style keys
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),            # GitHub tokens
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),          # Slack tokens
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                      # AWS access key id
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
)


def _env_secrets() -> list[str]:
    return [
        value
        for name, value in os.environ.items()
        if _SENSITIVE_ENV_HINT.search(name) and len(value) >= 8
    ]


def redact(value: Any) -> Any:
    """Recursively replace known secret shapes and live env secrets with a marker."""
    if isinstance(value, str):
        out = value
        for secret in _env_secrets():
            out = out.replace(secret, REDACTED)
        for pattern in _PATTERNS:
            out = pattern.sub(REDACTED, out)
        return out
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(redact(v) for v in value)
    return value
