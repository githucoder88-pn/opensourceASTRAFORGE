# ADR 0006: Hash-chain the event log

- **Status:** Accepted
- **Date:** 2026-09-05

## Problem

AstraForge's claim is that autonomous work should be *independently verifiable*.
Artifacts were content-addressed from v0.1, so a modified output file is caught
by `astraforge verify`.

The execution log was not protected at all. An audit confirmed that any line in
`events.jsonl` could be edited, reordered, deleted or truncated, and every
AstraForge command still reported the run as fully verified.

That is the wrong asymmetry. The log is the more attractive target: it holds the
record of the task that failed, the policy that blocked a tool, the retry that
was needed and the approval that was refused. An adversary — or an
embarrassed operator — hides a problem by deleting the event describing it, not
by editing the output file.

A proof-of-work report is only as trustworthy as the history it summarises.

## Options considered

1. **Do nothing.** Document that the log is trusted. Cheapest, but it leaves the
   project's central claim resting on an unverified file.
2. **Sign each event with a keypair.** Strongest: detects wholesale
   regeneration, not just edits. Requires key generation, storage, rotation and
   a trust story for where the key lives. On a single-user local machine the key
   sits next to the log it protects, so the added guarantee is largely
   illusory while the complexity is real.
3. **Append-only OS enforcement** (`chattr +a`, WORM storage). Genuinely strong,
   platform-specific, needs privileges, and does not survive `git clone` of a
   run directory.
4. **Unkeyed hash chain.** Each event stores its position, the digest of the
   previous event and its own digest. Detects any modification of recorded
   history. Costs one SHA-256 per event and no configuration.
5. **External timestamp authority / transparency log.** Detects regeneration
   properly, but requires a network service and turns an offline-first tool into
   one with an external dependency.

## Decision

Adopt **option 4**, the unkeyed hash chain, and pin the event count and final
digest in `run.json`.

Rationale:

- It closes the actual observed gap — silent alteration of recorded history —
  at essentially zero cost and with no new dependency, configuration or
  privilege.
- It preserves every property that made JSONL the right choice in ADR 0003: the
  log stays greppable, diffable, streamable and readable without AstraForge.
- Signing (option 2) does not meaningfully improve the local single-user threat
  model, because the signing key would live on the same machine as the log.
  It becomes worthwhile once runs execute on a remote runner and are shipped
  elsewhere for audit, which is a v0.3 concern, not a v0.1 one.
- The chain is a strict prerequisite for signing anyway: signing the chain head
  is a small later change that covers every event at once.

The count/head pin exists because a chain *prefix* is internally consistent, so
hashing alone cannot detect events dropped from the end.

## Consequences

**Gained.** Editing, deleting, reordering and truncating events are all detected
and reported by `astraforge verify` with a non-zero exit code. The event that
broke the chain is named.

**Not gained — and this must stay documented.** The digests are unkeyed. Anyone
who can write to the run directory can also discard the log and generate a
fresh, internally consistent one. This is tamper *evidence*, not tamper
*proofing*. `SECURITY.md`, `docs/concepts/evidence.md` and the README all state
this limitation directly; removing that wording would turn a real property into
an overclaim.

**Compatibility.** Events written before this change have no `entry_hash` and are
reported as *unverifiable*, never as tampered — upgrading must not retroactively
accuse old runs of forgery.

**Cost.** One SHA-256 over a small JSON object per event, and three extra fields
per line. Both are negligible relative to tool execution.

**Follow-up.** When remote execution lands, sign the chain head so a run can be
audited by someone who does not trust the machine that produced it.
