"""Workspace-confined filesystem tools."""

from __future__ import annotations

from typing import Any

from astraforge.models.core import Evidence, FailureClass, RiskLevel
from astraforge.security.capabilities import Capability
from astraforge.security.workspace import is_noise
from astraforge.tools.base import Tool, ToolContext, ToolResult


class WriteFileTool(Tool):
    """Write a UTF-8 text file inside the workspace."""

    name = "fs.write"
    description = "Write text content to a file inside the workspace."
    capabilities = frozenset({Capability.FILESYSTEM_WRITE})
    risk = RiskLevel.MEDIUM
    reversible = True
    input_schema = {
        "type": "object",
        "required": ["path", "content"],
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative path."},
            "content": {"type": "string", "description": "File contents."},
        },
    }

    def run(self, payload: dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = ctx.workspace.write_text(payload["path"], payload["content"])
        rel = ctx.workspace.relative(path)
        size = path.stat().st_size
        return ToolResult.success(
            {"path": rel, "bytes": size, "sha256": ctx.workspace.sha256(path)},
            evidence=[
                Evidence(
                    kind="file.written",
                    summary=f"wrote {rel} ({size} bytes)",
                    data={"path": rel, "bytes": size},
                )
            ],
            produced_paths=[rel],
        )


class ReadFileTool(Tool):
    """Read a UTF-8 text file from the workspace."""

    name = "fs.read"
    description = "Read a text file from the workspace."
    capabilities = frozenset({Capability.FILESYSTEM_READ})
    risk = RiskLevel.LOW
    input_schema = {
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {"type": "string"},
            "max_bytes": {"type": "integer"},
        },
    }

    def run(self, payload: dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = ctx.workspace.resolve(payload["path"])
        if not path.is_file():
            return ToolResult.failure(
                f"file not found: {payload['path']}", FailureClass.ENVIRONMENT_FAILURE
            )
        limit = int(payload.get("max_bytes", 200_000))
        content = path.read_text(encoding="utf-8", errors="replace")[:limit]
        rel = ctx.workspace.relative(path)
        return ToolResult.success(
            {"path": rel, "content": content, "bytes": len(content)},
            evidence=[Evidence(kind="file.read", summary=f"read {rel}")],
        )


class ListDirTool(Tool):
    """List files under a workspace directory."""

    name = "fs.list"
    description = "List files under a workspace directory (recursive)."
    capabilities = frozenset({Capability.FILESYSTEM_READ})
    risk = RiskLevel.LOW
    input_schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
    }

    def run(self, payload: dict[str, Any], ctx: ToolContext) -> ToolResult:
        root = ctx.workspace.resolve(payload.get("path", "."))
        if not root.is_dir():
            return ToolResult.failure(
                f"not a directory: {payload.get('path', '.')}",
                FailureClass.ENVIRONMENT_FAILURE,
            )
        entries = sorted(
            rel
            for rel in (
                ctx.workspace.relative(p) for p in root.rglob("*") if p.is_file()
            )
            if not is_noise(rel)
        )
        return ToolResult.success(
            {"entries": entries, "count": len(entries)},
            evidence=[
                Evidence(
                    kind="dir.listed",
                    summary=(
                        f"{len(entries)} file(s) under {ctx.workspace.relative(root)}"
                    ),
                )
            ],
        )
