# Safety and bounded autonomy

Autonomy without bounds is not a feature, it is a liability. AstraForge
distinguishes read-only, reversible, destructive and external operations, and
gates them accordingly.

## Capabilities

Tools declare the permissions they need as class attributes, so policy can be
evaluated **before** anything runs:

```python
class ShellTool(Tool):
    capabilities = frozenset({Capability.SHELL_EXECUTE})
    risk = RiskLevel.HIGH
    reversible = False
```

| Capability | Default | Why |
| --- | --- | --- |
| `filesystem.read` | granted | confined to the workspace |
| `filesystem.write` | granted | confined to the workspace |
| `shell.execute` | granted | needed for tests; gated at HIGH risk |
| `model.invoke` | granted | no side effects beyond the provider |
| `network.request` | **denied** | exfiltration, unbounded side effects |
| `github.read` / `github.write` | **denied** | external, often irreversible |
| `browser.read` / `browser.interact` | **denied** | external side effects |

An ungranted capability produces `DENY` and the tool is **never invoked**.

## Risk and approval

Effective risk is `max(task.risk, tool.risk)` — a plan can escalate a low-risk
tool without modifying the tool. At or above the threshold, execution stops and
asks a human.

```yaml
security:
  capabilities: [filesystem.read, filesystem.write, shell.execute, model.invoke]
  approval_at_or_above: HIGH   # LOW | MEDIUM | HIGH | CRITICAL
  approval_gate: console       # console | deny | auto
```

| Gate | Behaviour | Use |
| --- | --- | --- |
| `console` | prompts on stdin | interactive (default) |
| `deny` | rejects everything gated | untrusted goals |
| `auto` | approves risk gates | CI, sandboxed runs (`--yes`) |

**`auto` cannot bypass a missing capability grant.** Autonomy never silently
becomes "grant everything" — verified by
`test_autonomous_mode_auto_approves_but_still_enforces_grants`.

Approvals become evidence: `approval.required`, `approval.granted` and
`approval.denied` are events, and the `human_approval` verifier can require one.

## Containment

Every path resolves through `Workspace.resolve()`, which rejects anything
outside the run directory — `../`, absolute paths, symlink tricks. One choke
point, one place to audit, one place to test.

```python
workspace.resolve("../../etc/passwd")   # WorkspaceEscapeError
```

## No implicit shell

`shell.run` takes an argv list and never uses `shell=True`:

```yaml
tool_input:
  command: ["echo", "a; echo pwned"]   # one argument, not two commands
```

Within an argv element, `;`, `|`, `&&` and backticks are ordinary characters.

**Scope of the guarantee.** A plan can still ask for a shell explicitly:

```yaml
command: ["sh", "-c", "make build && make test"]   # a real shell, by request
```

That is permitted, and then normal shell rules apply. The guarantee is that
AstraForge never *adds* an interpreter behind your back — not that a shell can
never run. Plan files are executable input; review them with `--dry-run`.

## Secrets

- Config stores the **name** of an env var, never a value.
- Redaction runs on tool output, **command arguments**, events, reports and
  artifacts — matching known credential shapes (OpenAI, Anthropic, GitHub,
  Google, Hugging Face, Slack, AWS, JWTs, `Authorization` headers, URL-embedded
  passwords, PEM blocks) **and** the live values of env vars named like
  `*KEY*`, `*TOKEN*`, `*SECRET*`, `*PASSWORD*`, `*CREDENTIAL*`.
- Short or common env values are deliberately ignored, because over-redaction
  destroys the evidence the report exists to provide.
- Subprocesses receive a minimal environment (`PATH`, `HOME`, locale, `TMPDIR`).
  **Your API keys are not inherited by commands the agent runs.**

Redaction is defence in depth, not a guarantee. Do not point AstraForge at a
workspace containing credentials.

## Bounded execution

```yaml
limits:
  max_task_attempts: 2
  max_total_tool_calls: 100
  max_runtime_s: 900
```

Memory is bounded as well: subprocess output streams through a capped buffer, so
a runaway command is killed rather than allowed to exhaust RAM. Truncation is
reported as evidence. When a budget stops a run, unfinished tasks become
`CANCELLED` so the persisted record stays truthful.

Additionally, failure classes carry their own recoverability. `POLICY_BLOCK`,
`HUMAN_REJECTION`, `AUTHORIZATION_FAILURE` and `DEPENDENCY_FAILURE` are **never
retried** — retrying only burns budget to reach the same answer.

## Failure classification

| Class | Recoverable | Meaning |
| --- | --- | --- |
| `TOOL_FAILURE` | yes | the tool reported failure |
| `TIMEOUT` | yes | exceeded its time limit |
| `INVALID_OUTPUT` | yes | schema violation |
| `TEST_FAILURE` | yes | tests did not pass |
| `ENVIRONMENT_FAILURE` | yes | missing binary, missing file |
| `MODEL_FAILURE` | yes | the provider failed |
| `VERIFICATION_FAILURE` | yes | evidence did not support completion |
| `AUTHORIZATION_FAILURE` | **no** | not permitted |
| `POLICY_BLOCK` | **no** | capability not granted |
| `HUMAN_REJECTION` | **no** | a human said no |
| `DEPENDENCY_FAILURE` | **no** | a prerequisite failed |

Nothing is hidden: every failure is an event and appears in the report.

## What is *not* protected in v0.1

Stated plainly:

- **`shell.run` is confined, not sandboxed.** Commands run on the host with a
  minimal environment. They can still reach the network and read files the user
  can read. Container isolation is v0.2.
- **A hostile provider can return hostile plans.** Policy and verification limit
  the blast radius; they do not eliminate it.
- **Plan files are executable input.** Treat `--plan` like a shell script.
  `--dry-run` prints the graph without executing.

Full threat model: [SECURITY.md](../../SECURITY.md).

## Running untrusted goals

```yaml
security:
  capabilities: [filesystem.read, filesystem.write, model.invoke]  # no shell
  approval_at_or_above: MEDIUM
  approval_gate: console
limits:
  max_total_tool_calls: 25
  max_runtime_s: 300
```

Or use the container:

```bash
docker run --rm -it --network=none -v "$PWD/out:/work" astraforge run "goal" -y
```


## Network egress is enforced, not merely declared

`shell.run` declares `shell.execute`, but a shell can open sockets — so the
declaration understates what the tool can do. Gating `network.request` only in
the policy would leave `sh -c "curl ..."` as an open back door.

AstraForge therefore confines the child process itself. Without a
`network.request` grant, the command runs in an empty network namespace:

```console
$ astraforge run "..." -y        # default policy, no network grant
# shell.run output.isolation == "network-namespace"
# a socket connect inside the task fails: there is no interface to use
```

Grant the capability and the confinement lifts:

```yaml
security:
  capabilities: [filesystem.read, filesystem.write, shell.execute, network.request]
```

Every shell call records a `sandbox.applied` evidence entry naming the level
that was active, so the report shows what was enforced.

**Honest limits.** Host filesystem *reads* are still possible; only egress and
resource use are confined. Namespaces are Linux-only, and where they are
unavailable AstraForge falls back to resource limits and records the downgrade
rather than pretending. See [SECURITY.md](../../SECURITY.md).
