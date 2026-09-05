# 1. Verification is the completion signal

**Status:** Accepted · **Date:** 2026-09-05

## Context

The dominant pattern in agent frameworks is that the model decides when a task
is finished. It emits something like "✅ Done — I fixed the bug and all tests
pass", and the orchestrator marks the task complete.

This is unreliable in a specific, damaging way: the failure is **silent and
confidently worded**. The user must independently check the work, which removes
most of the value the agent was supposed to provide.

Proposed alternatives generally do not fix it:

- **Confidence scores** — self-reported, and poorly calibrated.
- **A second model grading the first** — correlated failure modes; two models
  can be confidently wrong about the same thing.
- **Human review of everything** — does not scale, and is what we are trying to
  reduce.

## Decision

**A task reaches `COMPLETED` only when an external verifier confirms it.**

Concretely:

1. Every task carries a list of `VerificationSpec`s. Verification runs after the
   tool call, and a task with a *succeeding tool but failing verification does
   not complete*.
2. Verifiers return structured `VerificationResult` objects containing checks,
   failures and `Evidence` — never a bare boolean.
3. Verifiers **fail closed**: a verifier that raises is treated as a failure.
4. A task with no verification is recorded as unverified in the report and
   flagged by `astraforge verify`. It is visible, not silently trusted.
5. Verification is deterministic wherever possible: exit codes, file hashes,
   parsed output — not model judgement.

## Alternatives considered

| Alternative | Why not |
| --- | --- |
| Model self-assessment | The problem we are solving. |
| LLM-as-judge | Correlated errors; introduces nondeterminism into the trust boundary. |
| Verification as optional middleware | Optional verification becomes unused verification. It has to be structural. |
| Post-hoc verification of the whole run | Too late to retry a specific task, and cannot localise the failure. |

## Consequences

**Good**

- Completion means something checkable, and `astraforge verify` can re-check it
  later.
- Failures are localised to a task and a specific unmet check.
- Retry logic has a real signal to act on, instead of re-prompting until the
  prose improves.
- Evidence for the report falls out of verification for free.

**Bad**

- **Writing plans is more work.** Every task needs a meaningful check. This is a
  genuine ergonomic cost, and the main friction users will feel.
- Verification cannot express everything. "Is this report insightful?" has no
  deterministic verifier; the honest answer is `human_approval`.
- A badly written verifier gives false confidence. Hence the contribution rule:
  *if you cannot write a test that makes your verifier fail, it is not
  verifying anything.*
- Verification costs time — a test suite may run repeatedly across retries.

**Validated in practice:** while building the flagship demo, a plan passed for
the wrong reason (a missing interpreter exited 1, which looked like a
reproduced test failure). Verification surfaced it, and it produced two fixes:
interpreter resolution, and `stdout_excludes` on the command verifier. The
architecture caught a real bug in its own demo.
