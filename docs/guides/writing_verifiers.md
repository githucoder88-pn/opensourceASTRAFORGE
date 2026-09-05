# Writing a verifier

Verifiers are the most valuable thing you can add to AstraForge. One class, one
method.

## The contract

```python
from astraforge.models.core import VerificationResult
from astraforge.verification.base import VerificationContext, Verifier


class LineCountVerifier(Verifier):
    """Assert a file has at least `min_lines` lines."""

    name = "line_count"
    description = "Checks that `path` has at least `min_lines` lines."

    def verify(
        self, params: dict, ctx: VerificationContext
    ) -> VerificationResult:
        path = ctx.workspace.resolve(params["path"])
        if not path.is_file():
            return self.failed([f"file does not exist: {params['path']}"])

        lines = path.read_text(encoding="utf-8").splitlines()
        minimum = int(params.get("min_lines", 1))

        if len(lines) < minimum:
            return self.failed(
                [f"{params['path']} has {len(lines)} lines, expected >= {minimum}"],
                evidence=[f"{params['path']} exists"],
            )
        return self.passed(
            [f"{params['path']} has {len(lines)} lines (>= {minimum})"], checks=2
        )
```

Register it:

```python
# src/astraforge/verification/__init__.py
def default_verifiers() -> VerifierRegistry:
    return VerifierRegistry([..., LineCountVerifier()])
```

Use it:

```yaml
verification:
  - verifier: line_count
    params: {path: report.md, min_lines: 20}
```

## What the context gives you

```python
ctx.workspace     # Workspace - ALWAYS resolve paths through this
ctx.run_id        # str
ctx.task_id       # str
ctx.tool_result   # ToolResult | None - the tool output being verified
ctx.env           # dict[str, str] - engine state, e.g. recorded approvals
```

Always use `ctx.workspace.resolve()`. Never touch paths directly — that is the
containment boundary.

## Helpers

```python
self.passed(evidence: list[str], checks: int = 1)
self.failed(failures: list[str], evidence: list[str] | None = None, checks: int = 1)
self.skipped(reason: str)
```

`checks` should reflect how many distinct assertions you made. It appears in the
report and in `astraforge run --json`.

## Rules

### 1. Return evidence, not a boolean

State what you checked and what you saw. The evidence is what makes a report
convincing:

```python
# Good
self.passed(["report.md has 34 lines (>= 20)", "contains '## Findings'"], checks=2)

# Useless in a report
self.passed(["ok"])
```

### 2. It must be able to fail

A verifier that always passes is worse than none — it manufactures false
confidence. If you cannot write a test that makes yours go red, it is not
verifying anything.

### 3. Fail closed

Do not catch exceptions and return a pass. The base class already wraps
`verify()` so a crash becomes a failure; do not defeat it.

### 4. Be deterministic where possible

Prefer exit codes, hashes and parsed output over anything fuzzy. Nondeterministic
verifiers make runs irreproducible.

### 5. Be specific in failures

```python
# Good - actionable
self.failed(["report.md has 3 lines, expected >= 20"])

# Bad
self.failed(["verification failed"])
```

## Testing yours

Cover all three paths. The middle test is the important one:

```python
class TestLineCountVerifier:
    def test_passes_when_long_enough(self, workspace, verify_ctx):
        workspace.write_text("r.md", "\n".join(f"line {i}" for i in range(30)))
        result = LineCountVerifier().run({"path": "r.md", "min_lines": 20}, verify_ctx)
        assert result.status is VerificationStatus.PASSED
        assert result.evidence

    def test_FAILS_when_too_short(self, workspace, verify_ctx):
        """The test that proves the verifier is worth having."""
        workspace.write_text("r.md", "one line")
        result = LineCountVerifier().run({"path": "r.md", "min_lines": 20}, verify_ctx)
        assert result.status is VerificationStatus.FAILED
        assert "expected >= 20" in result.failures[0]

    def test_fails_when_file_is_missing(self, verify_ctx):
        result = LineCountVerifier().run({"path": "ghost.md"}, verify_ctx)
        assert result.status is VerificationStatus.FAILED
```

Fixtures `workspace` and `verify_ctx` are in `tests/conftest.py`.

## Ideas worth contributing

- `coverage` — assert a minimum test coverage percentage
- `type_check` — run mypy/pyright and assert clean
- `lint` — run a linter and assert zero findings
- `http` — assert an endpoint returns an expected status and schema (needs
  `network.request`)
- `image` — assert an image exists with expected dimensions
- `csv` — assert a CSV has expected columns and row count bounds
- `no_secrets` — assert no credential-shaped strings in the artifacts
