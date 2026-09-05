# Writing a plan

A plan file is the most useful thing you can contribute without writing Python.
It is a YAML (or JSON) description of a task graph.

```bash
astraforge run "your goal" --plan my-plan.yaml --dry-run   # inspect
astraforge run "your goal" --plan my-plan.yaml -y          # execute
```

## Structure

```yaml
assumptions:
  - What must be true for this plan to work.
objectives:
  - What the plan is trying to achieve.
risk: LOW

tasks:
  - task_id: task_snake_case      # unique within the plan
    description: One clear sentence.
    tool: fs.write                # must exist (see `astraforge tools`)
    tool_input:                   # must match the tool's input schema
      path: output.md
      content: "# Hello"
    depends_on: []                # task ids that must complete first
    expected_output: What this task should produce.
    risk: LOW                     # escalates above the tool's own risk
    max_attempts: 2
    verification:                 # at least one, and it must be able to fail
      - verifier: file
        description: Shown in the report.
        params:
          path: output.md
          contains: ["# Hello"]
```

The plan is validated before anything runs: unknown tools, dependency cycles,
dangling dependencies and duplicate ids are all rejected.

## Available tools

Run `astraforge tools`. In v0.1:

| Tool | Input | Notes |
| --- | --- | --- |
| `fs.write` | `path`, `content` | workspace-relative paths only |
| `fs.read` | `path`, `max_bytes` | |
| `fs.list` | `path` | recursive; excludes build noise |
| `shell.run` | `command`, `cwd`, `timeout_s`, `expect_exit_code` | argv list; HIGH risk |
| `model.generate` | `prompt`, `system`, `save_to` | uses the configured provider |

`shell.run` takes an **argv list**, not a shell string:

```yaml
command: ["python", "-m", "pytest", "-q"]     # correct
command: "pytest -q && echo done"             # the && will NOT chain
```

A bare `python` is rewritten to the interpreter AstraForge is running under, so
your tasks share its environment.

## Writing verification that means something

This is where plans succeed or fail as evidence.

**Weak:**

```yaml
- verifier: file
  params: {path: report.md}      # proves only that a file exists
```

**Strong:**

```yaml
- verifier: file
  params:
    path: report.md
    min_bytes: 200
    contains: ["## Findings", "91.7"]   # the specific value the analysis
                                        # should have found
```

The test: **can this verifier fail?** If a broken implementation would still
pass, you have not verified anything.

### Verify the failure too

The single most valuable pattern:

```yaml
- task_id: task_reproduce_failure
  tool: shell.run
  tool_input:
    command: ["python", "-m", "pytest", "-q"]
    expect_exit_code: 1              # we REQUIRE failure here
  verification:
    - verifier: command
      params:
        command: ["python", "-m", "pytest", "-q"]
        expect_exit_code: 1
        stdout_contains: ["test_the_specific_case", "1 failed"]
        stdout_excludes: ["No module named", "ImportError"]
```

`stdout_excludes` matters: an exit code of 1 could mean "the test failed" *or*
"the environment is broken". Assert **how** it failed, not just that it did.
(This exact bug occurred while building the shipped demo — see
[verification](../concepts/verification.md#failing-for-the-wrong-reason).)

## Verifier reference

| Verifier | Key params |
| --- | --- |
| `file` | `path`, `min_bytes`, `contains[]`, `matches[]` (regex) |
| `command` | `command`, `cwd`, `expect_exit_code`, `stdout_contains[]`, `stdout_excludes[]`, `timeout_s` |
| `tests` | same as `command`; defaults to `pytest -q`, parses the summary |
| `schema` | `path`, `required_keys[]` |
| `tool_output` | `output_equals{}`, `output_contains{}` |
| `human_approval` | none |

## Patterns

**Prove, change, prove again** — the strongest shape for engineering work:

```text
write tests → prove they fail → apply fix → prove they pass → summarise
```

**Generate, then check independently** — never let the generator grade itself:

```text
write analysis script → run it → verify the OUTPUT contains the expected finding
```

**Gate the irreversible** — force a human decision:

```yaml
risk: CRITICAL
verification:
  - verifier: human_approval
```

## Tips

- Paths are workspace-relative. Absolute paths are rejected.
- Keep tasks small; a failed task is retried whole.
- `depends_on` controls order. Dependents of a failed task are `BLOCKED`, not
  silently skipped.
- Use `--dry-run` constantly while iterating.
- Add your plan to `examples/` with a README and the test suite will run it.

## Full examples

- [`software_engineering/plan.yaml`](../../examples/software_engineering/plan.yaml) — reproduce a failure, fix it, prove it
- [`data_analysis/plan.yaml`](../../examples/data_analysis/plan.yaml) — analysis verified against known-correct results
- [`research/plan.yaml`](../../examples/research/plan.yaml) — enforced citations
