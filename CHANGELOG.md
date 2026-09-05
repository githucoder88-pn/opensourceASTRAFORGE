# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Pre-1.0, breaking changes may occur in any minor release.

## [Unreleased]

### Added

- **Prompt-injection test suite** (`tests/security/`). The audit noted §18 had
  zero tests. Inspection established the honest position first: v0.1 has no live
  injection channel, because no tool output is ever interpolated into a later
  task input or a model prompt. That is an architectural property, not a defence
  we built, and it vanishes the moment a data-flow feature is added — so it is
  now pinned by tests that break if the invariant is violated.

  The suite also covers the realistic threat, a hostile or compromised planner:
  unregistered tools, absolute-path and traversal writes, self-declared LOW risk
  to dodge the approval gate, ungranted capabilities, and malformed or cyclic
  plans. SECURITY.md documents the position, including the known future exposure
  once MCP allows third-party tool descriptions to reach the model.

### Security

- **`network.request` is now enforced by the kernel.** `shell.run` declares
  `shell.execute`, but a shell can open sockets, so a policy that denied
  `network.request` still allowed `sh -c "curl ..."` to reach the internet. The
  capability was checked at the front door while the shell held a key to the
  back one.

  Without the grant, shell commands now run in an empty Linux network namespace
  (unprivileged `CLONE_NEWUSER | CLONE_NEWNET`): no interfaces except loopback,
  so egress is absent rather than filtered. Granting `network.request` lifts it.
  Verified by a test that opens a real socket and asserts it fails.

  Resource limits are applied in the same step (`RLIMIT_NPROC`, `RLIMIT_AS`,
  `RLIMIT_FSIZE`, `RLIMIT_CORE`). If isolation cannot be applied the child dies
  rather than running unconfined.

  Every shell call records `sandbox.applied` evidence and an `isolation` field,
  and `astraforge tools` reports what the machine can enforce — a degraded
  sandbox must never look like a working one.

  **Still not confined:** host filesystem *reads*. That needs a mount namespace
  with a pivoted root; use the container image for untrusted workloads. Linux
  only; other platforms degrade to resource limits and record the downgrade.

### Added

- **Tamper-evident event log.** Every event now carries `seq`, `prev_hash` and
  `entry_hash`, chaining it to all prior history. `astraforge verify` recomputes
  the chain and fails on an edited, deleted or reordered event. The run record
  pins the event count and final digest, so events dropped from the end are
  caught too — a chain prefix is otherwise self-consistent.

  Artifacts were hash-protected from the start while the execution log was
  freely editable, which left the more valuable target unprotected: rewriting
  history is how a failure would be hidden. Unkeyed digests make this tamper
  evidence, not tamper proofing, and `SECURITY.md` says so explicitly. Logs
  written before this change are reported as unverifiable, never as tampered.

### Fixed

Findings from a pre-release independent audit.

- **Unbounded subprocess memory (critical).** `subprocess.run(capture_output=True)`
  buffered a child's entire output in memory, so a runaway command could
  OOM-kill the engine before truncation applied — surfacing as an unclassified
  crash with no captured evidence. Output now streams through a capped buffer
  (`astraforge.tools.process`); memory is bounded regardless of volume, the tail
  is preserved, truncation is reported as evidence, and a process that floods
  past the hard limit is killed immediately rather than waiting out its timeout.
- **Credentials leaked through command arguments (high).** The shell tool and
  command verifier redacted process *output* but echoed raw `argv` into
  evidence, reports and `events.jsonl`. Arguments are now redacted too.
- **Redaction gaps (high).** Added Google, Hugging Face, Anthropic, fine-grained
  GitHub PAT, JWT, `Authorization` header, URL-embedded password and
  `key = value` credential shapes. Short and common environment values are no
  longer used as redaction needles, since over-redaction destroys evidence.
  Environment scanning is cached and ~2x faster.
- **Verifier subprocesses inherited the full environment (high).** They now get
  the same minimal environment as tool subprocesses, so secrets are not exposed
  to verification commands.
- **Stranded task states (medium).** A run aborted by a budget left tasks
  persisted as `RUNNING`/`PENDING`; `run.json` claimed work was in flight after
  the process had exited. Unfinished tasks are now `CANCELLED`.
- **`human_approval` on a low-risk task was a silent trap (medium).** It failed
  with an unexplained "no approval recorded" because no gate had triggered. The
  failure now names the cause and the two ways to fix it.
- **Leaky plan-file errors (medium).** Malformed YAML/JSON raised raw parser
  exceptions instead of `PlanningError`.
- **Binary subprocess output crashed the shell tool (medium).**
- **`make` targets required an activated virtualenv (medium).** They now resolve
  tools through the active interpreter and fail with actionable guidance.
  Added `python -m astraforge` as an entry point.

### Changed

- Removed `TaskStatus.READY` and `RunStatus.AWAITING_APPROVAL`, which were
  declared but never assigned — they implied states the engine never enters.
- Documentation no longer claims model-generated strings "cannot chain
  commands". The accurate guarantee is that AstraForge never adds an interpreter
  you did not ask for; a plan may still invoke `sh -c` deliberately.

## [0.1.0] — 2026-09-05

First release. The complete core loop —
`goal → plan → execution → verification → evidence → artifact` — works end to
end, offline and deterministically.

### Added

**Core engine**
- Typed state models (`Goal`, `Plan`, `Task`, `Evidence`, `Event`, `Artifact`, `Run`)
  with strict schema validation
- Task graph validation: cycles, dangling dependencies, duplicate ids, unknown tools
- Execution engine with dependency ordering and explicit task statuses
- Failure classification with per-class recoverability
- Bounded retries: attempt, tool-call and wall-clock budgets

**Verification**
- `file`, `command`, `tests`, `schema`, `tool_output`, `human_approval` verifiers
- Structured `VerificationResult` with evidence rather than booleans
- Verifiers fail closed when they crash
- `stdout_excludes` on the command verifier, to rule out failures caused by a
  broken environment rather than by the defect under test

**Tools**
- `fs.write`, `fs.read`, `fs.list`, `shell.run`, `model.generate`
- Declared capabilities, risk level, reversibility, timeout and input schema
- `shell.run` uses argv lists, never `shell=True`
- Automatic resolution of `python` to the running interpreter

**Security**
- Capability grants with conservative defaults (no network, GitHub or browser)
- Risk-based approval gates: console, deny-all, auto, scripted
- Workspace containment for every filesystem operation
- Secret redaction by pattern and by live environment value
- Minimal subprocess environment; API keys are not inherited

**Evidence**
- Content-addressed artifacts with SHA-256, including files created indirectly
  by subprocesses
- Artifact revisions tracked per `(path, hash)`, so file changes remain visible
- Build/cache noise excluded from the artifact trail
- Append-only JSONL event log
- Markdown proof-of-work report covering failures, retries and recoveries

**Planning and providers**
- `StaticPlanner`, `HeuristicPlanner` and `ModelPlanner`
- Model-generated plans validated as untrusted input
- `echo` (offline, deterministic) and OpenAI-compatible providers

**Interface**
- CLI: `init`, `run`, `runs`, `inspect`, `logs`, `artifacts`, `verify`, `tools`, `cancel`
- `--dry-run`, `--json`, `--plan`, `--provider`, `--model`, run-id prefixes and `latest`
- Configuration validated at load time; secrets referenced by env-var name only

**Project**
- Four reproducible examples, all run by the test suite
- 289 tests across unit, integration and end-to-end layers
- `mypy --strict` and `ruff` clean
- Architecture, security, contribution, governance and roadmap documentation

[Unreleased]: https://github.com/githucoder88-pn/opensourceASTRAFORGE/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/githucoder88-pn/opensourceASTRAFORGE/releases/tag/v0.1.0
