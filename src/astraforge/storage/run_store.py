"""Filesystem-backed run storage.

Layout under ``.astraforge/runs/<run_id>/``::

    run.json        final Run object (goal, plan, task attempts, artifacts)
    events.jsonl    append-only event log
    report.md       human-readable proof-of-work report
    workspace/      everything the run produced

A directory of JSON is chosen over a database deliberately: a run is meant to be
inspectable with ``cat``, diffable in review, and attachable to a bug report.
"""

from __future__ import annotations

import json
from pathlib import Path

from astraforge.models.core import Run
from astraforge.models.events import Event

RUNS_DIRNAME = "runs"


class RunStore:
    """Reads and writes run directories under a root (default ``.astraforge``)."""

    def __init__(self, root: str | Path = ".astraforge") -> None:
        self.root = Path(root).expanduser().resolve()
        self.runs_dir = self.root / RUNS_DIRNAME

    # -- paths ------------------------------------------------------------ #

    def run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    def workspace_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "workspace"

    def events_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "events.jsonl"

    def run_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "run.json"

    def report_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "report.md"

    # -- lifecycle -------------------------------------------------------- #

    def create(self, run_id: str) -> Path:
        directory = self.run_dir(run_id)
        (directory / "workspace").mkdir(parents=True, exist_ok=True)
        return directory

    def save_run(self, run: Run) -> Path:
        path = self.run_path(run.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load_run(self, run_id: str) -> Run:
        path = self.run_path(run_id)
        if not path.exists():
            raise FileNotFoundError(f"no such run: {run_id}")
        return Run.model_validate_json(path.read_text(encoding="utf-8"))

    def load_events(self, run_id: str) -> list[Event]:
        path = self.events_path(run_id)
        if not path.exists():
            return []
        with path.open(encoding="utf-8") as fh:
            return [Event.model_validate(json.loads(line)) for line in fh if line.strip()]

    def save_report(self, run_id: str, markdown: str) -> Path:
        path = self.report_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
        return path

    def list_runs(self) -> list[str]:
        """Run ids, newest first."""
        if not self.runs_dir.is_dir():
            return []
        dirs = [d for d in self.runs_dir.iterdir() if (d / "run.json").exists()]
        dirs.sort(key=lambda d: (d / "run.json").stat().st_mtime, reverse=True)
        return [d.name for d in dirs]

    def resolve(self, run_id: str) -> str:
        """Resolve ``latest`` or a unique run-id prefix to a full run id."""
        runs = self.list_runs()
        if run_id in {"latest", "last"}:
            if not runs:
                raise FileNotFoundError("no runs recorded yet")
            return runs[0]
        if run_id in runs:
            return run_id
        matches = [r for r in runs if r.startswith(run_id)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"ambiguous run id {run_id!r}: {', '.join(matches)}")
        raise FileNotFoundError(f"no such run: {run_id}")
