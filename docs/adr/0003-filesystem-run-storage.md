# 3. Filesystem + JSONL run storage

**Status:** Accepted · **Date:** 2026-09-05

## Context

A run produces state that must outlive the process: the plan, every attempt,
artifacts, and a complete event stream. Something has to store it.

The obvious instinct is a database — SQLite at minimum, Postgres for a future
multi-user deployment.

## Decision

Store each run as a **directory of plain files**:

```text
.astraforge/runs/<run_id>/
├── run.json      final state (goal, plan, attempts, artifacts)
├── events.jsonl  append-only event log
├── report.md     human-readable proof-of-work
└── workspace/    everything the run produced
```

Events are newline-delimited JSON, appended as they occur.

## Rationale

The product's core claim is *"you can check what happened yourself."* Storage
that requires a client tool to inspect actively undermines that.

With plain files a user can:

```bash
cat report.md                                  # read it
grep '"type":"task.failed"' events.jsonl       # search it
jq 'select(.type=="tool.called")' events.jsonl # query it
diff run-a/report.md run-b/report.md           # compare runs
tail -f events.jsonl                           # stream a live run
zip -r evidence.zip .astraforge/runs/run_x/    # attach it to a bug report
```

None of that requires AstraForge to be installed, or even running. JSONL in
particular is append-only by nature, which matches an audit log: no update path
means no accidental history rewriting.

## Alternatives considered

| Alternative | Why not |
| --- | --- |
| **SQLite** | Needs a client to inspect; opaque in code review; no benefit at v0.1 scale (runs are tens to thousands of events). |
| **Postgres** | Requires infrastructure for a local CLI tool. Unacceptable install friction. |
| **Single JSON file per run** | Cannot append incrementally; cannot stream a live run; whole-file rewrites risk corruption on crash. |
| **Structured logs to stdout only** | Not durable, not queryable after the fact. |

## Consequences

**Good**

- Zero-dependency, zero-configuration, cross-platform.
- Evidence is human-inspectable, greppable, diffable and portable.
- Trivially streamable for a future web UI (`tail -f` semantics).
- Crash-resilient: events already written are already durable.

**Bad**

- **No efficient cross-run queries.** "Show every run where the tests verifier
  failed" means scanning directories. Acceptable now; a real limitation at
  thousands of runs.
- No transactions. A crash mid-run leaves `events.jsonl` complete but
  `run.json` absent. Mitigated because the event log is the source of truth for
  what happened.
- No concurrent-writer safety. One process per run today.
- Many small files; unfriendly to some network filesystems.

## Future path

`RunStore` is a single class with a narrow interface (`save_run`, `load_run`,
`load_events`, `list_runs`, `resolve`). Adding a SQLite-backed implementation
for indexing — while continuing to write the file tree as the portable
artifact — is a contained change. Deferred until someone actually has enough
runs for it to matter.
