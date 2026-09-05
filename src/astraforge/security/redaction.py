"""Secret redaction applied to everything that leaves the process.

AstraForge writes tool output into event logs, reports and artifacts. Those are
exactly the places a leaked API key would end up committed to Git, so redaction
happens at the boundary rather than being left to individual tools.

This is defence in depth, not a guarantee: it recognises common credential
shapes and the live values of sensitively-named environment variables. Novel
formats will slip through. Do not point AstraForge at a workspace containing
credentials.
"""

from __future__ import annotations

import os
import re
from typing import Any

REDACTED = "[REDACTED]"

_SENSITIVE_ENV_HINT = re.compile(
    r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|API|AUTH|PRIVATE)", re.IGNORECASE
)

#: Environment values shorter than this are ignored: redacting a short, common
#: string (``"test"``, ``"true"``) would corrupt unrelated output far more often
#: than it would protect anything.
_MIN_ENV_SECRET_LEN = 12

#: Values that look like configuration rather than credentials are never used as
#: redaction needles, even when the variable is sensitively named.
_ENV_VALUE_ALLOWLIST = frozenset(
    {"true", "false", "none", "null", "default", "production", "development", "staging"}
)

_PATTERNS: tuple[re.Pattern[str], ...] = (
    # OpenAI (classic, project and service-account forms)
    re.compile(r"\b(?:sk|rk)-(?:proj-|svcacct-)?[A-Za-z0-9_-]{16,}\b"),
    # Anthropic
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}\b"),
    # GitHub personal/OAuth/app/refresh tokens and fine-grained PATs
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    # Google / Firebase
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,40}"),
    # Hugging Face
    re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"),
    # Slack
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    # AWS access key id, and secret access key when explicitly labelled
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(
        r"(?i)\baws_secret_access_key\s*[=:]\s*['\"]?([A-Za-z0-9/+=]{40})['\"]?"
    ),
    # JSON Web Tokens
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"),
    # Authorization headers and bare scheme+credential pairs.
    re.compile(
        r"(?i)\b(?:proxy-)?authorization\s*:\s*"
        r"(?:bearer|basic|token|digest)?\s*[A-Za-z0-9._~+/=-]{8,}"
    ),
    re.compile(r"(?i)\b(?:bearer|basic|token)\s+[A-Za-z0-9._~+/=-]{12,}"),
    # Credentials embedded in a URL: https://user:password@host
    re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/:@]+:(?P<urlpw>[^\s/@]+)@"),
    # Generic "key = value" assignments in config-ish output
    re.compile(
        r"(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|"
        r"client[_-]?secret|password)\s*[=:]\s*['\"]?([A-Za-z0-9_\-./+=]{8,})['\"]?"
    ),
    # PEM private key blocks
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
    ),
)

def _env_secrets() -> frozenset[str]:
    """Live values of sensitively-named environment variables.

    Recomputed per call rather than cached: a long-running process may load
    credentials after import, and a stale cache would silently stop redacting.
    The result is memoised against the environment's identity below.
    """
    secrets = set()
    for name, value in os.environ.items():
        if not _SENSITIVE_ENV_HINT.search(name):
            continue
        stripped = value.strip()
        if len(stripped) < _MIN_ENV_SECRET_LEN:
            continue
        if stripped.lower() in _ENV_VALUE_ALLOWLIST:
            continue
        secrets.add(stripped)
    return frozenset(secrets)


_ENV_CACHE: tuple[int, frozenset[str]] = (-1, frozenset())


def _cached_env_secrets() -> frozenset[str]:
    """Cache env secrets, invalidating when the environment changes size/content."""
    global _ENV_CACHE
    fingerprint = hash(frozenset(os.environ.items()))
    cached_fingerprint, cached = _ENV_CACHE
    if fingerprint != cached_fingerprint:
        cached = _env_secrets()
        _ENV_CACHE = (fingerprint, cached)
    return cached


def _redact_str(value: str) -> str:
    out = value
    for secret in _cached_env_secrets():
        if secret in out:
            out = out.replace(secret, REDACTED)
    for pattern in _PATTERNS:
        if "urlpw" in (pattern.groupindex or {}):
            # Keep the URL readable; redact only the embedded password.
            out = pattern.sub(
                lambda m: m.group(0).replace(m.group("urlpw"), REDACTED), out
            )
        elif pattern.groups == 2:
            # Preserve the label, redact only the credential value.
            out = pattern.sub(lambda m: f"{m.group(1)}={REDACTED}", out)
        elif pattern.groups == 1:
            out = pattern.sub(lambda m: m.group(0).replace(m.group(1), REDACTED), out)
        else:
            out = pattern.sub(REDACTED, out)
    return out


def redact(value: Any) -> Any:
    """Recursively replace known secret shapes and live env secrets with a marker."""
    if isinstance(value, str):
        return _redact_str(value)
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(redact(v) for v in value)
    return value
