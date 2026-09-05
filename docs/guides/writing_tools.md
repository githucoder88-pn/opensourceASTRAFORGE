# Writing a tool

A tool is the only way AstraForge affects the world. Adding one requires no
changes to the engine.

## The contract

```python
from typing import Any

from astraforge.models.core import Evidence, FailureClass, RiskLevel
from astraforge.security.capabilities import Capability
from astraforge.tools.base import Tool, ToolContext, ToolResult


class AppendFileTool(Tool):
    """Append text to a file inside the workspace."""

    name = "fs.append"
    description = "Append text to a workspace file, creating it if needed."
    capabilities = frozenset({Capability.FILESYSTEM_WRITE})
    risk = RiskLevel.MEDIUM
    reversible = False          # you cannot un-append
    timeout_s = 30
    input_schema = {
        "type": "object",
        "required": ["path", "content"],
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative path."},
            "content": {"type": "string"},
        },
    }

    def run(self, payload: dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = ctx.workspace.resolve(payload["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(payload["content"])

        rel = ctx.workspace.relative(path)
        return ToolResult.success(
            {"path": rel, "bytes": path.stat().st_size},
            evidence=[Evidence(kind="file.appended", summary=f"appended to {rel}")],
            produced_paths=[rel],
        )
```

Register it in `default_registry()` in `src/astraforge/tools/__init__.py`.

## Declaring metadata honestly

These attributes are how the policy engine protects users. Understating them
defeats the security model.

| Attribute | Guidance |
| --- | --- |
| `capabilities` | Everything you need. `model.generate` declares both `MODEL_INVOKE` and `FILESYSTEM_WRITE` because it can save output. |
| `risk` | `LOW` read-only · `MEDIUM` workspace writes · `HIGH` code execution · `CRITICAL` irreversible/external. When unsure, go higher. |
| `reversible` | `False` if the effect cannot be undone by rerunning. |
| `timeout_s` | Enforce it yourself for long operations. |
| `input_schema` | Required for validation and for briefing the planner model. |

## Returning results

**Never raise for an expected failure.** Return a classified result so the
engine can decide whether a retry could help:

```python
if not path.is_file():
    return ToolResult.failure(
        f"file not found: {payload['path']}",
        FailureClass.ENVIRONMENT_FAILURE,
    )
```

| Class | Use when |
| --- | --- |
| `TOOL_FAILURE` | generic failure |
| `TIMEOUT` | exceeded the time limit |
| `INVALID_OUTPUT` | bad input or unparseable output |
| `ENVIRONMENT_FAILURE` | missing binary, missing file |
| `AUTHORIZATION_FAILURE` | not permitted |
| `MODEL_FAILURE` | the provider failed |

Unexpected exceptions are caught by `Tool.execute()` and classified
automatically (`PermissionError → AUTHORIZATION_FAILURE`, `TimeoutError →
TIMEOUT`, otherwise `TOOL_FAILURE`), but explicit is better.

## Rules

### Always use `ctx.workspace`

```python
path = ctx.workspace.resolve(payload["path"])   # correct
path = Path(payload["path"])                    # WRONG - escapes containment
```

This is the single choke point preventing a generated plan from reading
`~/.ssh/id_rsa`.

### Declare produced files

`produced_paths` makes files into recorded artifacts. The engine also snapshots
the workspace to catch indirect outputs, but declaring is clearer and attributes
them precisely.

### Emit evidence

Evidence appears in the report. `"wrote report.md (1204 bytes)"` is useful;
`"done"` is not.

### Redact untrusted output

If your tool captures external output, redact it:

```python
from astraforge.security.redaction import redact
stdout = redact(proc.stdout)
```

### Never use `shell=True`

Use argv lists. Model-generated strings must not be able to chain commands.

## Testing yours

```python
class TestAppendFileTool:
    def test_appends(self, tool_ctx):
        WriteFileTool().execute({"path": "a.txt", "content": "one\n"}, tool_ctx)
        result, _ = AppendFileTool().execute({"path": "a.txt", "content": "two\n"}, tool_ctx)
        assert result.ok
        assert tool_ctx.workspace.read_text("a.txt") == "one\ntwo\n"

    def test_cannot_escape_the_workspace(self, tool_ctx):
        result, _ = AppendFileTool().execute(
            {"path": "../escape.txt", "content": "x"}, tool_ctx
        )
        assert not result.ok
        assert result.failure_class is FailureClass.AUTHORIZATION_FAILURE

    def test_rejects_missing_input(self, tool_ctx):
        result, _ = AppendFileTool().execute({"path": "a.txt"}, tool_ctx)
        assert not result.ok
```

Always include the containment test.

## Tools needing new capabilities

If your tool needs a capability that is not granted by default (network, GitHub,
browser), that is correct and intentional. Users opt in:

```yaml
security:
  capabilities: [filesystem.read, filesystem.write, model.invoke, network.request]
```

Document the requirement in your tool's `description`, and never widen the
defaults in a PR without an ADR.
