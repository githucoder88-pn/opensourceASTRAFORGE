"""Turn files produced by tools into content-addressed artifact records."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from astraforge.models.core import Artifact
from astraforge.security.workspace import Workspace

_EXTRA_TYPES = {
    ".md": "text/markdown",
    ".jsonl": "application/x-ndjson",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".py": "text/x-python",
}

_KINDS = {
    "text/markdown": "report",
    "text/x-python": "code",
    "application/json": "data",
    "text/csv": "data",
}


def guess_media_type(path: Path) -> str:
    if custom := _EXTRA_TYPES.get(path.suffix.lower()):
        return custom
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def collect_artifact(
    workspace: Workspace, relative_path: str, produced_by: str
) -> Artifact | None:
    """Build an :class:`Artifact` for a workspace file, or None if it vanished."""
    path = workspace.resolve(relative_path)
    if not path.is_file():
        return None
    media_type = guess_media_type(path)
    return Artifact(
        name=path.name,
        path=workspace.relative(path),
        kind=_KINDS.get(media_type, "file"),
        media_type=media_type,
        bytes=path.stat().st_size,
        sha256=workspace.sha256(path),
        produced_by=produced_by,
    )
