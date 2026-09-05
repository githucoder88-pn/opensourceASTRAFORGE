# Software engineering — fix a genuinely failing test suite

This is AstraForge's flagship demo. It is interesting because of the order of
the tasks: the plan **proves the bug exists before fixing it**.

```bash
astraforge run "Fix the failing statistics module" \
  --plan examples/software_engineering/plan.yaml -y
```

## The task graph

| Task | Tool | What proves it worked |
| --- | --- | --- |
| `task_write_tests` | `fs.write` | the spec file exists and defines the even-length case |
| `task_write_buggy_module` | `fs.write` | `stats.py` exists with a `median` function |
| `task_reproduce_failure` | `shell.run` | **the suite exits 1 with `FAILED (failures=1)` and `2 != 2.5`** |
| `task_apply_fix` | `fs.write` | the corrected averaging expression is present |
| `task_prove_fixed` | `shell.run` | **the suite exits 0 with `Ran 3 tests` / `OK`** |
| `task_report` | `fs.write` | `fix-summary.json` parses with all required fields |

## Why `task_reproduce_failure` matters

Anyone can write a passing test. The hard part is showing the fix *did
something*. This task requires the suite to exit non-zero **and** requires the output to
contain `FAILED (failures=1)`, `Ran 3 tests` and the actual wrong value
`2 != 2.5`, while **excluding** `No module named` and `ImportError`.

That last part is not decoration. While building this demo, the first version of
the plan passed for the wrong reason: `python` resolved to a system interpreter
with no pytest installed, which also exits 1. A broken environment was
masquerading as a reproduced bug. Two things came out of that:

- `astraforge` now rewrites a leading `python` to the interpreter it is running
  under (`src/astraforge/tools/interpreter.py`);
- the `command` verifier gained `stdout_excludes`, so plans can rule out
  "failed for the wrong reason".

The false positive was caught by verification, which is the system working as
intended.

A second portability bug surfaced the same way: testing a clean
`pip install astraforge` (without the `dev` extra) showed the demo failing
because pytest was not present. The plan now uses stdlib `unittest`, so the
flagship demo runs from a bare install with **no dependencies at all**.

## Inspecting the evidence

```bash
astraforge inspect latest
```

You will see `stats.py` recorded **twice**, with different hashes — the buggy
revision produced by `task_write_buggy_module` and the fixed revision produced
by `task_apply_fix`. The evidence trail shows the file changed and which task
changed it.
