"""Tool registry: name -> tool instance, with metadata for the planner."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from astraforge.tools.base import Tool


class ToolRegistry:
    """Holds the tools available to a run."""

    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if not tool.name:
            raise ValueError(f"{type(tool).__name__} must define a name")
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise KeyError(
                f"unknown tool {name!r}; available: {', '.join(sorted(self._tools))}"
            ) from None

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)

    def describe(self) -> list[dict[str, Any]]:
        return [self._tools[n].describe() for n in self.names()]

    def __iter__(self) -> Iterator[Tool]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)
