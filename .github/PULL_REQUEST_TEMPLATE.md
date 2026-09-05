## What does this change?

<!-- A short description of the change and the problem it solves. -->

## Why?

<!-- Motivation and context. Link any related issue: Fixes #123 -->

## How did you verify it?

<!-- Be specific. "Added a test" is less useful than "added
     test_x_fails_when_y, confirmed it goes red if I revert the fix". -->

## Checklist

- [ ] `make check` passes (lint, `mypy --strict`, tests)
- [ ] New behaviour has a test **that can actually fail** — I confirmed it goes
      red against the unfixed code
- [ ] Documentation updated if behaviour changed
- [ ] No unsupported claims added to docs (anything aspirational is marked as roadmap)
- [ ] No placeholder files, dead code, or unused dependencies
- [ ] If this changes a core abstraction, the security model, or the public
      API, an ADR is included in `docs/adr/`
