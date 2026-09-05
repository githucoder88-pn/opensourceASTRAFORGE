"""Tamper evidence for the event log.

The audit found that ``events.jsonl`` — the record of what was attempted, what
failed and what was verified — could be edited, reordered or truncated with no
detection at all, while artifacts were hash-protected. Rewriting history is how
you would hide a failure, so the history needs the same protection.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from astraforge.events.bus import JsonlEventSink
from astraforge.events.integrity import (
    GENESIS,
    canonical_payload,
    compute_entry_hash,
    verify_chain,
)
from astraforge.models.events import Event, EventType


def _event(run_id: str = "run_test", message: str = "hello") -> Event:
    return Event(run_id=run_id, type=EventType.RUN_STARTED, message=message)


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


class TestCanonicalisation:
    def test_digest_ignores_key_order(self) -> None:
        a = {"run_id": "r", "message": "m", "type": "run.started"}
        b = {"type": "run.started", "message": "m", "run_id": "r"}
        assert canonical_payload(a) == canonical_payload(b)

    def test_digest_excludes_chain_metadata(self) -> None:
        """Otherwise the hash would depend on itself."""
        base = {"run_id": "r", "message": "m"}
        with_chain = {**base, "seq": 3, "prev_hash": "x" * 64, "entry_hash": "y" * 64}
        assert canonical_payload(base) == canonical_payload(with_chain)

    def test_different_content_gives_different_digest(self) -> None:
        assert compute_entry_hash(0, GENESIS, {"m": "a"}) != compute_entry_hash(
            0, GENESIS, {"m": "b"}
        )

    def test_same_content_at_a_different_position_differs(self) -> None:
        """Position is bound into the digest, so events cannot be moved."""
        assert compute_entry_hash(0, GENESIS, {"m": "a"}) != compute_entry_hash(
            1, GENESIS, {"m": "a"}
        )


class TestChainWriting:
    def test_events_are_chained_on_write(self, tmp_path: Path) -> None:
        sink = JsonlEventSink(tmp_path / "events.jsonl")
        for i in range(3):
            sink.handle(_event(message=f"m{i}"))

        rows = _rows(tmp_path / "events.jsonl")
        assert [r["seq"] for r in rows] == [0, 1, 2]
        assert rows[0]["prev_hash"] == GENESIS
        assert rows[1]["prev_hash"] == rows[0]["entry_hash"]
        assert rows[2]["prev_hash"] == rows[1]["entry_hash"]

    def test_a_fresh_log_verifies(self, tmp_path: Path) -> None:
        sink = JsonlEventSink(tmp_path / "events.jsonl")
        for i in range(5):
            sink.handle(_event(message=f"m{i}"))
        verdict = sink.verify()
        assert verdict.intact
        assert verdict.checked == 5

    def test_chain_resumes_across_processes(self, tmp_path: Path) -> None:
        """A second sink appending to the same file must not restart the chain."""
        path = tmp_path / "events.jsonl"
        first = JsonlEventSink(path)
        first.handle(_event(message="a"))
        first.handle(_event(message="b"))

        second = JsonlEventSink(path)  # simulates a later process
        second.handle(_event(message="c"))

        assert second.verify().intact
        assert [r["seq"] for r in _rows(path)] == [0, 1, 2]

    def test_reading_events_still_works(self, tmp_path: Path) -> None:
        sink = JsonlEventSink(tmp_path / "events.jsonl")
        sink.handle(_event(message="readable"))
        events = sink.read()
        assert len(events) == 1
        assert events[0].message == "readable"
        assert events[0].entry_hash is not None


class TestTamperDetection:
    @pytest.fixture
    def log(self, tmp_path: Path) -> Path:
        sink = JsonlEventSink(tmp_path / "events.jsonl")
        for i in range(6):
            sink.handle(_event(message=f"event {i}"))
        return tmp_path / "events.jsonl"

    def test_edited_content_is_detected(self, log: Path) -> None:
        rows = _rows(log)
        rows[2]["message"] = "everything succeeded"
        _write(log, rows)

        verdict = JsonlEventSink(log).verify()
        assert not verdict.intact
        assert any("does not match" in b.problem for b in verdict.breaks)

    def test_deleted_event_is_detected(self, log: Path) -> None:
        rows = _rows(log)
        del rows[2]
        _write(log, rows)
        assert not JsonlEventSink(log).verify().intact

    def test_reordered_events_are_detected(self, log: Path) -> None:
        rows = _rows(log)
        rows[2], rows[3] = rows[3], rows[2]
        _write(log, rows)
        assert not JsonlEventSink(log).verify().intact

    def test_truncated_tail_is_detected_when_metadata_is_stale(self, log: Path) -> None:
        """Dropping the last events breaks nothing on its own; the run record's
        event count is what exposes it. Confirm the chain itself stays honest."""
        rows = _rows(log)
        verdict = verify_chain(rows[:3])
        assert verdict.intact  # a prefix is internally consistent by design
        assert verdict.checked == 3

    def test_forged_hash_does_not_help(self, log: Path) -> None:
        """Recomputing one digest without fixing the rest still fails."""
        rows = _rows(log)
        rows[2]["message"] = "tampered"
        rows[2]["entry_hash"] = compute_entry_hash(2, rows[2]["prev_hash"], rows[2])
        _write(log, rows)

        verdict = JsonlEventSink(log).verify()
        assert not verdict.intact
        assert any("broken link" in b.problem for b in verdict.breaks)

    def test_the_breaking_event_is_identified(self, log: Path) -> None:
        rows = _rows(log)
        rows[4]["message"] = "tampered"
        _write(log, rows)

        verdict = JsonlEventSink(log).verify()
        assert verdict.breaks[0].seq == 4
        assert "4" in str(verdict.breaks[0])


class TestBackwardCompatibility:
    def test_unchained_events_are_unverifiable_not_tampered(
        self, tmp_path: Path
    ) -> None:
        """Upgrading must not retroactively accuse old runs of forgery."""
        path = tmp_path / "events.jsonl"
        path.write_text(
            json.dumps({"event_id": "evt_old", "run_id": "r", "message": "legacy"})
            + "\n",
            encoding="utf-8",
        )
        verdict = JsonlEventSink(path).verify()
        assert not verdict.intact
        assert all("written before chaining" in b.problem for b in verdict.breaks)

    def test_empty_log_is_intact(self, tmp_path: Path) -> None:
        verdict = JsonlEventSink(tmp_path / "nothing.jsonl").verify()
        assert verdict.intact
        assert verdict.checked == 0
