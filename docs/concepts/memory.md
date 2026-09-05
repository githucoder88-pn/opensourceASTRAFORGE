# Memory

AstraForge starts with **explicit structured memory**, not a vector database.

## Why not embeddings first

A vector store is easy to add and hard to reason about. Once an agent silently
accumulates a behavioural profile, three things become true:

1. You cannot tell why it behaved differently today than yesterday.
2. You cannot reliably delete a specific fact.
3. Runs stop being reproducible.

All three conflict directly with a project whose premise is auditability. So
v0.1 memory is a JSON file per scope: inspectable with `cat`, deletable with
`rm`, and **never written implicitly**.

## Scopes

| Scope | Holds | Lifetime |
| --- | --- | --- |
| `run` | facts about the current run | one run |
| `project` | durable facts about the project | until deleted |
| `preferences` | settings the user stated explicitly | until deleted |
| `workflows` | reusable successful workflows | until deleted |

Separation matters: "this project uses pytest" (project) is a different kind of
claim from "I prefer terse reports" (preference), and they should be forgettable
independently.

## Usage

```python
from astraforge.memory import MemoryScope, MemoryStore

memory = MemoryStore(".astraforge")

memory.set(MemoryScope.PROJECT, "test_command", "pytest -q")
memory.get(MemoryScope.PROJECT, "test_command")   # "pytest -q"

memory.all(MemoryScope.PROJECT)                   # inspect everything
memory.delete(MemoryScope.PROJECT, "test_command")
memory.clear(MemoryScope.PROJECT)                 # forget the whole scope
```

Stored as `.astraforge/memory/<scope>.json` — sorted, indented, diffable.

## Principles

1. **Nothing is stored implicitly.** No file exists until something asks for a
   write.
2. **Everything is deletable.** Every scope can be cleared. There is no hidden
   store.
3. **Memory is inspectable.** Plain JSON, no client required.
4. **Memory does not silently change behaviour.** It is read explicitly, not
   injected into every prompt.

## Current status

The store is implemented and tested. The **engine does not yet read from it** —
wiring memory into planning is a v0.2 item, and doing it well means answering
"how does the report show that a remembered fact influenced this run?" first.
An unaudited influence on behaviour would undercut the evidence model.

Documenting this gap rather than implying a working feature.

## Roadmap

- **v0.2** — planner reads project memory and preferences; memory reads are
  recorded as events so their influence is auditable.
- **v0.4** — workflow genomes: distil a successful run into a reusable template
  (`"CSV → anomaly detection → report"`) that a later user can adapt.
- **Later** — optional embedding-backed recall, as an addition that preserves
  inspectability and deletability rather than replacing them.
