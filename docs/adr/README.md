# Architecture decision records

Each ADR records a decision with long-term consequences: the context, what was
decided, what else was considered, and what it costs us.

Superseded ADRs are **not deleted** — they are marked superseded, so the
reasoning stays inspectable. A stated goal of this project is that no decision
depends on one person's undocumented knowledge.

| # | Decision | Status |
| --- | --- | --- |
| [0001](0001-verification-first-architecture.md) | Verification is the completion signal | Accepted |
| [0002](0002-apache-2-license.md) | Apache-2.0 license | Accepted |
| [0003](0003-filesystem-run-storage.md) | Filesystem + JSONL run storage | Accepted |
| [0004](0004-synchronous-engine.md) | Synchronous engine in v0.1 | Accepted |
| [0005](0005-deterministic-default-provider.md) | Deterministic offline default provider | Accepted |
| [0006](0006-tamper-evident-event-log.md) | Hash-chain the event log | Accepted |

Write a new ADR when a change alters a core abstraction, adds a required
dependency, changes the security model, or changes the public API.
