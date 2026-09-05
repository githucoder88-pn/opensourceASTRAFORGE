# Security

AstraForge executes commands and writes files on your behalf. Security is a
core feature, not an afterthought.

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Use [GitHub private vulnerability reporting](https://github.com/githucoder88-pn/opensourceASTRAFORGE/security/advisories/new).

Include: affected version/commit, reproduction steps, impact, and any suggested
fix. We aim to acknowledge within 72 hours and to ship a fix or a documented
mitigation for confirmed high-severity issues within 30 days. We will credit
you in the advisory unless you prefer otherwise.

AstraForge is pre-1.0; only `main` receives security fixes.

## Threat model

**What we defend against**

- A model producing a plan that tries to read or write outside the workspace.
- A model producing a plan that requests capabilities it was not granted.
- Secrets leaking into event logs, reports, artifacts or subprocesses.
- Shell metacharacter injection through model-generated command strings.
- Runaway execution consuming unbounded time, tool calls or retries.
- Unverifiable claims of success (arguably the core threat).

**What we do NOT defend against, in v0.1**

- **Malicious code executed by `shell.run`.** It is workspace-confined, not
  sandboxed. A command can still reach the network, read files elsewhere on the
  host that the user can read, and consume resources. Container isolation is on
  the v0.2 roadmap.
- **A compromised model provider.** A hostile provider can return hostile plans.
  Policy and verification limit the blast radius; they do not eliminate it.
- **Supply-chain attacks** on dependencies.
- **Malicious plan files.** A `--plan` file is executable input. Treat it with
  the same care as a shell script.

## Controls

### Capability grants

Tools declare the permissions they need; the policy decides. Defaults are
deliberately narrow:

| Capability | Granted by default | Why |
| --- | --- | --- |
| `filesystem.read` / `filesystem.write` | yes | confined to the workspace |
| `shell.execute` | yes | needed for tests; risk-gated at HIGH |
| `model.invoke` | yes | no side effects beyond the provider |
| `network.request` | **no** | exfiltration and unbounded side effects |
| `github.read` / `github.write` | **no** | external, often irreversible |
| `browser.read` / `browser.interact` | **no** | external side effects |

An ungranted capability is a `DENY`. The tool is **never invoked** — verified by
`test_denied_capability_blocks_the_tool`.

### Risk-based approval

Effective risk is `max(task.risk, tool.risk)`. At or above
`approval_at_or_above` (default `HIGH`) the run stops and asks.

`--yes` / `approval_gate: auto` auto-approves risk gates but **cannot** bypass a
missing capability grant. Autonomy never becomes "grant everything".

### Workspace containment

Every path goes through `Workspace.resolve()`, which rejects anything resolving
outside the run directory — including `../`, symlink tricks and absolute paths.
One choke point, one place to audit.

### No shell injection

`shell.run` accepts an argv list and never uses `shell=True`. `;`, `|`, `&&` and
backticks are ordinary characters. String commands are split with `shlex`.

### Secret handling

- Config stores the **name** of an environment variable, never a value.
- Redaction runs on tool output, events, reports and artifacts, matching both
  known key shapes (OpenAI, GitHub, Slack, AWS, PEM blocks) and the live values
  of any env var whose name contains `KEY`/`TOKEN`/`SECRET`/`PASSWORD`/`CREDENTIAL`.
- Subprocesses receive a minimal environment (`PATH`, `HOME`, locale, `TMPDIR`).
  **Your API keys are not inherited by commands the agent runs.**
- `.astraforge/` is git-ignored by `astraforge init`.

Redaction is best-effort defence in depth, not a guarantee. Do not point
AstraForge at a workspace containing credentials.

### Bounded execution

`max_task_attempts`, `max_total_tool_calls` and `max_runtime_s` are enforced by
the engine. Unrecoverable failure classes are never retried.

### Auditability

Every privileged operation is an event: `policy.blocked`, `approval.required`,
`approval.granted`, `approval.denied`, `tool.called`. `astraforge verify`
re-checks artifact hashes and detects post-hoc tampering.

## Running untrusted goals safely

```yaml
security:
  capabilities: [filesystem.read, filesystem.write, model.invoke]  # no shell
  approval_at_or_above: MEDIUM
  approval_gate: console
limits:
  max_total_tool_calls: 25
  max_runtime_s: 300
```

Better still, run in a container:

```bash
docker build -t astraforge .
docker run --rm -it --network=none -v "$PWD/out:/work" astraforge \
  run "your goal" -y
```

Never run `--yes` with `shell.execute` granted on a machine you care about
unless you have read the plan (`--dry-run` prints it without executing).
