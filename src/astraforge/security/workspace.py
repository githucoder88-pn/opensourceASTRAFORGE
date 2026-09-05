"""Workspace containment.

Every filesystem and shell tool resolves paths through a :class:`Workspace`.
This is the single choke point that prevents a generated plan from reading
``~/.ssh/id_rsa`` or writing outside the run directory.
"""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

#: Directories that are build/tool noise rather than meaningful output. They are
#: excluded from workspace snapshots so they never pollute the artifact trail.
IGNORED_DIRS = frozenset(
    {
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".git",
        "node_modules",
        ".venv",
        ".tox",
        ".astraforge",
    }
)

#: File suffixes that are never interesting as evidence.
IGNORED_SUFFIXES = frozenset({".pyc", ".pyo", ".pyd"})


def is_noise(relative_path: str) -> bool:
    """Whether a workspace-relative path is tool noise rather than an artifact."""
    parts = PurePosixPath(relative_path.replace("\\", "/")).parts
    if any(part in IGNORED_DIRS for part in parts):
        return True
    return any(relative_path.endswith(suffix) for suffix in IGNORED_SUFFIXES)


class WorkspaceEscapeError(PermissionError):
    """Raised when a path resolves outside the workspace root."""


class Workspace:
    """A rooted directory that all task file operations are confined to."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, relative: str | Path) -> Path:
        """Resolve ``relative`` inside the workspace or raise :class:`WorkspaceEscapeError`."""
        candidate = Path(relative)
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (self.root / candidate).resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise WorkspaceEscapeError(
                f"path {relative!r} resolves outside workspace {self.root}"
            )
        return resolved

    def write_text(self, relative: str | Path, content: str) -> Path:
        path = self.resolve(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def read_text(self, relative: str | Path) -> str:
        return self.resolve(relative).read_text(encoding="utf-8")

    def relative(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)

    def snapshot(self) -> dict[str, tuple[int, float]]:
        """Cheap (size, mtime) fingerprint of every file, for change detection."""
        snap: dict[str, tuple[int, float]] = {}
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            relative = self.relative(path)
            if is_noise(relative):
                continue
            stat = path.stat()
            snap[relative] = (stat.st_size, stat.st_mtime)
        return snap

    @staticmethod
    def changed_since(
        before: dict[str, tuple[int, float]], after: dict[str, tuple[int, float]]
    ) -> list[str]:
        """Paths that were created or modified between two snapshots."""
        return sorted(k for k, v in after.items() if before.get(k) != v)

    @staticmethod
    def sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"Workspace({self.root})"
