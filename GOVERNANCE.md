# Governance

AstraForge is an early-stage open-source project. This document describes how
decisions are made today and how that is expected to change.

## Current model: BDFL-lite

The project currently has a small maintainer group with final say on direction.
This is honest about the project's stage — pretending to have a foundation-style
governance structure at v0.1 would be theatre.

In practice:

- Anyone may open issues and pull requests.
- Maintainers review, request changes, and merge.
- Disagreements are resolved in the open, in the relevant issue or PR.

## Decision principles

When several options are viable, maintainers weigh, in order:

1. **Does it strengthen verification and evidence?** That is the product.
2. **Can an external contributor understand it?** Cleverness that requires
   hidden context is a defect.
3. **Is it testable deterministically?** If we cannot test it, we cannot claim it.
4. **Does it add lock-in?** The core stays vendor-neutral.
5. **Is it the simplest thing that works?** Architecture ambition must not
   outrun the working core.

Rejected proposals get a written reason. "No" with an explanation is more useful
than silence.

## Architecture decision records

Decisions with long-term consequences are recorded in [`docs/adr/`](docs/adr/).
An ADR states the context, the decision, the alternatives considered and the
consequences — including the bad ones. ADRs are not deleted when superseded;
they are marked superseded, so the reasoning stays inspectable.

Open an ADR pull request when a change would:

- alter a core abstraction (goal, plan, task, tool, verifier, evidence),
- add a required dependency,
- change the security model,
- change the public API or CLI contract.

## Becoming a maintainer

There is no application process. Maintainership follows sustained, high-quality
contribution: several merged non-trivial PRs, helpful review of others' work,
and demonstrated judgement about scope. Existing maintainers extend the
invitation.

## Path to shared governance

As the contributor base grows we intend to move toward:

1. **Multiple maintainers** with domain ownership (verification, tools,
   providers, docs).
2. **A published release policy** with semantic versioning and deprecation
   guarantees (targeted at v1.0).
3. **A lightweight RFC process** for significant changes, replacing ad-hoc ADRs.

## Releases

Pre-1.0, releases are cut from `main` when a coherent set of changes has landed.
Breaking changes are possible in any minor version and are listed in
[CHANGELOG.md](CHANGELOG.md). From v1.0 the project commits to semantic
versioning.

## No hidden assumptions

A stated goal of this project is that **no single person's undocumented
knowledge is required to work on it**. If you hit a decision whose reasoning is
not written down anywhere, that is a bug — please open an issue.
