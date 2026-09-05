# AstraForge documentation

## Start here

- **[Getting started](getting_started.md)** — install to first verified run
- **[Architecture](../ARCHITECTURE.md)** — how the pieces fit and why
- **[Roadmap](../ROADMAP.md)** — what exists and what does not

## Concepts

Understand the ideas behind the system.

- **[Verification](concepts/verification.md)** — the core idea: a task is done
  only when something other than the model says so
- **[Evidence](concepts/evidence.md)** — events, artifacts, hashes and reports
- **[Safety](concepts/safety.md)** — capabilities, risk gates, containment,
  bounded retries
- **[Memory](concepts/memory.md)** — explicit, inspectable, deletable

## Guides

Practical how-tos. Each extension point is one class with one method.

- **[Writing a plan](guides/writing_plans.md)** — no Python required
- **[Writing a verifier](guides/writing_verifiers.md)** — the highest-value
  contribution
- **[Writing a tool](guides/writing_tools.md)**
- **[Adding a provider](guides/adding_providers.md)**

## Decisions

- **[Architecture decision records](adr/)** — what was decided, what was
  rejected, and what it costs

## Reference

- **[Security](../SECURITY.md)** — threat model and reporting
- **[Contributing](../CONTRIBUTING.md)** — the quality bar
- **[Governance](../GOVERNANCE.md)** — how decisions get made
- **[Examples](../examples/)** — four reproducible demos, all run by the test suite
- **[Benchmarks](../benchmarks/)** — designed, not yet run

## Integrations

MCP, GitHub and browser integrations are **not implemented in v0.1**. They are
roadmap items ([v0.2 and v0.3](../ROADMAP.md)). Rather than ship placeholder
modules, the directories are absent until there is working code — an empty
module is a liability, not a promise.
