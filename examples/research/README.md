# Research — synthesis with enforced citations

```bash
astraforge run "Summarise verification approaches for AI agents" \
  --plan examples/research/plan.yaml -y
```

## The idea

Research output is hard to verify: prose always *looks* plausible. This example
makes one property mechanically checkable — **every claim must cite a source
that actually exists**.

| Task | Tool | What proves it worked |
| --- | --- | --- |
| `task_sources` | `fs.write` | `sources.json` parses with a topic and source list |
| `task_checker` | `fs.write` | the citation checker exists |
| `task_synthesis` | `fs.write` | `synthesis.md` exists with a findings section |
| `task_check_citations` | `shell.run` | checker exits 0: `3 claims, all cited` |

## The citation checker can fail

A verifier that cannot fail proves nothing, so try breaking it:

```bash
cd .astraforge/runs/*/workspace
echo "- A claim with no source." >> synthesis.md
python check_citations.py        # exits 1: UNCITED

echo "- A claim citing nothing real [S99]." >> synthesis.md
python check_citations.py        # exits 1: UNKNOWN SOURCE: S99
```

It catches both uncited claims and **fabricated source ids** — the failure mode
that matters most when a model writes the synthesis. Both behaviours are
asserted in `tests/end_to_end/test_examples.py`.

## Honest limitations

`sources.json` is a fixed offline fixture with three entries, so the example is
reproducible without network access. AstraForge does **not** currently ship a
tool that retrieves sources from the web; that is on the roadmap (v0.2) and
would need its own verification for source reachability and quotation accuracy.
The synthesis text is authored in the plan, not model-generated — this example
demonstrates the *citation-enforcement machinery*, not model research quality.
