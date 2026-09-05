# AstraForge Bench

**Status: designed, not yet run. No results exist. This directory contains a
specification, not data.**

We will not publish numbers we have not measured.

## What it should measure

Text-quality benchmarks do not answer the question that matters here: *did the
work actually get done?* AstraForge Bench measures **completed, verified work**.

| Metric | Definition | Why |
| --- | --- | --- |
| Task completion rate | tasks reaching `COMPLETED` / total | the headline number |
| Verification success rate | verifiers passed / run | did evidence support completion? |
| First-attempt success | tasks completed on attempt 1 | efficiency without retries |
| Failure recovery rate | tasks completed after ≥1 failure | resilience |
| Human interventions | approvals requested per run | true autonomy cost |
| Tool calls | count per run | efficiency |
| Model calls / tokens | count per run | cost proxy |
| Wall-clock time | seconds per run | practicality |
| Cost | provider spend per run | comparability |
| Regression rate | previously passing tasks that now fail | stability across versions |

## Design principles

1. **Identical infrastructure for every model.** The same tools, verifiers,
   policies and plan-validation rules. Only the provider changes. Otherwise the
   benchmark measures scaffolding, not models.
2. **Verification is the score.** Not a rubric, not an LLM judge — the same
   deterministic verifiers the engine uses. A task counts as done when it is
   provably done.
3. **Held-out tasks.** Benchmark tasks must not be shipped as examples, or they
   become part of what implementations are tuned against.
4. **Report failures.** Runs that fail, error or time out are reported, never
   silently dropped. A model that fails 40% of tasks should show 60%.
5. **Reproducible.** Every benchmark run emits its full evidence bundle
   (`run.json`, `events.jsonl`, artifacts) so results can be independently
   audited.
6. **No favouritism.** We will not tune tasks, prompts or verifiers to favour
   any provider. A benchmark that flatters its author is worthless.

## Proposed task suite

Each task needs an unambiguous verifier — that is the hard part of the design.

| Category | Example | Verified by |
| --- | --- | --- |
| Bug fixing | fix a failing test in a small repo | the suite passes; the test was not modified |
| Feature implementation | add an endpoint matching a spec | new tests pass; existing tests still pass |
| Refactoring | extract a module without behaviour change | full suite passes; public API unchanged |
| Data analysis | find planted anomalies in a dataset | findings contain the known values |
| Research synthesis | summarise a fixed source set | every claim cites a real source |
| Multi-step | analyse → implement → test → document | all of the above chained |

Tasks must span difficulty so the benchmark does not saturate.

## Threats to validity

Stating these up front, because a benchmark without them is marketing:

- **Contamination.** Public tasks leak into training data. Mitigation: hold out
  a private set and report both.
- **Verifier gaming.** A model may satisfy the check without doing the work
  (e.g. weakening a test rather than fixing code). Mitigation: verify that test
  files were not modified; include anti-gaming assertions.
- **Scaffolding dominance.** Results may reflect AstraForge's prompts more than
  model capability. Mitigation: publish the exact plans and prompts; invite
  replication.
- **Small sample noise.** Report confidence intervals and run counts, not single
  numbers.
- **Cost asymmetry.** Comparing a large model to a small one on completion rate
  alone is misleading. Always report cost and time alongside.

## Status and how to help

Not yet implemented. Building it well requires the v0.2/v0.3 tooling (network,
Git, richer verifiers) so tasks can be realistic.

Most useful contribution right now: **propose a task with an unambiguous
verifier.** Open an issue describing the task, what "done" means, and exactly
how a verifier would check it without a model in the loop. The verifier design
is harder and more valuable than the task text.
