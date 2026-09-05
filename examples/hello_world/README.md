# Hello world — the smallest complete loop

This example uses no plan file at all. It shows what `astraforge run` does out
of the box with the built-in heuristic planner.

```bash
astraforge init .
astraforge run "Write a one-page design note for a URL shortener" -y
```

## What happens

Three tasks, each with real verification attached:

1. **`task_brief`** — `fs.write` records the goal, constraints and success
   criteria to `brief.md`. Verified by the `file` verifier: the file must exist,
   be non-trivial, and contain the goal heading.
2. **`task_approach`** — `model.generate` drafts `approach.md` using the
   configured provider. Verified twice: the file must exist and be non-trivial,
   *and* the tool must report the expected output path.
3. **`task_inventory`** — `fs.list` inventories the workspace. Verified by
   checking that the brief actually appears in the listing.

## What to look at

```bash
astraforge inspect latest
```

The report shows nine verification checks, two artifacts with SHA-256 hashes,
and the complete event trail. Then try breaking it:

```bash
# Edit an artifact after the fact...
echo "tampered" >> .astraforge/runs/*/workspace/brief.md
astraforge verify latest   # exits 1: hash mismatch
```

That is the whole point of the project in one command.

## A note on honesty

With the default `echo` provider, `approach.md` contains a deterministic
placeholder, not genuine analysis — the example demonstrates the *machinery*,
not model quality. Point the config at a real provider to get real content:

```yaml
model:
  provider: openai
  name: gpt-4o-mini
  api_key_env: OPENAI_API_KEY
```

The verification, evidence and reporting behave identically either way.
