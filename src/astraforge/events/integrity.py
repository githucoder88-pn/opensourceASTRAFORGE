"""Tamper-evident hash chaining for the event log.

AstraForge hashes artifacts so a modified output file is detected. Until now the
*execution record* — the log that says what was attempted, what failed and what
was verified — had no such protection: any line in ``events.jsonl`` could be
edited, reordered or deleted and every command still reported success.

That is a hole in the project's central claim. A proof-of-work report is only as
trustworthy as the history it summarises, so the history needs the same
treatment the artifacts already get.

Each event carries the digest of the event before it::

    seq 0:  prev_hash = GENESIS
            entry_hash = H(0 | GENESIS | canonical_json(event))
    seq 1:  prev_hash = entry_hash(0)
            entry_hash = H(1 | prev_hash | canonical_json(event))

Editing event *n* changes its digest, which breaks the ``prev_hash`` link of
event *n+1* and every event after it. Deleting an event breaks the sequence.
Appending forged events to the end requires no secret, so this is **tamper
evidence, not tamper proofing** — it detects modification of recorded history,
and does not prevent a party who controls the machine from writing a fresh
consistent log. Detecting that would require a signing key or an external
timestamp authority, neither of which v0.1 has. The docs must not overstate it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

#: ``prev_hash`` of the first event in a chain.
GENESIS = "0" * 64

#: Keys excluded from the digest because they *are* the integrity metadata.
_CHAIN_KEYS = frozenset({"seq", "prev_hash", "entry_hash"})


def canonical_payload(event_data: dict[str, Any]) -> str:
    """Serialise an event deterministically, excluding its chain metadata.

    Key order and separators are fixed so the digest depends only on content,
    never on dict ordering or the writer's formatting.
    """
    body = {k: v for k, v in event_data.items() if k not in _CHAIN_KEYS}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)


def compute_entry_hash(seq: int, prev_hash: str, event_data: dict[str, Any]) -> str:
    """Digest binding an event to its position and to the whole prior history."""
    material = f"{seq}\n{prev_hash}\n{canonical_payload(event_data)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass
class ChainBreak:
    """A single detected inconsistency in the event chain."""

    seq: int
    event_id: str
    problem: str

    def __str__(self) -> str:
        return f"event {self.seq} ({self.event_id}): {self.problem}"


@dataclass
class ChainVerdict:
    """Result of verifying an event chain."""

    checked: int
    breaks: list[ChainBreak]

    @property
    def intact(self) -> bool:
        return not self.breaks

    @property
    def summary(self) -> str:
        if self.checked == 0:
            return "no events recorded"
        if self.intact:
            return f"{self.checked} events form an unbroken hash chain"
        return f"{len(self.breaks)} of {self.checked} events failed integrity checks"


def verify_chain(events: list[dict[str, Any]]) -> ChainVerdict:
    """Recompute every digest and confirm each event links to its predecessor.

    Events written before chaining existed have no ``entry_hash``; those are
    reported as unverifiable rather than as tampering, so upgrading AstraForge
    does not retroactively accuse old runs of being forged.
    """
    breaks: list[ChainBreak] = []
    expected_prev = GENESIS

    for index, data in enumerate(events):
        event_id = str(data.get("event_id", "?"))
        recorded_hash = data.get("entry_hash")

        if recorded_hash is None:
            breaks.append(
                ChainBreak(index, event_id, "no integrity hash (written before chaining)")
            )
            continue

        seq = data.get("seq")
        if seq != index:
            breaks.append(
                ChainBreak(
                    index,
                    event_id,
                    f"sequence mismatch: recorded {seq}, expected {index}",
                )
            )

        prev = data.get("prev_hash")
        if prev != expected_prev:
            breaks.append(
                ChainBreak(
                    index,
                    event_id,
                    "broken link: an earlier event was modified, reordered or removed",
                )
            )

        recomputed = compute_entry_hash(
            index if seq is None else int(seq), str(prev), data
        )
        if recomputed != recorded_hash:
            breaks.append(
                ChainBreak(index, event_id, "content does not match its recorded hash")
            )

        expected_prev = str(recorded_hash)

    return ChainVerdict(checked=len(events), breaks=breaks)
