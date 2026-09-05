"""Explicit key-value memory, deliberately not a vector database.

Memory in v0.1 is a JSON file per scope. It is inspectable with ``cat``,
deletable with ``rm``, and never populated implicitly: nothing is written here
unless a caller asks for it. Embedding-based recall is a later addition that
must not change this property.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any


class MemoryScope(str, Enum):
    """Memory is partitioned so the user can inspect and delete each kind."""

    RUN = "run"
    """Facts about the current run only."""
    PROJECT = "project"
    """Durable facts about the project being worked on."""
    PREFERENCES = "preferences"
    """Settings the user stated explicitly."""
    WORKFLOWS = "workflows"
    """Reusable successful workflows (see docs/concepts/genome.md)."""


class MemoryStore:
    """One JSON document per scope under ``<root>/memory``."""

    def __init__(self, root: str | Path = ".astraforge") -> None:
        self.root = Path(root).expanduser().resolve() / "memory"

    def path(self, scope: MemoryScope) -> Path:
        return self.root / f"{scope.value}.json"

    def all(self, scope: MemoryScope) -> dict[str, Any]:
        path = self.path(scope)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def get(self, scope: MemoryScope, key: str, default: Any = None) -> Any:
        return self.all(scope).get(key, default)

    def set(self, scope: MemoryScope, key: str, value: Any) -> None:
        data = self.all(scope)
        data[key] = value
        self._write(scope, data)

    def delete(self, scope: MemoryScope, key: str) -> bool:
        data = self.all(scope)
        if key not in data:
            return False
        del data[key]
        self._write(scope, data)
        return True

    def clear(self, scope: MemoryScope) -> None:
        """Forget an entire scope. Memory must always be deletable."""
        self.path(scope).unlink(missing_ok=True)

    def _write(self, scope: MemoryScope, data: dict[str, Any]) -> None:
        path = self.path(scope)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
