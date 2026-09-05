# 4. Synchronous engine in v0.1

**Status:** Accepted · **Date:** 2026-09-05

## Context

Agent frameworks are typically written with `asyncio`. Tasks involve network
calls and subprocesses, which is exactly the workload async is designed for, and
a task graph has obvious latent parallelism.

## Decision

**The v0.1 engine is synchronous.** Tasks execute one at a time in dependency
order.

## Rationale

The v0.1 bottleneck is not concurrency — it is *trustworthiness*. The engine's
job is to enforce invariants (verification gates completion, policy gates
execution, retries are bounded, nothing escapes the workspace). Those invariants
must be obviously correct on inspection and deterministically testable.

Synchronous code buys:

- **Readable control flow.** `_execute_task` reads top to bottom: authorize,
  call tool, collect artifacts, verify, retry or complete. A reviewer can check
  the security properties by reading one function.
- **Deterministic tests.** No event-loop fixtures, no flaky ordering, no
  interleaving to reason about. Event ordering assertions are exact.
- **Simple, correct budgets.** Counting tool calls and elapsed time needs no
  synchronisation.
- **A low contribution barrier.** Writing a tool or verifier requires no async
  knowledge.

The actual cost is small at current scale: the shipped examples complete in
under two seconds, dominated by subprocess startup.

## Alternatives considered

| Alternative | Why not now |
| --- | --- |
| **Fully async engine** | Colours the whole codebase, including every tool and verifier third parties write. Large cost paid up front for latency we do not yet have. |
| **Thread pool for parallel tasks** | Real speedup, but concurrent tool calls share one workspace — file conflicts become possible, and artifact snapshot diffing (which attributes files to tasks) would produce wrong attribution. Needs per-task workspace isolation first. |
| **Async internals, sync public API** | Worst of both: async complexity with no user-visible parallelism. |

## Consequences

**Good**

- The engine is ~220 statements at 98% test coverage and can be read in one
  sitting.
- Tool and verifier authors write ordinary functions.
- No async-related flakiness anywhere in the suite.

**Bad**

- **Independent tasks do not run in parallel.** For a plan with several
  long-running test suites this is real, measurable waste.
- A slow tool blocks the whole run.
- Live event streaming to a future web UI will need a thread or a subprocess.

## Revisiting

Parallel execution of independent tasks is a v0.3 roadmap item. Prerequisites:

1. Per-task workspace views (or explicit declared file ownership) so artifact
   attribution stays correct.
2. Thread-safe budget accounting.
3. Deterministic event ordering guarantees for tests, or tests rewritten to
   assert on partial orders.

The `Tool.run()` contract is deliberately synchronous and would remain so; the
engine would run tools in a pool. That keeps the extension surface unchanged.
