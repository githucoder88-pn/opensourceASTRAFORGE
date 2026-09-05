# 2. Apache-2.0 license

**Status:** Accepted · **Date:** 2026-09-05

## Context

AstraForge is infrastructure intended for developers, startups, universities and
enterprises. The license affects adoption more than almost any other early
decision, and changing it later requires consent from every contributor — so it
should be chosen deliberately rather than by habit.

Requirements:

1. Commercial use without friction (enterprise legal review must be a
   non-event).
2. An **explicit patent grant** — AstraForge executes code and takes actions on
   a user's behalf; the patent surface of automated software engineering is
   non-trivial, and users deserve protection.
3. Compatibility with all dependencies.
4. A contribution model that does not require a CLA to be safe.

## Decision

**Apache License 2.0.**

## Alternatives considered

| License | Assessment |
| --- | --- |
| **MIT** | Maximum adoption and very familiar, but **no express patent grant**. For a tool that executes code autonomously, that gap matters. |
| **BSD-3-Clause** | Same patent gap as MIT. |
| **MPL-2.0** | File-level copyleft. Compatible with commercial use, but the per-file obligation is an unnecessary review burden for adopters, and it deters vendoring. |
| **GPL-3.0 / AGPL-3.0** | Would prevent the most likely adoption path — embedding AstraForge inside internal and commercial tooling. AGPL in particular would make it unusable as a service component for most companies. Kills the "standard infrastructure" ambition. |
| **BSL / SSPL / "fair source"** | Not OSI-approved open source. Contradicts the project's stated philosophy of no proprietary lock-in. |

## Dependency compatibility

Verified against the actual installed dependency tree (`importlib.metadata`),
not assumed:

| Package | License | Compatible |
| --- | --- | --- |
| pydantic | MIT | ✅ |
| pydantic-core | MIT | ✅ |
| annotated-types | MIT | ✅ |
| typer | MIT | ✅ |
| click | BSD-3-Clause | ✅ |
| rich | MIT | ✅ |
| Pygments | BSD-2-Clause | ✅ |
| markdown-it-py | MIT | ✅ |
| mdurl | MIT | ✅ |
| PyYAML | MIT | ✅ |
| shellingham | ISC | ✅ |
| typing-extensions | PSF-2.0 | ✅ |

All permissive; none impose obligations conflicting with Apache-2.0. The
optional `openai` SDK is Apache-2.0. Dev-only tools (pytest, ruff, mypy) are MIT
and are not distributed with the package.

## Consequences

**Good**

- Explicit patent grant and contributor patent retaliation clause.
- Enterprise-friendly; widely pre-approved by legal teams.
- The Apache-2.0 contribution terms (§5) mean **no CLA is needed** — inbound
  contributions are automatically licensed under the same terms.
- Compatible with the ecosystem AstraForge integrates with.

**Bad**

- Slightly more ceremony than MIT: the `NOTICE` convention and requirement to
  state changes in modified files.
- Permissive licensing allows a proprietary fork. We accept this: adoption as
  shared infrastructure matters more than preventing it, and copyleft would
  block the primary use case.
- Apache-2.0 is one-way incompatible with GPLv2 (though fine with GPLv3).
