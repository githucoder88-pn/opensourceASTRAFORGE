# Contributing to AstraForge

Thanks for considering a contribution. AstraForge is designed so that most
useful additions are **self-contained files with a clear contract** — you should
not need to understand the whole engine to add value.

## Setup

```bash
git clone https://github.com/githucoder88-pn/opensourceASTRAFORGE.git
cd opensourceASTRAFORGE
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
make check     # lint + typecheck + tests; should be green before you start
```

## Good first contributions

| Contribution | Where | Effort |
| --- | --- | --- |
| A new verifier | `src/astraforge/verification/verifiers.py` | one class, one method |
| A new tool | `src/astraforge/tools/` | one class, one method |
| A new example plan | `examples/<name>/plan.yaml` + `README.md` | no Python needed |
| A model provider | `src/astraforge/providers/` | one method (`complete`) |
| Docs improvements | `docs/`, `README.md` | always welcome |

See [docs/guides/](docs/guides/) for step-by-step walkthroughs.

## The quality bar

Every PR must pass:

```bash
make lint        # ruff, zero warnings
make typecheck   # mypy --strict, zero errors
make test        # full suite
```

And must satisfy these, which CI cannot check for us:

- **New behaviour has a test that can actually fail.** A test that passes
  against a broken implementation is worse than no test — for a project about
  verification, this is non-negotiable. Try breaking your code and confirm the
  test goes red.
- **No unsupported claims in docs.** If you write that something works, it must
  be demonstrable. If it is aspirational, mark it as roadmap.
- **No placeholder files or dead code.** An empty module is a liability. Add
  the file when the implementation exists.
- **Errors say what to do next.** `unknown tool 'fs.wrte'; available: fs.list,
  fs.read, fs.write` beats `KeyError`.

## Writing a verifier

Verifiers are the heart of the project. Two rules:

1. **Return evidence, not a boolean.** Include what you checked and what you
   saw, so it reads well in the report.
2. **It must be able to fail.** If you cannot write a test that makes it fail,
   it is not verifying anything.

```python
class MyVerifier(Verifier):
    name = "my_check"
    description = "One line, shown by `astraforge tools`."

    def verify(self, params, ctx) -> VerificationResult:
        if all_good:
            return self.passed(["what I confirmed"], checks=2)
        return self.failed(["what was wrong"], evidence=["what I did confirm"])
```

Register it in `default_verifiers()` and add tests for the passing case, the
failing case, and any partial-failure case.

## Writing a tool

Declare capabilities and risk **honestly** — the policy engine relies on them.
When in doubt, pick the higher risk level and mark it irreversible.

```python
class MyTool(Tool):
    name = "namespace.action"
    description = "One line."
    capabilities = frozenset({Capability.FILESYSTEM_READ})
    risk = RiskLevel.LOW
    reversible = True
    input_schema = {"type": "object", "required": ["x"],
                    "properties": {"x": {"type": "string"}}}

    def run(self, payload, ctx) -> ToolResult:
        # Never raise for expected failures - return a classified result.
        return ToolResult.success({"out": ...}, evidence=[...])
```

Use `ctx.workspace` for **all** file access. Never touch paths directly.

## Commits and PRs

Conventional-commit prefixes (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`,
`chore:`) with an imperative subject.

A good PR description says what changed, **why**, and how you verified it.
Please open an issue before large architectural changes so we can agree on the
approach first.

## Scope

AstraForge is a **goal execution system with verification**. Contributions that
push it toward being a general chatbot, a prompt library or a RAG framework will
be declined — not because they are bad, but because scope drift is how this kind
of project dies. See [Product differentiation](ROADMAP.md#what-astraforge-is-not).

## Code of conduct

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
