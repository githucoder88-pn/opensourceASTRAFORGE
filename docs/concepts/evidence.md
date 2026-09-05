# Evidence

Evidence is a first-class object in AstraForge, not a logging side effect. A run
should answer, without you re-doing the work:

> *"Why should I believe the agent completed the job?"*

## What a run records

```text
.astraforge/runs/<run_id>/
├── run.json      final state: goal, plan, every attempt, artifacts
├── events.jsonl  append-only log of everything that happened
├── report.md     human-readable proof-of-work
└── workspace/    everything the run produced
```

Plain files, deliberately — see [ADR 0003](../adr/0003-filesystem-run-storage.md).
You can `grep`, `jq`, `diff` and `zip` them without AstraForge installed.

## Events

Every meaningful action is an immutable, machine-readable fact:

```json
{
  "event_id": "evt_3f9a1c2b",
  "run_id": "run_85349fae",
  "timestamp": "2026-09-05T08:12:52.091Z",
  "type": "verification.passed",
  "actor": "verifier:file",
  "task_id": "task_brief",
  "message": "file: 3 check(s) passed",
  "payload": {"status": "passed", "checks": 3}
}
```

Event types cover the run lifecycle (`run.started`, `run.completed`), planning,
tasks (`task.started`, `task.retrying`, `task.failed`), tools, verification,
artifacts, and every privileged decision (`policy.blocked`,
`approval.required`, `approval.granted`, `approval.denied`).

```bash
astraforge logs latest -t verification
astraforge logs latest --json | jq 'select(.type=="task.failed")'
```

## Artifacts

Every produced file is recorded with metadata and a **SHA-256 hash**:

| Path | Kind | Bytes | SHA-256 | Produced by |
| --- | --- | --- | --- | --- |
| `test_stats.py` | code | 452 | `cee0492394ee…` | `task_write_tests` |
| `stats.py` | code | 379 | `16e155376e47…` | `task_write_buggy_module` |
| `stats.py` | code | 449 | `a4c86f540bd6…` | `task_apply_fix` |
| `fix-summary.json` | data | 444 | `d021b795b676…` | `task_report` |

Two details worth noting:

**Revisions are preserved.** `stats.py` appears twice with different hashes —
the buggy version and the fixed one, each attributed to the task that wrote it.
Deduping by path would hide the very change you want to review.

**Indirect outputs are captured.** The engine snapshots the workspace around
every tool call, so a report written by a script running under `shell.run` still
enters the evidence trail. Tools cannot be trusted to declare everything they
produced, and undeclared output is exactly what goes missing. Build noise
(`__pycache__`, `.pytest_cache`) is excluded.

## The report

`astraforge inspect <run_id>` renders the proof-of-work report: summary metrics,
the plan, then every task with every attempt, every verification check and its
evidence, and the artifact table with hashes.

Crucially, **the report does not hide failures.** Failed attempts, their failure
class, whether the class was recoverable, and what changed on retry are all
recorded. A run that succeeded on the second attempt says so.

```text
### `task_reproduce_failure` — PASS

**Attempt 1** — ok
- Tool `shell.run` -> ok in 214ms
  - `python -m unittest -v test_stats` exited 1
- Verifier `command`: passed (8 check(s))
  - evidence: output contains 'test_median_even_length'
  - evidence: output contains 'FAILED (failures=1)'
  - evidence: output contains '2 != 2.5'
  - evidence: output does not contain 'No module named'
```

## Re-verification

Evidence you cannot re-check is just a claim in a nicer format:

```bash
astraforge verify latest
```

This re-hashes every artifact and compares against the record. Tampering and
deletion both exit non-zero. Superseded revisions are reported, not flagged.

## What the evidence does not prove

- **That the goal was the right goal.** Verifiers check what a plan asked for.
- **That the checks were adequate.** A weak verifier produces weak evidence.
  `file exists` proves far less than `file contains the specific value the
  analysis should have found`.
- **That nothing happened outside the workspace.** `shell.run` is confined for
  file paths but is not a sandbox in v0.1.

Evidence raises the floor from "trust the model" to "check the record". It does
not remove the need for judgement about whether the record checks the right
things.
