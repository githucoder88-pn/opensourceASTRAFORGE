# Verification

The concept the whole project is built on.

## The problem

An agent tells you: *"✅ Done — I fixed the bug and all tests pass."*

Should you believe it? You cannot tell from the sentence. It is equally
plausible whether the agent fixed the bug, fixed the test to pass trivially,
ran nothing at all, or ran the tests in an environment where they could not
fail. To find out, you have to check — which is most of the work you were
trying to delegate.

## The rule

> **A task is complete only when something other than the model says so.**

## How it works

Each task declares what would prove it worked:

```yaml
- task_id: task_prove_fixed
  description: Prove the fix by requiring the whole suite to pass.
  tool: shell.run
  tool_input:
    command: ["python", "-m", "pytest", "-q", "test_stats.py"]
  verification:
    - verifier: tests
      description: the full suite passes after the fix
      params:
        command: ["python", "-m", "pytest", "-q", "test_stats.py"]
        expect_exit_code: 0
        stdout_contains: ["3 passed"]
```

After the tool runs, the engine executes every verifier. **All must pass** for
the task to reach `COMPLETED`.

## Evidence, not booleans

A verifier returns a structured result:

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

That is why the report can say *"pytest: 3 passed"* instead of
*"verification: true"*. The evidence is the product.

## Three engine-enforced guarantees

These are properties of the engine, not conventions — each has a test that
fails if it regresses.

### 1. A succeeding tool with failing verification does not complete

The tool wrote the file. The file has the wrong content. The task **fails**.

> `test_a_successful_tool_with_failing_verification_does_not_complete`

### 2. A crashing verifier fails closed

If a verifier raises, the result is `FAILED`, never a pass. A broken check must
never be mistaken for a passing one.

> `test_a_broken_verifier_fails_closed`

### 3. Unverified tasks are visible

A task with no verification still runs, but is recorded as unverified in the
report and flagged by `astraforge verify`. It is *visible*, not silently
trusted.

> `test_a_task_without_verification_is_flagged_as_unverified`

## Built-in verifiers

| Verifier | Checks | Typical use |
| --- | --- | --- |
| `file` | exists, min size, substrings, regexes | an artifact was produced with real content |
| `command` | exit code, required and **forbidden** output | anything with a CLI |
| `tests` | runs a suite, parses the summary | the code actually works |
| `schema` | JSON parses, required keys present | structured output is well-formed |
| `tool_output` | assertions on the tool's return value | the tool did what it reported |
| `human_approval` | a human approved this task | judgement calls |

## Verify failure, not just success

The most valuable pattern, and the one most often missed:

```yaml
# Prove the bug EXISTS before fixing it. (From the shipped demo, which uses
# stdlib unittest so it runs with no dependencies at all.)
- task_id: task_reproduce_failure
  tool: shell.run
  tool_input:
    command: ["python", "-m", "unittest", "-v", "test_stats"]
    expect_exit_code: 1
  verification:
    - verifier: command
      params:
        command: ["python", "-m", "unittest", "-v", "test_stats"]
        expect_exit_code: 1
        stdout_contains:
          - "test_median_even_length"
          - "Ran 3 tests"
          - "FAILED (failures=1)"
          - "2 != 2.5"          # the actual wrong value the bug produced
        stdout_excludes: ["No module named", "ImportError"]
```

Anyone can write a passing test suite. Showing the fix *changed something*
requires proving the failure first.

## Failing for the wrong reason

`stdout_excludes` exists because of a real bug in this repository.

The first version of that task only required exit code 1. It passed — but for
the wrong reason: `python` resolved to a system interpreter with no pytest
installed, which also exits 1. **A broken environment was masquerading as a
successfully reproduced bug.**

Two fixes followed:

1. AstraForge now rewrites a leading `python` to the interpreter it is running
   under, so tasks use the same environment as the engine.
2. The `command` verifier gained `stdout_excludes`, so a plan can assert
   *"failed, and not because the environment is broken"*.

The general lesson: **an assertion that a thing failed is weak unless you also
assert it failed the way you expected.** Exit codes are ambiguous; output is
specific. Asserting the *actual wrong value* (`2 != 2.5`) is stronger still.

A related bug appeared later, testing a bare `pip install` without dev extras:
the demo assumed pytest was installed. Verification refused to pass on the
broken environment — correctly — and the demo was rewritten to use stdlib
`unittest`, so it now runs with zero dependencies.

## What verification cannot do

Being honest about the limits:

- **Subjective quality.** "Is this report insightful?" has no deterministic
  verifier. Use `human_approval`, and do not pretend otherwise.
- **Completeness.** Verifiers check what you thought to check. Unconsidered
  failure modes pass silently.
- **Weak checks give false confidence.** `file exists` is nearly worthless as
  proof of work. `file contains the specific value the analysis should have
  found` is strong.

A useful test when writing one: **can I make this verifier fail?** If not, it is
not verifying anything.

## Writing your own

See [Writing a verifier](../guides/writing_verifiers.md). It is one class with
one method.
