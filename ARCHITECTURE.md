# Architecture

This document explains how AstraForge is put together and, more importantly,
*why*. If you are extending the system, read this first.

## The one idea

> A task is complete only when something other than the model says so.

Every design decision below follows from that sentence.

## Data flow

```text
Goal ──► Planner ──► Plan ──► [validate: acyclic? tools exist? every task verifiable?]
                                │
                                ▼
                      ┌─── next READY task (dependency order)
                      │         │
                      │         ▼
                      │   Policy.evaluate(capabilities, risk)
                      │         │
                      │    ┌────┴─────┬──────────────┐
                      │  ALLOW   REQUIRE_APPROVAL   DENY
                      │    │          │              │
                      │    │      ApprovalGate       ▼
                      │    │       │       │      FAILED (POLICY_BLOCK,
                      │    │   granted  rejected      not retryable)
                      │    │       │       │
                      │    ▼◄──────┘       ▼
                      │  Tool.execute()  FAILED (HUMAN_REJECTION,
                      │    │                     not retryable)
                      │    ▼
                      │  snapshot diff ──► artifacts (incl. indirect outputs)
                      │    │
                      │    ▼
                      │  Verifiers ──► VerificationResult[]
                      │    │
                      │  ┌─┴──────────┐
                      │ pass        fail
                      │  │            │
                      │  ▼            ▼
                      │ COMPLETED   retry within budget? ──yes──┐
                      │              │no                        │
                      │              ▼                          │
                      │            FAILED                       │
                      └─────────────────────────────────────────┘
                                │
                                ▼
              Artifacts (SHA-256) + Events (JSONL) + Report (Markdown)
```

## Components

### `models/` — typed state

Pydantic models with `extra="forbid"`. Malformed model output fails loudly at
the boundary rather than propagating a half-valid object into the engine.

`Plan.validate_graph()` detects empty plans, duplicate ids, dangling
dependencies and cycles. It returns a *list of problems* rather than raising, so
callers can report all issues at once.

`FailureClass.recoverable` is a property of the failure, not a decision the
engine makes ad hoc. `POLICY_BLOCK`, `HUMAN_REJECTION`,
`AUTHORIZATION_FAILURE` and `DEPENDENCY_FAILURE` are never retried — retrying
them just burns budget to reach the same answer.

### `planning/` — goal to task graph

Three planners share one contract:

| Planner | Use | Determinism |
| --- | --- | --- |
| `StaticPlanner` | pre-authored plan file | fully deterministic |
| `HeuristicPlanner` | zero-config default | fully deterministic |
| `ModelPlanner` | goal-aware decomposition | depends on the model |

`ModelPlanner` treats model output as **untrusted input**: it extracts JSON
(tolerating code fences), validates against the schema, then validates the
graph and checks every referenced tool exists. A malformed plan is a
`PlanningError` — the engine never executes a plan it could not validate.

### `tools/` — the only way to affect the world

Declaring capabilities, risk, reversibility and timeout as *class attributes*
means the policy can be evaluated **before** the tool runs. If permissions were
discovered during execution, gating would be impossible.

`Tool.execute()` wraps `run()` and converts exceptions into classified results:
`PermissionError → AUTHORIZATION_FAILURE`, `TimeoutError → TIMEOUT`, anything
else → `TOOL_FAILURE`. Tools never raise for expected failures.

### `verification/` — evidence, not booleans

A `VerificationResult` carries status, a check count, failure strings and
`Evidence` objects. The report is built from these, which is why it can say
"pytest: 3 passed" rather than "verification: true".

`Verifier.run()` wraps `verify()` so a **crashing verifier fails closed**. A
verifier that errors must never be mistaken for a passing one.

### `execution/engine.py` — the loop

The engine enforces the invariants that make the project's claim true:

1. A task reaches `COMPLETED` only when every verifier passed.
2. No tool runs before the policy allows it.
3. Every attempt, failure and recovery is an event.
4. Retries are bounded by attempts, tool calls and wall-clock time.
5. Nothing is written outside the workspace.

**Artifact capture** snapshots the workspace around each tool call, so files
created *indirectly* — a report written by a script run through `shell.run` —
still enter the evidence trail. Tools cannot be trusted to declare everything
they produced, and undeclared output is exactly what goes missing.

Artifacts are keyed by `(path, sha256)`, so a file rewritten by a later task is
recorded as a **new revision** rather than silently replacing the old record.
Deduping by path alone would hide that the file changed.

### `policies/` and `security/`

`Policy.evaluate()` returns `ALLOW` / `REQUIRE_APPROVAL` / `DENY` with a reason.
Autonomous mode auto-approves risk gates but **never** bypasses a missing
capability grant — otherwise `--yes` would silently become "grant everything".

Risk is `max(task.risk, tool.risk)`, so a plan can escalate a low-risk tool
without editing the tool.

`Workspace` is the single choke point for path resolution. One place to audit,
one place to test.

### `events/` and `storage/`

JSONL over a database: a run log stays greppable, diffable, streamable and
attachable to a bug report, with nothing to install. A failing sink prints to
stderr but never aborts a run — observability must not break execution.

## Deliberate non-decisions

Things we chose *not* to build yet, and why:

| Not built | Reason |
| --- | --- |
| Vector-database memory | Explicit key-value memory is inspectable and deletable. Semantic recall is a feature, not a foundation. |
| Async engine | The bottleneck is subprocesses and network I/O in tools. Sync code is easier to reason about and test; parallel task execution is v0.3. |
| Plugin/entry-point system | Two registries and a factory are enough at this size. Premature plugin infrastructure locks in the wrong extension points. |
| Full JSON Schema validation | The subset used (`required`/`properties`/`type`) covers real tool inputs without a dependency. Revisit when a tool needs more. |
| Multi-agent orchestration | A verified task graph already provides decomposition. Multiple conversing agents add nondeterminism without adding verification. |

## Extension points

| To add | Do this | Core changes |
| --- | --- | --- |
| A tool | Subclass `Tool`, implement `run()` | none |
| A verifier | Subclass `Verifier`, implement `verify()` | none |
| A provider | Subclass `ModelProvider`, implement `complete()` | none |
| A planner | Subclass `Planner`, implement `plan()` | none |
| An event consumer | Implement `handle(event)`, subscribe | none |

If an extension requires touching the engine, that is a design bug — please
open an issue.

## Testing strategy

| Layer | Location | What it proves |
| --- | --- | --- |
| Unit | `tests/unit/` | components behave in isolation |
| Integration | `tests/integration/test_engine.py` | **the reliability guarantees hold** |
| End to end | `tests/end_to_end/` | the real CLI and every shipped example work |

`tests/integration/test_engine.py` is the most important file in the suite. It
encodes the promises: verification overrides tool success, retries are bounded,
policy blocks are not retried, dependents of failed tasks are blocked, secrets
never reach the log, and plans cannot escape the workspace. If one of those
tests breaks, the project's central claim is no longer true.

Everything is deterministic and offline. No test needs a key or a network.
