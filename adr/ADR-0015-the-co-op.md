---
adr: 0015
title: The Co-op
component: coop
class: Architecture Component
status: Proposed
date: 2026-05-23
---

# ADR-0015: The Co-op

## Status

Proposed. Promotion to Accepted requires a wired co-op backend in
`server/memory.py` (a second Qdrant client pointed at Qdrant Cloud), a
PII-scrubbing function on the engagement-summary and terminal-finding write
paths, an opt-in env flag (`MR_ROBOT_COOP_ENABLED`), a pseudonymous instance
handle stored in user config, a `doctor` command that reports backend
connectivity (the MCP server, Redis, local Qdrant, aiana, and the co-op's
Qdrant Cloud) and reliably distinguishes "the co-op is live" from "the
co-op silently isn't", and a verified write→read round trip from one
instance to another against a live Qdrant Cloud cluster — mirroring the
end-to-end verification gate used for ADR-0014.

Depends on ADR-0014 (the memory). Reuses its adapter, its embedding pipeline,
and its `Recollection` shape; adds a remote backend and two write/read sites
alongside the existing ones.

## Context

Mr. Robot's judgment compounds across engagements via the memory layer
(ADR-0014) — but only within a single Kali host. Two people running Mr. Robot
against the same HTB lineup learn the same lessons independently, and never
benefit from each other's work.

The point of running the *same boxes other people are running* is that
patterns generalize across operators too: "Lame is SMB → MS17-010", "Vsftpd
2.3.4 backdoor on this port shape", "the rabbit hole on Optimum was the
exploit-db top hit, not the real path". Today every Mr. Robot instance has to
learn those independently.

This ADR records a proposal for a **cooperative cross-operator memory tier** —
a shared, hosted vector store that opted-in instances write *solved* progress
to and read from. It is named **the co-op**, after the user's framing and in
the spirit of the arcade and the memory: a shared space the personas return
to.

The co-op is not a substitute for the memory; it is a second tier above it.
Local memory is private and engagement-rich; the co-op is public and
solved-only.

## Decision

### Qdrant Cloud is the co-op backend

The memory layer already runs on Qdrant locally (ADR-0014). Qdrant Cloud is
the same engine as a hosted service. Reusing it for the co-op means:

- the same embedding pipeline (`all-MiniLM-L6-v2`, 384-dim, cosine);
- the same `Recollection` shape over the wire;
- the same adapter seam (`server/memory.py`) — no second adapter, no second
  schema, no second embedding model.

Connection from `MR_ROBOT_COOP_QDRANT_URL`,
`MR_ROBOT_COOP_QDRANT_API_KEY`, `MR_ROBOT_COOP_QDRANT_COLLECTION`
(default `mrrobot-coop`).

A separate hosted instance was considered (Pinecone, Weaviate Cloud, a custom
HTTP service). Rejected: it would split the adapter, double the embedding
maintenance, and add a schema we'd have to keep in sync with the local one.

### The co-op is opt-in and write-gated

`MR_ROBOT_COOP_ENABLED` defaults to off. With it off, the co-op is invisible —
no reads, no writes, no network traffic to Qdrant Cloud. Identical local
behavior to a Mr. Robot built before this ADR.

With it on:

- **Reads** of the co-op happen *additionally* to local memory reads, at the
  same brain call sites. They are clearly labelled in recollections so the
  brain (and a human reading the report) can distinguish "your own past
  work" from "the co-op says".
- **Writes** to the co-op happen *only when an engagement is solved* — both
  flags captured, terminal condition reached cleanly. Aborted, dead-ended,
  or budget-exhausted engagements write to local memory as before but do
  **not** propagate to the co-op. Solved-only is the simplest defensible
  signal-quality bar; the co-op is for outcomes that worked, not noise.

### Identity is pseudonymous and per-instance

Each Mr. Robot instance generates a stable pseudonymous handle on first run
and stores it in user config (`~/.mr-robot/coop.yaml`):

```
handle: <user-chosen or auto-generated, e.g. "ghost-protocol-7c4">
instance_id: <uuid4>
created_at: <iso8601>
```

Every co-op write is tagged with `handle` and `instance_id`. Readers see the
handle; the instance_id is for self-identification (so the writer can find
or delete its own entries later).

No accounts, no auth beyond the Qdrant Cloud API key. The threat model is
trust-but-verify within an opted-in community, not adversarial multi-tenant
SaaS.

### What gets shared, what gets scrubbed

Two write sites — both campaign-tier, both gated by the solved-only rule and
the opt-in flag.

1. **Solved engagement summary**. The same structured summary the memory
   layer writes locally — `box_name · fingerprint · services ·
   path_that_worked · dead_ends · time_to_user · time_to_root · outcome` —
   passed through a scrubber before upload.

2. **High-confidence terminal findings from a solved box**. Same shape as
   the local memory write site, same scrubber.

The scrubber strips operator-local detail and keeps universal pattern:

| Field | Treatment |
|-------|-----------|
| `box_name` | Kept. HTB box names are public. |
| `box_ip` | **Dropped.** Per-operator on HTB, leaks nothing useful. |
| `fingerprint` | Kept. The whole point. |
| `services`, `web_tech`, `cves` | Kept. |
| `path_that_worked` | Kept at the *technique* level. Concrete shell commands and one-shot URLs are summarized, not pasted. |
| `dead_ends` | Kept. |
| `flag tokens` (user/root) | **Dropped.** Operator-specific secret. |
| `credentials` discovered on the box | **Dropped.** |
| filesystem paths under `engagements/` | **Dropped.** |
| `time_to_user`, `time_to_root` | Kept. |
| `handle`, `instance_id` | Added. |

The scrubber is a single function in `server/memory.py` so its behavior is
auditable and testable. A dry-run mode (`MR_ROBOT_COOP_DRY_RUN=1`) prints
the scrubbed payload instead of uploading — operators can verify what
their instance would share before flipping the opt-in.

Task-outcome writes (the third memory-tier write site, robot-tier) are
**not** propagated to the co-op. Per-task chatter is too noisy and too
operator-specific to generalize; the solved-engagement summary already
distills the durable lesson.

### What gets read, when

Three read sites — the same three sites the memory layer already reads.

1. **Triage** *(orchestrator)*. After `memory_recall_similar(fingerprint)`,
   the brain also calls `memory_recall_coop(fingerprint, k)`. Results are
   merged into a single recollection list, each entry labelled
   `source ∈ {self, coop}` with the co-op handle attached when `coop`.
2. **Reinforce / repurpose** *(orchestrator)*. Same parallel pattern over
   `memory_recall_coop_for_blocker(blocker, findings, k)`.
3. **Task pickup** *(robot)*. Task-tier read is *local-only* in v1 — robots
   do not query the co-op. Rationale: task-tier reads are high-frequency,
   the network cost is meaningful, and task craft is highly Hat-specific
   while the co-op corpus is small and operator-mixed. Revisit when the
   co-op has volume.

Recollections from the co-op carry the same status as recollections from
local memory: **context, not directives**. The scope guard
(per-engagement `box_ip`) and the active Hat's ethics axis are unchanged
and remain the only authorization gates. A co-op recollection that
references a different operator's box does not authorize action on the
current one.

### Adapter surface (v1)

Added to `server/memory.py` alongside the ADR-0014 surface:

```
# Co-op tier — orchestrator only
memory_recall_coop(fingerprint, k=5)                  -> list[Recollection]
memory_recall_coop_for_blocker(blocker, findings, k=5) -> list[Recollection]
memory_share_engagement(summary)                       -> None  # solved only
memory_share_finding(finding, fingerprint)             -> None  # solved + confirmed
```

`Recollection` gains an optional `source: "self" | "coop"` and an optional
`coop_handle: str | None`. Local recollections always have `source="self"`
and `coop_handle=None`.

If the co-op is unavailable (network down, API key missing/invalid, Qdrant
Cloud quota), the layer **degrades to memory-only**: reads return local
results, writes are queued in-process and dropped at engagement end with a
log line. The orchestrator does not halt.

### Governance and moderation

Deferred to open questions. v1 ships with no moderation: the opt-in
community is the only filter. A "report" or "shadow-ban a handle" mechanism
is out of scope here and named below.

### Cost

Qdrant Cloud's free tier covers a small collection comfortably; the per-write
embedding cost is local (CPU-only `all-MiniLM-L6-v2`), so the only marginal
spend is Qdrant Cloud storage + queries. Budget assumption: low-hundreds of
solved engagements across opted-in instances stays well under paid-tier
thresholds. Revisit if growth turns into a real bill.

### Pre-flight checks: the `doctor` command *(upcoming)*

The co-op adds a remote backend (Qdrant Cloud) whose connectivity is harder
to debug than a local service. "It silently degraded and I didn't notice"
is the failure mode this ADR most wants to avoid — a co-op that thinks it
is writing but isn't dilutes operator trust faster than no co-op at all.

The same operability gap already exists, less acutely, for the local stack:
the MCP server can be registered at the wrong scope, Redis can have died,
Qdrant's container can have exited, aiana can be installed in a different
Python. Each is feature-detected at use site, but the operator only finds
out at the first cold-recall, which is the worst time.

This ADR introduces a **`doctor`** command — a single pre-flight check that
verifies every backend the system depends on and prints a status table.
Proposed entrypoint:

```
python3 server/doctor.py
```

What it checks (v1):

| Backend | Check | Required for |
|---------|-------|--------------|
| MCP server | `claude mcp list` shows `mr-robot` with ✓ Connected, at user scope | real (non-mock) runs |
| Redis | `PING` over `MR_ROBOT_REDIS_URL` | memory cache (ADR-0014) |
| Local Qdrant | `GET /readyz` on `MR_ROBOT_QDRANT_URL` | semantic recall (ADR-0014) |
| aiana | `import aiana` succeeds in the same Python `mr_robot.py` uses | memory writes (ADR-0014) |
| Co-op Qdrant Cloud | `GET /readyz` on `MR_ROBOT_COOP_QDRANT_URL` with the configured API key | co-op reads & shares (ADR-0015) |
| Co-op opt-in | `MR_ROBOT_COOP_ENABLED` parsed and consistent with the URL/key being set | co-op reads & shares |

Output is a status table — one row per backend — with one of three states:
**OK** (green ✓), **Degraded** (yellow !) where the backend is missing but
the layer it serves degrades gracefully, or **Fail** (red ✗) where
something the operator clearly intended to be on is not on. Exit code is
non-zero iff any row is Fail.

Behaviour:

- **Boundary, not gating.** `doctor` is advisory — it never starts or
  configures backends, never mutates Claude Code config, never writes to
  Qdrant Cloud. It only inspects. Fixing things stays the operator's job
  and `how-to-install.md`'s job.
- **Solo and on-loop modes.** Solo (default) — run once, print, exit.
  On-loop (`--watch`) — re-checks every N seconds for use during an
  engagement; cheap because every check is read-only.
- **Opt-in-aware.** With `MR_ROBOT_COOP_ENABLED` off, the co-op rows
  report `Disabled` (not Fail). With it on but URL/key missing, those
  rows are Fail — the operator asked for the co-op and it isn't actually
  wired.
- **Machine-readable mode.** `--json` emits the same status as a single
  JSON object so the orchestrator's startup path and CI can consume it
  without parsing text.

Why introduced here: the co-op is the first backend that crosses the
machine boundary, and so the first whose silent degradation is invisible
to the operator until recall returns nothing surprising. The `doctor` is
the smallest tool that closes that gap — and once it exists, covering the
local backends with it is essentially free.

`doctor` is part of this ADR's promotion criterion (see Status): the co-op
does not promote to Accepted until `doctor` exists and reliably distinguishes
"the co-op is live" from "the co-op silently isn't".

## Consequences

**Gains**

- Mr. Robot's judgment compounds across *operators*, not just engagements on
  one host. Lessons from someone else's solve on a box you haven't seen yet
  can shape your triage.
- Reuses ADR-0014's adapter and embedding pipeline — no new schema, no new
  embedding model, no second adapter to maintain.
- Solved-only + scrub-by-default give a defensible default privacy posture:
  what is shared is what was *useful*, stripped of operator detail.
- Opt-in is the safe default — the feature is invisible until consciously
  enabled, so adding it does not change anyone's threat model unless they
  ask for it.

**Costs / tradeoffs**

- New runtime dependency: a hosted Qdrant Cloud cluster. Owned by someone
  (operationally) — naming that owner is its own conversation.
- Cross-operator memory means cross-operator trust. A poisoned entry — a
  recollection that misleads on purpose — degrades brain quality for every
  reader.
- The scrubber is a maintained artifact. A field added to the engagement
  summary that nobody updates the scrubber for *will* leak.
- Even with scrubbing, the act of writing reveals "operator X solved box Y
  at time T" to whoever can read the Qdrant Cloud collection. That is a
  small but non-zero metadata leak.
- The co-op's value is gated on having writers. A near-empty co-op adds
  read latency for no recall gain. There is a chicken-and-egg phase.
- Recall at triage and reinforce/repurpose now does double network work
  (local Qdrant + remote Qdrant Cloud). Tolerable at heartbeat cadence;
  re-examine if the brain's wall-time budget tightens.
- Identity-by-handle is weak. A determined actor can claim someone else's
  handle on a fresh instance.

## Open Questions

- Who hosts and pays for the Qdrant Cloud cluster, and what is the
  governance model when that owner moves on?
- Moderation: report-a-recollection, shadow-ban-a-handle, or trust the
  community filter? When does v1's no-moderation stance break?
- Poisoning resistance — does the brain need a "co-op recollections are
  evidence-grade only when N independent handles converge" rule?
- Identity hardening: do we eventually want signed writes (handle ↔ keypair)
  so handle squatting is detectable?
- Does the co-op include the *playbook* that solved the box, or just the
  outcome? Sharing playbooks is a different consent surface.
- Task-tier reads — does Script Kiddie / Green Hat ever get co-op reads, or
  is the co-op forever campaign-tier only?
- Deletion: how does a writer delete their own entries after the fact
  (regret, mistake, scrubber bug discovered late)? `instance_id` enables
  it; the UX does not exist yet.
- Box-name handling for non-public engagements: if someone points Mr. Robot
  at a non-HTB target with the co-op enabled, the scrubber currently keeps
  `box_name`. Should the co-op be hard-gated to HTB engagements only?
- Versioning the scrubber: when scrubber rules change, do old entries get
  re-scrubbed or accepted as-is?

## Related

- Builds on [ADR-0014 The Memory](ADR-0014-the-memory.md) — same adapter,
  same embedding pipeline, parallel read/write sites.
- Consumed by [ADR-0013 The Orchestrator](ADR-0013-the-orchestrator.md) —
  co-op reads happen at the same brain call sites as memory reads.
- Hat-tier ethics axis (per-Hat ADRs) is unchanged — the co-op does not
  introduce a new authorization gate, only new context.
- External: Qdrant Cloud — https://cloud.qdrant.io
