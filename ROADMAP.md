# Roadmap

AstraForge's north star: **AI that does work instead of generating responses.**

Ordering principle: *never let architectural ambition outrun a working core.*
Each version must leave the system usable end to end.

## v0.1 — Core loop ✅ shipped

- [x] Typed state: goal, plan, task graph, evidence, events, artifacts
- [x] Execution engine with bounded retries and failure classification
- [x] Tool system with declared capabilities, risk and reversibility
- [x] Six deterministic verifiers
- [x] Capability policy + risk-based human approval gates
- [x] Workspace containment and secret redaction
- [x] Content-addressed artifacts (including indirect outputs)
- [x] JSONL event log and filesystem run store
- [x] Proof-of-work Markdown report
- [x] CLI: `init`, `run`, `runs`, `inspect`, `logs`, `artifacts`, `verify`, `tools`, `cancel`
- [x] Provider abstraction with offline `echo` and OpenAI-compatible providers
- [x] Four reproducible examples, all run by the test suite
- [x] 186 tests, `mypy --strict` clean

## v0.2 — Isolation, MCP and richer evidence

- [ ] **Container-isolated execution** for `shell.run` (the biggest current
      safety gap — see [SECURITY.md](SECURITY.md))
- [ ] **MCP client**: discover external tools, inspect schemas, enforce policy
      at the boundary, log every call. External tools are untrusted input.
- [ ] `http` tool + `HttpVerifier` (status, schema, latency), behind
      `network.request`
- [ ] Research tooling with source-reachability verification
- [ ] Artifact diffing between runs
- [ ] Structured logging to stderr alongside the event log

## v0.3 — Git, GitHub and long-running work

- [ ] Git tool: branch, commit, diff — local only, no remote writes
- [ ] GitHub read: repository, issues, PRs, CI results
- [ ] GitHub write **behind explicit approval**, following
      *read → clone → modify local branch → test → show diff → request approval*
      before PR submission is ever enabled
- [ ] `astraforge pause` / `resume` for long-running runs
- [ ] Parallel execution of independent tasks
- [ ] Cost tracking and budgets per provider

## v0.4 — Observability and reuse

- [ ] Web UI: live task graph, tool activity, verification, approvals.
      The UI must make execution *understandable*, not merely attractive.
- [ ] Browser tool (Playwright) with screenshot evidence, behind
      `browser.interact`
- [ ] **Workflow genomes**: distil a successful run into a reusable, adaptable
      template (`"CSV → anomaly detection → report"`). Requires the core loop to
      be proven first.
- [ ] **AstraForge Bench**: task completion rate, verification success, human
      interventions, retries, recovery rate, cost, wall time — comparing models
      on identical workflow infrastructure.

  > We will publish benchmark numbers only after actually running them, and we
  > will not tune the benchmark to favour any model. A benchmark that flatters
  > its author is worthless.

## v0.5 — Scale

- [ ] Distributed execution across workers
- [ ] Multi-user runs with per-user permissions
- [ ] Pluggable storage backends
- [ ] Fine-grained per-tool permission policies

## v1.0 — Stability

- [ ] Stable public Python API with deprecation policy
- [ ] Plugin ecosystem via entry points
- [ ] Production deployment guidance
- [ ] Semantic versioning commitment

## What AstraForge is not

Guarding against scope drift is an ongoing task. AstraForge will not become:

- another chat interface
- a prompt library
- a generic multi-agent demo
- a RAG wrapper
- a grab-bag of unrelated AI utilities

The defining concept stays: **reliable autonomous work with verification and
evidence.** Features that do not strengthen that are out of scope, however
individually appealing.

## Influencing this roadmap

Open an issue describing the problem you hit. Concrete use cases move items up;
"it would be cool if" generally does not.
