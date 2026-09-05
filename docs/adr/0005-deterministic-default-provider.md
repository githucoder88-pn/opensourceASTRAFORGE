# 5. Deterministic offline default provider

**Status:** Accepted · **Date:** 2026-09-05

## Context

Most AI tools require an API key before doing anything. The first-run experience
is: install, hit a credentials error, find a key, pay for tokens, and only then
discover whether the tool is any good.

For AstraForge this is worse than an inconvenience. The project's claim is
*"you can verify what the agent did."* A user cannot evaluate that claim if
every attempt costs money and produces different output each time.

## Decision

The default provider is **`echo`**: deterministic, offline, no credentials.

`EchoProvider.complete()` returns a content-addressed summary of the prompt.
Same input, same output, forever. It is the default in `Config`, it is what
`astraforge init` writes, and it is what the entire test suite and every shipped
example use.

## Rationale

This makes several valuable properties true at once:

1. **`pip install` → working demo, in one command.** No signup, no key, no cost.
2. **The test suite is hermetic.** 187 tests, no network, no credentials, no
   flakiness, no bill. CI needs no secrets — so forks and first-time
   contributors get green CI immediately.
3. **Examples are reproducible.** Two runs of the same plan produce identical
   artifact hashes, which is asserted by a test. Users can verify the evidence
   chain works before trusting it.
4. **It separates two questions.** "Does the orchestration, verification and
   evidence machinery work?" is answerable independently of "is the model any
   good?". That separation is what makes AstraForge honestly benchmarkable
   later.

## The honesty obligation

`echo` does not reason. It returns placeholder text.

This creates a real risk of misleading users: a demo where a "model" appears to
produce an approach document is easy to mistake for genuine capability. We
handle this by stating it plainly wherever it could mislead — the README's
[Honest limitations](../../README.md#honest-limitations) section, the
`hello_world` example, and the generated config comments.

Any demo that would be dishonest with `echo` must not be presented as a model
capability demo. The shipped examples are all *machinery* demonstrations, and
say so.

## Alternatives considered

| Alternative | Why not |
| --- | --- |
| **Require a real provider** | Blocks first-run evaluation behind cost and signup; makes CI need secrets; makes examples irreproducible. |
| **Recorded/replayed real responses (VCR)** | Deterministic in tests, but cassettes rot, obscure what is real, and still need a key to re-record. Considerable machinery for the same benefit. |
| **A bundled small local model** | Hundreds of megabytes, platform-specific, slow in CI, and still nondeterministic. |
| **Mocks in tests, no shipped offline provider** | Solves testing but not first-run experience or example reproducibility. |

## Consequences

**Good**

- Zero-friction evaluation; contributors get green CI with no setup.
- Reproducibility is a testable property, not a promise.
- Provider abstraction is exercised by two real implementations from day one.

**Bad**

- The out-of-the-box experience does not showcase model capability, which is
  what many visitors expect from an "AI" project. We accept looking less
  impressive in exchange for being verifiable.
- Requires ongoing discipline in documentation to avoid implying `echo` output
  is meaningful.
- The `heuristic` planner has to work without model reasoning, which is why it
  produces a fixed honest task graph rather than pretending to understand goals.
