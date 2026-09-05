"""A deliberately small synchronous event bus.

Events are the only mechanism by which the engine reports progress. Anything
that wants to observe a run — the CLI renderer, the JSONL log, a future web UI
streaming endpoint — subscribes as an :class:`EventSink`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Protocol

from astraforge.models.events import Event, EventType


class EventSink(Protocol):
    """Anything that can receive events."""

    def handle(self, event: Event) -> None:  # pragma: no cover - protocol
        ...


class MemoryEventSink:
    """Collects events in memory. Used by tests and the report builder."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    def handle(self, event: Event) -> None:
        self.events.append(event)

    def of_type(self, *types: EventType) -> list[Event]:
        wanted = set(types)
        return [e for e in self.events if e.type in wanted]


class JsonlEventSink:
    """Appends events to a newline-delimited JSON file.

    JSONL is chosen over a database so a run log stays greppable, diffable and
    trivially streamable, with no storage engine to install.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def handle(self, event: Event) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(event.model_dump_json() + "\n")

    def read(self) -> list[Event]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as fh:
            return [Event.model_validate(json.loads(line)) for line in fh if line.strip()]


class EventBus:
    """Fans events out to sinks. A failing sink never breaks a run."""

    def __init__(self, run_id: str, sinks: list[EventSink] | None = None) -> None:
        self.run_id = run_id
        self.sinks: list[EventSink] = list(sinks or [])

    def subscribe(self, sink: EventSink) -> None:
        self.sinks.append(sink)

    def emit(
        self,
        type: EventType,
        message: str = "",
        *,
        actor: str = "engine",
        task_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Event:
        event = Event(
            run_id=self.run_id,
            type=type,
            actor=actor,
            task_id=task_id,
            message=message,
            payload=payload or {},
        )
        for sink in self.sinks:
            try:
                sink.handle(event)
            except Exception as exc:
                # A broken sink is reported on stderr rather than aborting
                # execution or being swallowed silently.
                print(
                    f"astraforge: event sink {sink.__class__.__name__} failed: {exc}",
                    file=sys.stderr,
                )
        return event
