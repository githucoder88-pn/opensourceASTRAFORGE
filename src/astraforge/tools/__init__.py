"""Tools are the only way AstraForge affects the world."""

from __future__ import annotations

from astraforge.providers.base import ModelProvider
from astraforge.tools.base import Tool, ToolContext, ToolError, ToolResult
from astraforge.tools.filesystem import ListDirTool, ReadFileTool, WriteFileTool
from astraforge.tools.model import ModelGenerateTool
from astraforge.tools.registry import ToolRegistry
from astraforge.tools.shell import ShellTool


def default_registry(provider: ModelProvider | None = None) -> ToolRegistry:
    """The built-in tool set: filesystem, shell, and (if given) model generation."""
    registry = ToolRegistry([WriteFileTool(), ReadFileTool(), ListDirTool(), ShellTool()])
    if provider is not None:
        registry.register(ModelGenerateTool(provider))
    return registry


__all__ = [
    "ListDirTool",
    "ModelGenerateTool",
    "ReadFileTool",
    "ShellTool",
    "Tool",
    "ToolContext",
    "ToolError",
    "ToolRegistry",
    "ToolResult",
    "WriteFileTool",
    "default_registry",
]
