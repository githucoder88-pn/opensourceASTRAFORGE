"""Configuration, validated at load time.

Configuration lives in ``astraforge.yaml`` at the project root. Every field has
a defensible default so ``astraforge run "..."`` works with no config file at
all. Secrets are never stored here — only the *name* of the environment
variable to read them from.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from astraforge.models.core import RiskLevel
from astraforge.policies.policy import DEFAULT_CAPABILITIES, Policy
from astraforge.security.capabilities import Capability

CONFIG_FILENAME = "astraforge.yaml"


class ConfigError(ValueError):
    """The configuration file is invalid."""


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = "echo"
    name: str | None = None
    api_key_env: str | None = None
    base_url: str | None = None

    def options(self) -> dict[str, Any]:
        opts: dict[str, Any] = {}
        if self.api_key_env:
            opts["api_key_env"] = self.api_key_env
        if self.base_url:
            opts["base_url"] = self.base_url
        return opts


class LimitsConfig(BaseModel):
    """Bounded autonomy: no run may exceed these."""

    model_config = ConfigDict(extra="forbid")

    max_task_attempts: int = Field(default=2, ge=1, le=10)
    max_total_tool_calls: int = Field(default=100, ge=1)
    max_runtime_s: int = Field(default=900, ge=1)


class SecurityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capabilities: list[str] = Field(
        default_factory=lambda: sorted(c.value for c in DEFAULT_CAPABILITIES)
    )
    approval_at_or_above: RiskLevel = RiskLevel.HIGH
    approval_gate: Literal["console", "deny", "auto"] = "console"

    def policy(self) -> Policy:
        try:
            granted = frozenset(Capability(c) for c in self.capabilities)
        except ValueError as exc:
            valid = ", ".join(sorted(c.value for c in Capability))
            raise ConfigError(f"{exc}. Valid capabilities: {valid}") from exc
        return Policy(
            granted=granted,
            approval_at_or_above=self.approval_at_or_above,
            autonomous=self.approval_gate == "auto",
        )


class Config(BaseModel):
    """Top-level AstraForge configuration."""

    model_config = ConfigDict(extra="forbid")

    project: str = "astraforge-project"
    storage_dir: str = ".astraforge"
    planner: Literal["heuristic", "model", "static"] = "heuristic"
    plan_file: str | None = None
    model: ModelConfig = Field(default_factory=ModelConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)

    @classmethod
    def load(cls, path: str | Path | None = None) -> Config:
        """Load config from ``path``, or from ``./astraforge.yaml`` if it exists."""
        file = Path(path) if path else Path(CONFIG_FILENAME)
        if not file.exists():
            if path:
                raise ConfigError(f"config file not found: {file}")
            return cls()
        try:
            data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"{file} is not valid YAML: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"{file} must contain a mapping at the top level")
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            raise ConfigError(f"invalid configuration in {file}:\n{exc}") from exc

    def to_yaml(self) -> str:
        return yaml.safe_dump(
            self.model_dump(mode="json", exclude_none=True), sort_keys=False
        )
