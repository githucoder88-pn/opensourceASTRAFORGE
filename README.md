# AstraForge

**Open-source infrastructure for reliable AI work.**

Most AI agents finish a task by *telling you* they finished it. AstraForge
finishes a task by **proving** it — with test exit codes, file hashes, and an
append-only event log you can read yourself.

```text
GOAL → PLAN → EXECUTION → VERIFICATION → EVIDENCE → ARTIFACT
```

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

> **Status: v0.1, early but real.** The core loop works end to end, is covered
> by 187 tests, and every example in this README is executed by CI. It is not
> yet a finished product — see [Honest limitations](#honest-limitations).

---

## Why this exists

An agent that reports "✅ Done — I fixed the bug and all tests pass" is making a
claim. If you have to open the repo and check, the agent saved you nothing.

AstraForge is built on one rule:

> **A task is complete only when something other than the model says so.**

Not a confidence score. Not a second model grading the first. A pytest exit
code, a file that exists and matches a hash, a command that returned what it was
supposed to return, or a human who clicked approve.

## How it's different

|  | Typical agent framework | AstraForge |
| --- | --- | --- |
| Completion signal | The model asserts it | A verifier checks reality |
| Failure handling | Retry until the text looks right | Classified failures, bounded retries, recorded recovery |
| Output | Chat transcript | Hashed artifacts + structured event log + report |
| Dangerous actions | Usually ungated | Capability grants + risk-based approval gates |
| Reproducibility | Rarely | Deterministic offline default provider |
| Trust model | Trust the model | Verify the evidence |

AstraForge is **not** a chatbot, a prompt library, or a RAG wrapper. It is an
execution engine for work you need to be able to audit.

---

## Install

Requires Python 3.10+.

```bash
git clone https://github.com/githucoder88-pn/opensourceASTRAFORGE.git
cd opensourceASTRAFORGE
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Your first goal, in 30 seconds

No API key required. The default `echo` provider is deterministic and offline.

```bash
mkdir my-project && cd my-project
astraforge init .
astraforge run "Write a one-page design note for a URL shortener" -y
```

```text
╭──────────────────── Goal ─────────────────────╮
│ Write a one-page design note for a URL shortener │
╰───────────────────────────────────────────────╯
                Run run_85349fae
 task            status     attempts  evidence
 task_brief      COMPLETED         1  3 check(s) passed
 task_approach   COMPLETED         1  4 check(s) passed
 task_inventory  COMPLETED         1  2 check(s) passed

Artifacts
  brief.md    (167 B, sha256 740f13d835ea…)
  approach.md (156 B, sha256 8d9c8a98fc64…)
╭──────────────────── COMPLETED ─────────────────────╮
│ 3/3 tasks completed · 9 verification checks ·      │
│ 3 tool calls · 2 artifacts                         │
╰────────────────────────────────────────────────────╯
```

Now audit it:

```bash
astraforge inspect latest     # full proof-of-work report
astraforge logs latest        # every structured event
astraforge artifacts latest   # outputs with SHA-256 hashes
astraforge verify latest      # re-check the hashes
```

**Try breaking it** — this is the part that matters:

```bash
echo "I edited this myself" >> .astraforge/runs/*/workspace/brief.md
astraforge verify latest
# fail hash mismatch for brief.md: recorded 740f13d835ea…, on disk 3a1f…
# exit code 1
```

The evidence chain notices. That is the entire product thesis in one command.

---

## The flagship demo: fix a genuinely broken test suite

```bash
astraforge run "Fix the failing statistics module" \
  --plan examples/software_engineering/plan.yaml -y
```

What makes this demo worth looking at is the **order of the tasks**:

| Task | What proves it worked |
| --- | --- |
| `task_write_tests` | the spec file exists and defines the even-length case |
| `task_write_buggy_module` | `stats.py` exists with a `median` function |
| `task_reproduce_failure` | **the suite exits 1 with `FAILED (failures=1)` and `2 != 2.5`** |
| `task_apply_fix` | the corrected averaging expression is present |
| `task_prove_fixed` | **the suite exits 0 with `Ran 3 tests` / `OK`** |
| `task_report` | `fix-summary.json` parses with all required fields |

The plan proves the bug **exists** before fixing it. Anyone can produce a
passing test suite; showing that the fix actually changed something is the hard
part. Afterwards, `astraforge artifacts latest` shows `stats.py` recorded
**twice with different hashes** — the buggy revision and the fixed one, each
attributed to the task that wrote it.

### A real false positive this caught

The first version of that plan passed for the wrong reason. `python` resolved to
a system interpreter with no pytest installed — which also exits 1. A broken
environment was masquerading as a successfully reproduced bug.

Verification caught it, and two fixes followed:

- AstraForge now rewrites a leading `python` to the interpreter it is running
  under ([`tools/interpreter.py`](src/astraforge/tools/interpreter.py));
- the `command` verifier gained `stdout_excludes`, so a plan can assert
  *"failed, and not because the environment is broken"*.

A second portability bug surfaced the same way, by testing a bare
`pip install` without dev extras: the demo assumed pytest was available. It now
uses stdlib `unittest` and runs with **zero dependencies**.

We're documenting this rather than hiding it, because it is exactly the class of
bug that makes unverified agent output untrustworthy.

### More examples

All four are deterministic, offline, and [executed by CI](tests/end_to_end/test_examples.py):

| Example | Demonstrates |
| --- | --- |
| [`hello_world`](examples/hello_world/) | the smallest complete loop |
| [`software_engineering`](examples/software_engineering/) | reproduce a failure, fix it, prove the fix |
| [`data_analysis`](examples/data_analysis/) | CSV → anomaly detection → chart → report |
| [`research`](examples/research/) | synthesis with **enforced citations** (catches fabricated source ids) |

---

## Architecture

```text
              Goal  ("Fix the failing test suite")
                │
                ▼
            Planner ──────────► Plan  (validated: acyclic, tools resolve)
                │
                ▼
        ┌───► Task ─────────────────────────────────┐
        │       │                                   │
        │       ▼                                   │
        │   Policy check ──── denied ──► FAILED     │  bounded retry
        │       │                                   │  (attempt / tool-call /
        │       ▼                                   │   wall-clock budgets)
        │   Approval gate ─── rejected ─► FAILED    │
        │       │                                   │
        │       ▼                                   │
        │     Tool  (workspace-confined)            │
        │       │                                   │
        │       ▼                                   │
        │   Verifiers ─────── failed ───────────────┘
        │       │
        │       ▼ passed
        └── COMPLETED
                │
                ▼
    Artifacts (SHA-256) + Events (JSONL) + Report (Markdown)
```

Every arrow emits a structured event. A run is fully reconstructable from
`.astraforge/runs/<run_id>/`:

```text
run.json      final state: goal, plan, every attempt, artifacts
events.jsonl  append-only log of everything that happened
report.md     human-readable proof-of-work
workspace/    everything the run produced
```

Full detail: **[ARCHITECTURE.md](ARCHITECTURE.md)**.

### Layout

```text
src/astraforge/
├── models/        typed state (Goal, Plan, Task, Evidence, Event)
├── planning/      goal → validated task graph
├── execution/     the engine loop
├── verification/  verifiers that produce evidence
├── tools/         the only way to affect the world
├── providers/     model abstraction (echo, openai-compatible)
├── policies/      capability grants + risk thresholds
├── security/      workspace containment, secret redaction
├── artifacts/     content-addressed output metadata
├── events/        structured event bus
├── memory/        explicit, inspectable, deletable
├── storage/       filesystem run store
├── reporting/     proof-of-work report
└── cli/           the astraforge command
```

---

## How tools work

A tool is the only way AstraForge touches anything. Each declares its schema,
required capabilities, risk, reversibility and timeout **up front**, so policy
is enforced before execution:

```python
class WriteFileTool(Tool):
    name = "fs.write"
    capabilities = frozenset({Capability.FILESYSTEM_WRITE})
    risk = RiskLevel.MEDIUM
    reversible = True
    input_schema = {
        "type": "object",
        "required": ["path", "content"],
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
    }

    def run(self, payload, ctx) -> ToolResult:
        path = ctx.workspace.write_text(payload["path"], payload["content"])
        return ToolResult.success(
            {"path": ctx.workspace.relative(path)},
            evidence=[Evidence(kind="file.written", summary=f"wrote {path.name}")],
            produced_paths=[ctx.workspace.relative(path)],
        )
```

Built in: `fs.write`, `fs.read`, `fs.list`, `shell.run`, `model.generate`.
Run `astraforge tools` to see them with their permissions.

Tools never raise for expected failures — they return a classified
`ToolResult`, so the engine can decide whether a retry could possibly help.

## How verification works

A verifier returns **structured evidence**, never a bare boolean:

```json
{
  "verifier": "tests",
  "status": "passed",
  "checks": 3,
  "failures": [],
  "evidence": [
    "`pytest -q test_stats.py` exited 0",
    "output contains '3 passed'",
    "pytest: 3 passed"
  ]
}
```

| Verifier | Checks |
| --- | --- |
| `file` | existence, minimum size, substrings, regexes |
| `command` | exit code, required/**forbidden** output substrings |
| `tests` | runs a suite and parses the summary |
| `schema` | JSON parses and has required keys |
| `tool_output` | assertions about what the tool returned |
| `human_approval` | a human actually approved this task |

Three properties are enforced by the engine, not by convention:

- A task with a **succeeding tool but failing verification does not complete.**
- A verifier that **crashes fails closed** — never treated as a pass.
- A task with **no verification is recorded as unverified** in the report and
  flagged by `astraforge verify`.

Writing a new verifier means subclassing `Verifier` and implementing one method.

## How safety works

Autonomy is bounded by design.

**Capabilities.** Tools declare what they need; the policy decides. Network,
GitHub writes and browser interaction are **not** granted by default:

```yaml
security:
  capabilities: [filesystem.read, filesystem.write, shell.execute, model.invoke]
  approval_at_or_above: HIGH   # LOW | MEDIUM | HIGH | CRITICAL
  approval_gate: console       # console | deny | auto
```

**Containment.** Every path resolves through a `Workspace` rooted at the run
directory. `../../etc/passwd` raises `WorkspaceEscapeError` — [tested](tests/unit/test_security.py).

**No shell injection.** `shell.run` takes an argv list and never uses
`shell=True`, so model-generated strings cannot chain commands.

**Secrets.** Redacted from events, reports and artifacts by pattern *and* by
matching live environment variables. Subprocesses get a minimal environment —
your API keys are not inherited. Config files store the *name* of an env var,
never a value.

**Bounded retries.** Attempt, tool-call and wall-clock budgets. Unrecoverable
failures (`POLICY_BLOCK`, `HUMAN_REJECTION`, `AUTHORIZATION_FAILURE`) are never
retried.

Details and threat model: **[SECURITY.md](SECURITY.md)**.

## Model providers

Model-specific code lives in `providers/` and nowhere else.

```yaml
model:
  provider: openai        # or: echo (default, offline & deterministic)
  name: gpt-4o-mini
  api_key_env: OPENAI_API_KEY
  base_url: null          # set for Ollama / vLLM / LM Studio / llama.cpp
```

The `openai` provider speaks the Chat Completions shape, so most local servers
work via `base_url`. Adding a provider means implementing one method,
`complete()`. Nothing in planning, execution or verification changes.

`echo` is the default on purpose: the whole system — including the test suite
and every example — runs with no key, no network and no nondeterminism.

---

## CLI

```bash
astraforge init                    # create astraforge.yaml
astraforge run "goal"              # plan, execute, verify
astraforge run "goal" --dry-run    # show the task graph, execute nothing
astraforge run "goal" --json       # machine-readable summary (pipe to jq)
astraforge run "goal" --plan p.yaml  # run a pre-authored plan
astraforge runs                    # list runs
astraforge inspect RUN_ID          # proof-of-work report
astraforge logs RUN_ID -t task     # filtered event log
astraforge artifacts RUN_ID        # outputs with hashes
astraforge verify RUN_ID           # re-check the evidence
astraforge tools                   # tools, verifiers, granted permissions
astraforge cancel RUN_ID
```

`RUN_ID` accepts `latest` or any unique prefix. `run` exits non-zero when a run
fails, so it drops straight into CI.

## Configuration

```yaml
project: my-project
storage_dir: .astraforge
planner: heuristic        # heuristic | model | static
model:
  provider: echo
limits:
  max_task_attempts: 2
  max_total_tool_calls: 100
  max_runtime_s: 900
security:
  capabilities: [filesystem.read, filesystem.write, shell.execute, model.invoke]
  approval_at_or_above: HIGH
  approval_gate: console
```

Unknown keys and invalid values are rejected at load time with a clear message.

## Using it as a library

```python
from astraforge import Config, build_engine, make_goal

engine = build_engine(Config())
result = engine.run(make_goal("Write a design note"))

print(result.ok, len(result.run.artifacts))
for task in result.tasks:
    print(task.task_id, task.status.value, task.attempt_count)
```

---

## Honest limitations

Things this README does **not** claim:

- **The default provider does not reason.** `echo` returns deterministic
  placeholder text. It exists to make the machinery testable, not to produce
  insight. Point at a real provider for real content.
- **The `heuristic` planner does not understand your goal.** It builds an
  honest three-task graph (record → draft → inventory). Goal-aware
  decomposition requires `planner: model`, whose quality depends entirely on the
  model you configure.
- **Example plans are human-authored.** They demonstrate that verification,
  evidence and reporting work — not that a model produced them. Model-generated
  plans are validated hard (schema, cycles, unknown tools) but are not yet
  proven across a broad task distribution.
- **`shell.run` is workspace-confined, not sandboxed.** It runs on the host
  with a minimal environment. Container isolation is v0.2. Do not run untrusted
  generated code with `--yes` on a machine you care about.
- **No benchmark numbers.** AstraForge Bench is designed but not run. We will
  not publish numbers we have not measured.
- **Not implemented yet:** MCP, GitHub integration, browser automation, web UI,
  workflow genomes. These are roadmap items with directory placeholders removed
  rather than stubbed — see [ROADMAP.md](ROADMAP.md).

## Development

```bash
make install     # editable install with dev extras
make test        # 187 tests
make lint        # ruff
make typecheck   # mypy --strict, zero errors
make check       # all of the above
make demo        # run the flagship example
```

Quality bar for merging: ruff clean, `mypy --strict` clean, tests pass,
new behaviour covered by a test that can actually fail.

## Contributing

Good first contributions: a new verifier, a new tool, a new example plan, or a
provider. Each is a self-contained file with a clear contract.

Read [CONTRIBUTING.md](CONTRIBUTING.md). Please open an issue before large
architectural changes.

## License

Apache-2.0 — see [LICENSE](LICENSE) and the
[licensing rationale](docs/adr/0002-apache-2-license.md) (patent grant matters
for a project that executes code on your behalf; all dependencies are
MIT/BSD/Apache-2.0 compatible).

---

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — how the pieces fit
- [ROADMAP.md](ROADMAP.md) — where this is going
- [SECURITY.md](SECURITY.md) — threat model and reporting
- [docs/getting_started.md](docs/getting_started.md) — the full tutorial
- [docs/concepts/](docs/concepts/) — verification, evidence, safety, memory
- [docs/guides/](docs/guides/) — writing tools, verifiers, plans and providers
- [docs/adr/](docs/adr/) — architecture decision records
