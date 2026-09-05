# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Pre-1.0, breaking changes may occur in any minor release.

## [Unreleased]

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
- 187 tests across unit, integration and end-to-end layers
- `mypy --strict` and `ruff` clean
- Architecture, security, contribution, governance and roadmap documentation

[Unreleased]: https://github.com/githucoder88-pn/opensourceASTRAFORGE/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/githucoder88-pn/opensourceASTRAFORGE/releases/tag/v0.1.0
