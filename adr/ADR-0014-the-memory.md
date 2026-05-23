---
adr: 0014
title: The Memory
component: memory
class: Architecture Component
status: Accepted
date: 2026-05-22
---

# ADR-0014: The Memory

## Status

Accepted — built and verified end-to-end on 2026-05-23 with all three
backends live (aiana/SQLite-FTS5 in `~/.aiana/conversations.db`, Qdrant
v1.18.1 in a local container, Redis 8.x as a user-mode daemon on
`127.0.0.1:6379`). The full write/read/cache-invalidate cycle was exercised
through every public adapter method via `/tmp/mr_robot_memory_e2e.py`.
Depends on ADR-0012 (the arcade) and ADR-0013 (the orchestrator); resolves
the open question in ADR-0012 on cross-engagement state.

## Context

The arcade (ADR-0012) is engagement-scoped: when a box is done, its workspace
is archived and the next engagement starts cold. The orchestrator (ADR-0013)
drives the engagement, and its LLM brain makes the campaign-shaping decisions
(triage, reinforce, repurpose) — but it makes them with no recollection of any
prior box. Every engagement is a fresh start.

That is wrong for HTB specifically. The point of running many boxes is that
*patterns generalize*: "Vsftpd 2.3.4 + anonymous FTP → known foothold", "this
recon shape played out as SMB + MS17-010 last time", "we hit this dead-end on
Lame too". Without memory, Mr. Robot's judgment is as sharp on box #50 as on
box #1 — and Mr. Robot's judgment is the project's standout.

This ADR records the decision to add a **cross-engagement memory layer** and
to adopt **aiana** (https://github.com/ry-ops/aiana) as that layer rather than
build one from scratch. The arcade remains engagement-scoped; cross-engagement
state lives in a separate component called **the memory**.

## Decision

### Aiana is the memory layer

Aiana is selected because it already provides what we need — semantic recall
over a growing corpus, SQLite + vector storage, MCP and Python interfaces —
and building this ourselves is a sizeable side quest off the critical path.

Aiana's design center is capturing Claude Code conversations via Hooks. We use
it differently — as a structured-write store driven by the orchestrator — but
its Python API and MCP tools support that usage. The mismatch is real but
narrow, and it is contained behind an adapter (below).

### Backends: SQLite + Qdrant + Redis

- **SQLite** (`~/.aiana/conversations.db`) — durable storage with FTS5
  full-text search across every engagement summary and high-confidence finding.
- **Qdrant** — vector storage. The embedding engine
  (sentence-transformers `all-MiniLM-L6-v2`, 384-dim, cosine) turns each
  memory entry into a vector so the brain can ask "boxes like this one" by
  recon fingerprint. URL from `MR_ROBOT_QDRANT_URL`
  (default `http://localhost:6333`); collection from
  `MR_ROBOT_QDRANT_COLLECTION` (default `mrrobot-memory`). Reads fuse FTS5
  and Qdrant via reciprocal rank fusion (k=60).
- **Redis** — recall cache in front of the FTS5/Qdrant read path. URL from
  `MR_ROBOT_REDIS_URL` (default `redis://localhost:6379/0`); TTL from
  `MR_ROBOT_MEMORY_CACHE_TTL_SECONDS` (default 600s). Invalidation is by
  generation counter: every write `INCR`s `mrrobot:memory:gen` and the gen
  value is folded into each cache key, so writes invalidate all cached
  reads without an exhaustive scan.

Redis is in scope because triage and reinforce/repurpose can call into
memory multiple times per heartbeat as the brain explores; the cache
amortizes the embedding + Qdrant round-trip across those reads, which is
the slowest path in the recall flow.

Mem0 is deferred — its automatic extraction and dedupe are valuable but add
another dependency and a behaviour we have no use for until the corpus is
large; revisit at hundreds of summaries.

If Qdrant is unavailable, the memory layer **degrades to FTS5-only**. Brain
quality drops; the orchestrator does not halt.
If Redis is unavailable, the cache is bypassed and reads hit the
SQLite/Qdrant path directly; writes are unaffected.

### Memory is used across both tiers

Both the orchestrator and the robots read and write memory.

- **Orchestrator** uses memory for *campaign* judgment — triage direction,
  reinforce/repurpose decisions — and writes the engagement-end summary plus
  high-confidence terminal findings.
- **Robots** use memory for *task* judgment — "have I (as this Hat) faced
  this kind of task before? what worked? what dead-ended?" — and write a
  short task-outcome recollection of their own work on completion or
  dead-end.

This is a deliberate widening from an orchestrator-only design. The tradeoff
is a larger robot tool surface and more write traffic into aiana; the gain is
that every Hat's craft compounds over time, not just the brain's strategy.

### Integration model

Two paths into the same aiana store — one per tier — sharing a single
adapter.

- **Orchestrator** imports aiana's Python package directly via a thin adapter
  at `server/memory.py`. No MCP round-trip for the control loop. Mirrors the
  arcade pattern from ADR-0013.

- **Robots** reach memory through the existing `mr-robot` MCP server, which
  gains a new tool family (`memory_*`) backed by the same `server/memory.py`
  adapter. Robots do not get a second MCP server — the tool surface stays
  unified.

`server/memory.py` is the single seam over aiana. Both tiers go through it,
and the underlying implementation is replaceable without touching callers.

Adapter surface (v1):

```
# Campaign tier — orchestrator only, direct import
memory_recall_similar(fingerprint, k=5)             -> list[Recollection]
memory_recall_for_blocker(blocker, findings, k=5)   -> list[Recollection]
memory_record_engagement(summary)                   -> None
memory_record_finding(finding, fingerprint)         -> None   # confirmed only

# Task tier — robots, exposed as mr-robot MCP tools
memory_recall_for_task(task, hat, k=5)              -> list[Recollection]
memory_record_task_outcome(task, hat, outcome)      -> None
```

`Recollection` carries `box_name · summary · score · tags{services, cves,
dead_ends, hat, task_type}`. The adapter handles aiana's session/note
primitives underneath and computes fingerprints; callers do not see aiana
types.

### What gets written, when

Three write sites — two campaign-tier, one task-tier.

1. **Engagement end** *(orchestrator)*. Terminal condition: both flags, no
   actionable work, or budget exhausted. The orchestrator composes one
   structured summary — `box_name · fingerprint · services ·
   path_that_worked · dead_ends · time_to_user · time_to_root · outcome` —
   and records it as a single memory entry. One per engagement.

2. **High-confidence terminal findings** *(orchestrator)*.
   `type ∈ {foothold, privesc_vector, flag}` with `confidence == confirmed`,
   tagged with the box fingerprint. Denormalized "what unlocked things on
   what kind of box" view to complement the summary.

3. **Task outcome** *(robot)*. On `complete` or `dead_end`, the robot writes
   a short recollection of *its* work on *its* task — the task type, the
   approach tried, whether it worked, and any non-obvious thing it learned.
   Tagged with its Hat, the task type, and the box fingerprint. One entry
   per task, not per heartbeat — the goal is durable craft, not chatter.

Lower-confidence findings and the full task board are **not** written. The
arcade owns those for the duration of the engagement; nothing about the
moment-to-moment churn generalizes.

### What gets read, when

Three read sites — two in the orchestrator brain, one at the robot tier. The
mechanical scheduler never consults memory.

1. **Triage** *(orchestrator)*. When the seed recon lands, the brain calls
   `memory_recall_similar(fingerprint)` and includes the top-k recollections
   in its first direction-decision prompt.

2. **Reinforce / repurpose** *(orchestrator)*. When a robot reports a
   structured blocker, the brain calls
   `memory_recall_for_blocker(blocker, findings)` so its prompt can include
   "we've been here" context alongside the live board state.

3. **Task pickup** *(robot)*. When a robot claims a task, its first move can
   be `memory_recall_for_task(task, hat)` — surfacing past approaches its
   own Hat has tried for similar tasks. Result feeds the robot's planning,
   not the orchestrator's.

Recollections are *context*, not directives. Both tiers decide what to do
with them, and both remain bound by the scope guard and the active Hat's
ethics axis.

### Box fingerprint

The recall key. Derived from arcade state at fingerprint time:

- OS family (nmap)
- open ports (sorted)
- service banners (normalized — version stripped to `major.minor`)
- web tech (server, framework) when present

Fingerprints are computed by the adapter, not stored in the arcade — they are
a memory-layer concern. The same arcade state always yields the same
fingerprint.

### Lifecycle

Memory is global to the Kali host and accretes across engagements. There is
no scheduled pruning in v1 — aiana owns storage. Misleading entries can be
deleted via aiana's CLI.

### Safety

Memory recall is read-only with respect to operational scope. A recollection
from a past box does **not** authorize action on the current one. The scope
guard (per-engagement `box_ip`) is unchanged and remains the only
authorization gate. The brain may suggest a path informed by memory; that
path is still bound by the active Hat's ethics axis and the scope guard.

## Consequences

**Gains**

- Mr. Robot's judgment compounds at *both* tiers — the brain's campaign
  strategy and each Hat's task craft. The project's stated purpose actually
  shows up at box #20+.
- ADR-0012's cross-engagement memory question is resolved without coupling
  it back into the arcade.
- Reuses aiana — a substantial build is avoided, and aiana remains
  independently useful as a personal memory layer.
- One adapter, two tiers — the seam keeps aiana swappable, and writes from
  either tier benefit reads from either tier (same store).

**Costs / tradeoffs**

- New runtime dependency: aiana + Qdrant (extra service to keep running).
- Aiana is being used outside its design center (structured writes vs.
  Hooks-captured conversations). Upstream changes may require adapter shims.
- Embedding cost per write (CPU-only `all-MiniLM-L6-v2`). Cheap, but nonzero.
- Larger robot tool surface — every Hat now sees `memory_*` tools and must
  reason over when to use them. Per-Hat gating in the Hat ADRs mitigates.
- More write traffic — robots also write, so memory growth and noise are
  larger than an orchestrator-only design. Task-outcome quality varies by
  Hat; weak entries dilute recall.
- Memory quality is only as good as its writers. The engagement-summary
  prompt *and* the task-outcome prompt become maintained artifacts.
- Recall at both tiers grows the per-engagement token bill.
- Redis is one more service to keep running on the Kali host.
- Cache invalidation is coarse — every write bumps the generation counter,
  invalidating all cached reads. Acceptable at heartbeat cadence; revisit
  if write rate climbs.

## Open Questions

- Where do the summarization and task-outcome prompts live — orchestrator /
  robot code, or playbook-style files alongside `htb-default.yaml`?
- Are dead-ends surfaced as explicit *negative* signals, or is
  similarity-plus-summary enough for callers to infer "don't"?
- Recall scoping at the robot tier — does a White Hat recall *only* past
  White Hat work, or also relevant work from related Hats (Gray, Red Team)?
- Per-Hat tool gating — do all Hats get the full `memory_*` surface, or do
  some (Script Kiddie, Gray) get a reduced read-only subset?
- Redis deployment on Kali — host service or container? Same volume strategy
  question as Qdrant.
- Pin aiana to a known-good version, or track upstream? Vendor on breakage?
- v2: feed memory back into the playbook engine — auto-suggest new unlock
  rules from patterns that recur across boxes?

## Related

- Resolves the cross-engagement open question in
  [ADR-0012 The Arcade](ADR-0012-the-arcade.md)
- Sole consumer is [ADR-0013 The Orchestrator](ADR-0013-the-orchestrator.md)
- External: aiana — https://github.com/ry-ops/aiana
- Future: a playbook-evolution ADR that consumes memory
