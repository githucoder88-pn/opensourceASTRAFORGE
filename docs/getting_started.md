# Getting started

A complete walkthrough, from install to reading the evidence. No API key needed.

## Install

Requires Python 3.10+.

```bash
git clone https://github.com/githucoder88-pn/opensourceASTRAFORGE.git
cd opensourceASTRAFORGE
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
astraforge --version
```

## 1. Create a project

```bash
mkdir ~/astraforge-demo && cd ~/astraforge-demo
astraforge init .
```

This writes `astraforge.yaml` with safe defaults and adds `.astraforge/` to
`.gitignore` (run data is reproducible; it does not belong in Git).

## 2. See what the agent is allowed to do

Before running anything, check the permissions:

```bash
astraforge tools
```

```text
 tool            risk    reversible  capabilities
 fs.list         LOW     yes         filesystem.read
 fs.read         LOW     yes         filesystem.read
 fs.write        MEDIUM  yes         filesystem.write
 model.generate  LOW     yes         filesystem.write, model.invoke
 shell.run       HIGH    no          shell.execute

verifiers: command, file, human_approval, schema, tests, tool_output
granted capabilities: filesystem.read, filesystem.write, model.invoke, shell.execute
approval required at/above risk: HIGH
```

Note what is **absent**: no network, no GitHub, no browser. Those capabilities
are not granted by default.

## 3. Plan without executing

```bash
astraforge run "Write a design note for a URL shortener" --dry-run
```

```text
 task            tool            depends on     verification
 task_brief      fs.write        -              file
 task_approach   model.generate  task_brief     file, tool_output
 task_inventory  fs.list         task_brief, …  tool_output
```

Nothing ran. Always `--dry-run` a plan you did not write yourself.

## 4. Execute

```bash
astraforge run "Write a design note for a URL shortener" -y
```

`-y` auto-approves risk gates. Omit it and AstraForge prompts before anything
at or above `HIGH` risk.

Watch the `evidence` column: `3 check(s) passed` means three real assertions
were made about the world, not that a model claimed success.

## 5. Read the evidence

This is the part that matters.

```bash
astraforge inspect latest
```

The report includes, for every task: which tool ran, how long it took, every
attempt, every verification check and its evidence, and every artifact with its
SHA-256 hash.

```bash
astraforge logs latest              # every event
astraforge logs latest -t task      # filter to task.* events
astraforge logs latest --json | jq  # machine-readable
astraforge artifacts latest         # outputs with hashes
```

## 6. Prove the evidence chain is real

Verification is worthless if it cannot fail. Test it:

```bash
astraforge verify latest
# ok brief.md
# ok approach.md
# 2 artifact(s) match their recorded hashes

echo "I changed this by hand" >> .astraforge/runs/*/workspace/brief.md
astraforge verify latest
# fail hash mismatch for brief.md: recorded 740f13d835ea…, on disk 9c2e…
echo $?   # 1
```

## 7. Run a real plan

The default planner is deliberately simple. Real work comes from plan files:

```bash
cd /path/to/opensourceASTRAFORGE
astraforge run "Fix the failing statistics module" \
  --plan examples/software_engineering/plan.yaml -y
```

Six tasks that write a failing test suite, **prove it fails**, fix the bug,
prove it passes, and record a summary. See
[the example's README](../examples/software_engineering/README.md) for why
proving the failure first is the interesting part.

## 8. Use a real model

Edit `astraforge.yaml`:

```yaml
planner: model          # let the model decompose the goal
model:
  provider: openai
  name: gpt-4o-mini
  api_key_env: OPENAI_API_KEY
```

```bash
pip install "astraforge[llm]"
export OPENAI_API_KEY=...
astraforge run "Build a CLI tool that converts CSV to JSON" --dry-run
```

Always `--dry-run` a model-generated plan first. AstraForge validates it
(schema, cycles, unknown tools) but validation cannot tell you whether the plan
is *sensible*.

Any OpenAI-compatible server works via `base_url` — Ollama, vLLM, LM Studio,
llama.cpp.

## 9. Tighten the permissions

For anything you do not fully trust:

```yaml
security:
  capabilities: [filesystem.read, filesystem.write, model.invoke]  # no shell
  approval_at_or_above: MEDIUM
  approval_gate: console
limits:
  max_total_tool_calls: 25
  max_runtime_s: 300
```

Better yet, use the container — see [SECURITY.md](../SECURITY.md).

## Where next

- [Verification](concepts/verification.md) — the core idea
- [Evidence](concepts/evidence.md) — what a run records
- [Safety](concepts/safety.md) — capabilities and approvals
- [Writing a plan](guides/writing_plans.md)
- [Writing a verifier](guides/writing_verifiers.md)
- [Writing a tool](guides/writing_tools.md)
- [Adding a provider](guides/adding_providers.md)

## Troubleshooting

**`no runs recorded yet`** — you are in a different directory than the one you
ran from. Run data lives in `./.astraforge/`.

**A task fails with `policy denied`** — the tool needs a capability your config
does not grant. `astraforge tools` shows both sides.

**A task fails with `human rejected`** — you (or the default deny gate) declined
an approval. Use `-y` for unattended runs, having read the plan first.

**`command not found` inside a task** — `shell.run` uses a minimal environment.
Bare `python` is rewritten to the running interpreter; other binaries must be on
`PATH`.
