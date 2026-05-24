---
adr: 0016
title: Lifecycle, Deadlines, and Constraint IDs
component: orchestrator
class: Architecture Component
status: Accepted
date: 2026-05-23
---

# ADR-0016: Lifecycle, Deadlines, and Constraint IDs

## Status

Accepted — built and verified on 2026-05-23. Three patterns land together
because they came out of the same TAEM-framework review and they are each
small in isolation; bundling avoids three ADR ceremonies for one
afternoon of work.

The promotion criteria are each named below as a constraint and are
verifiable from the runtime today:

- **C-0016-001** — engagement lifecycle events. `Orchestrator.run()` no
  longer calls `_persist_memory()` and `_report()` inline; both are
  subscribers on the `engagement_ended` event emitted by
  `server/events.py`.
- **C-0016-002** — declared deadlines on external calls. Every external
  call in the codebase is bounded by an env-tunable deadline
  (`MR_ROBOT_QDRANT_DEADLINE_SECONDS`,
  `MR_ROBOT_REDIS_DEADLINE_SECONDS`,
  `MR_ROBOT_RECON_DEADLINE_SECONDS`), not a hard-coded constant.
- **C-0016-003** — constraint IDs. ADR-0014 and ADR-0015 carry explicit
  `C-NNNN-NNN` IDs on their contractual statements so `doctor` (proposed
  in ADR-0015) can report per-constraint, not per-paragraph.

Depends on ADR-0013 (orchestrator), ADR-0014 (memory), ADR-0015 (co-op).
Does not supersede any of them.

## Context

A TAEM-framework review (`taem-dev/refexplorer`, 2026-05-23) surfaced
three small patterns that fit Mr. Robot cleanly:

1. **Kernel closes missions; other things react.** TAEM's worker
   (`refexplorer`) does not run inside the kernel's mission loop; it is
   triggered by a `MISSION_LANDED`-shaped event after the mission closes.
   Mr. Robot's orchestrator today fuses control with persistence — the
   tail of `run()` called `_persist_memory()` and `_report()` inline. Any
   future consumer of terminal-state work (co-op share, htb-research
   enrichment, structured engagement reports) would have to edit `run()`.
   A small event bus inverts that.

2. **Declared envelopes on every external call.** TAEM's job manifest
   carries `activeDeadlineSeconds`, `backoffLimit`,
   `ttlSecondsAfterFinished`, and per-API rate limits as declared config,
   not as code. Mr. Robot has `--max-ticks 400` (an envelope on the loop)
   and a hard-coded `timeout=600` on the nmap subprocess (an envelope on
   one call) but no envelope on Qdrant or Redis. The co-op (ADR-0015) is
   the first cross-machine dependency; without declared deadlines its
   silent-degradation failure mode is unbounded.

3. **Constraint IDs (`C-NNN-NNN`).** TAEM annotates every contractual
   statement with a stable ID (e.g. `C-009-009`, `C-009-008`). Mr.
   Robot's ADRs are prose; the proposed `doctor` (ADR-0015) can verify
   "the layer is live" but not "constraint C-0014-005 holds." Adding
   stable IDs makes each ADR's promotion criteria something a script
   can assert and `doctor` can name.

None of the three patterns is novel. The point of this ADR is to record
that they were chosen together, with named bounds, and to give the
runtime the constraint IDs it can promote against.

## Decision

### Engagement lifecycle events

A new module `server/events.py` defines a small per-orchestrator
`EventBus` with `subscribe(event, fn)` and `emit(event, **payload)`.
Subscriber exceptions are logged but never propagate — one bad subscriber
must not break the control loop.

`Orchestrator.__init__` subscribes its own terminal-state methods
(`_persist_memory`, `_report`) to the `engagement_ended` event. `run()`
emits `engagement_started` once after the engagement row exists, and
`engagement_ended` once after the loop drains. The inline calls at the
tail of `run()` are removed.

Events for v1 are intentionally minimal:

| Event | Payload | When |
|-------|---------|------|
| `engagement_started` | `engagement: dict` | After `_ensure_engagement`, before the first tick |
| `engagement_ended` | `engagement: dict` | After `_drain`, before `run()` returns |

Outcome (complete / exhausted / aborted) is derivable from the engagement
row; subscribers compute it themselves. Future events
(`flag_user_captured`, `flag_root_captured`, finer-grained
`engagement_dead_ended`) are deferred — they require hooks into the
arcade write path and are not needed by today's subscribers.

The bus is **per-orchestrator**, not a process singleton. Two orchestrators
in the same process get two buses, so their subscribers do not collide.

### Declared deadlines

Every external call gets an env-tunable deadline. Defaults are chosen
from observed working envelopes, not from theory.

| Env var | Default | Bounds |
|---------|---------|--------|
| `MR_ROBOT_QDRANT_DEADLINE_SECONDS` | `5` | Qdrant HTTP client timeout |
| `MR_ROBOT_REDIS_DEADLINE_SECONDS` | `2` | Redis `socket_connect_timeout` + `socket_timeout` |
| `MR_ROBOT_RECON_DEADLINE_SECONDS` | `600` | nmap subprocess timeout |

The 5s and 2s defaults are chosen to be ~50–300× the observed local
round trips from the ADR-0014 verification (17 ms cold / 0.1 ms cached)
— generous enough not to trip on noise, tight enough that a stuck cloud
backend dies in seconds, not minutes. The 600s default for nmap is the
pre-existing constant, preserved as the default to avoid a behaviour
change.

Co-op cloud writes, MCP-mode hops, htb-api calls, and htb-research
fetches do not yet exist as code; their deadline knobs land in their
respective ADRs when the code does. The pattern (named env var, sensible
default, applied to the underlying client's timeout) is what this ADR
sets.

### Constraint IDs

Each ADR's Status section (and inline where load-bearing) carries
`C-NNNN-NNN` constraint IDs on its contractual statements. Format:
`C-` + 4-digit ADR number + `-` + 3-digit constraint number, e.g.
`C-0014-003`. The 4-digit ADR half mirrors Mr. Robot's existing ADR
numbering (ADR-0014, ADR-0015); TAEM's 3-digit form would conflict.

This revision annotates:

- **ADR-0014 (the memory)** with C-0014-001 through C-0014-009, covering
  the three-backend contract, the embedding model, the degradation
  paths, the cache-generation invariant, the adapter seam, the scope
  guard's authorization role, and the two ADR-0016 deadlines.
- **ADR-0015 (the co-op)** with C-0015-001 through C-0015-011, covering
  cloud mode, event mode, the doctor command, and the non-gating
  htb-api sibling — grouped so each subset (cloud / event / doctor)
  can promote on its own.

ADR-0013 (the orchestrator) is *not* annotated in this revision — its
contract surface is larger and IDs there should follow, not precede,
the next substantive update.

The `doctor` command (ADR-0015) will eventually print per-constraint
status. This ADR does not build `doctor`; it makes the IDs that
`doctor` will reference.

**Numbering rule.** IDs are append-only. A constraint that is removed
or replaced stays in its position with a `(deprecated, see C-XXXX-YYY)`
marker; renumbering would re-baseline every reference (in the runtime,
in `doctor`, in `journeys/`) and is therefore disallowed.

## Consequences

**Gains**

- Future ADRs (htb-research, co-op share, structured engagement reports)
  attach as subscribers without editing `Orchestrator.run()`.
- External calls die at named deadlines, not at whichever OS-level
  timeout fires first. The co-op's silent-degradation worst case
  (ADR-0015's most-feared failure mode) is bounded before the co-op
  ships.
- Each ADR's promotion criteria becomes something `doctor` can name and
  a script can assert.
- The bundled ADR matches the bundled work — one design conversation,
  one record, one mock-run verification.

**Costs / tradeoffs**

- The event bus is intentionally tiny — no async dispatch, no priority,
  no replay, no off-process subscribers. A future ADR that wants any of
  those properties replaces or extends the bus; it does not co-opt it.
- The default deadlines (5s / 2s) are guesses informed by one
  measurement on a local Qdrant + local Redis. Qdrant Cloud or a
  remote Redis may have a worse tail and require a revisit.
- Constraint IDs on prose ADRs are maintained text — the append-only
  rule prevents drift but at the cost of carrying deprecated IDs
  forever once they exist.
- Three concerns in one ADR makes the per-constraint promotion paths
  more interlocking than usual. The three are deliberately each small
  enough that this isn't a meaningful slowdown.

## Open Questions

- More event types (`flag_user_captured`, `flag_root_captured`,
  `engagement_dead_ended`) — wait for the first subscriber that needs
  them, or front-run by adding them now?
- Async dispatch — should `emit` return immediately and subscribers run
  on a task queue? Today's subscribers are sync and fast; not needed
  yet.
- `doctor` per-constraint output — table format, JSON, or both?
- Should `--max-ticks` migrate to `MR_ROBOT_LOOP_DEADLINE_TICKS` to
  match the env-var pattern, or stay a CLI arg?
- When ADR-0013's next substantive revision lands, should the
  orchestrator's constraints (Hat-for-life, pool budget, mechanical
  vs. judgment split) get C-0013-NNN IDs too, or is the orchestrator
  ADR small enough that prose alone is fine?

## Related

- Refactors [ADR-0013 The Orchestrator](ADR-0013-the-orchestrator.md) —
  `run()` emits lifecycle events instead of calling persistence and
  reporting inline.
- Constrains [ADR-0014 The Memory](ADR-0014-the-memory.md) — annotated
  with C-0014-NNN this revision; gains a Qdrant + Redis deadline.
- Constrains [ADR-0015 The Co-op](ADR-0015-the-co-op.md) — annotated
  with C-0015-NNN this revision; `doctor` will consume the constraint
  IDs once built.
- Reference: TAEM framework (`taem-dev/refexplorer`) — the patterns came
  from a review of `job.yaml` and `refexplorer.py` on 2026-05-23.
