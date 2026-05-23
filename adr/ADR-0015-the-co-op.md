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

Proposed. The ADR proposes three federation modes (**cloud**, **event**,
and **mcp**) and an upcoming sibling MCP server (**`htb-api`**). Each part
promotes independently against its own criterion:

- **Cloud mode → Accepted** when `server/memory.py` carries a second Qdrant
  client pointed at Qdrant Cloud, the PII-scrubbing function gates the
  engagement-summary and terminal-finding write paths, the opt-in env flag
  (`MR_ROBOT_COOP_ENABLED`) and pseudonymous instance handle land in user
  config, and a write→read round trip between two real instances over a
  live Qdrant Cloud cluster is verified end-to-end (mirroring the ADR-0014
  gate).
- **Event mode → Accepted** when `mr-robot coop host start` /
  `mr-robot coop join` exist with the join-key issuance and validation
  flow, the host's local Qdrant serves participant writes/reads under that
  key for the session's TTL, and a write→read round trip between two real
  instances over a third host instance is verified.
- **MCP mode → Accepted** when `server/memory.py` can route its cloud-tier
  Qdrant *and* Redis I/O through MCP servers (Qdrant via
  `mcp-server-qdrant`, Redis via Redis Inc.'s `mcp-redis`) selected by
  `MR_ROBOT_COOP_TRANSPORT=mcp`, both servers are registered at user scope
  alongside `mr-robot`, the scrubber gates the same write paths regardless
  of transport, and a write→read round trip between two real instances
  over MCP-routed Redis Cloud + Qdrant Cloud is verified end-to-end.
- **`doctor` command → required for all three** — must report backend
  connectivity (MCP, Redis, local Qdrant, aiana, cloud-mode Qdrant Cloud,
  the event-mode host endpoint when a session is joined, *and* the
  MCP-mode `mcp-server-qdrant` + `mcp-redis` servers when that transport
  is selected) and reliably distinguish "the co-op is live" from "the
  co-op silently isn't".
- **`htb-api` MCP server** — named here but graduates via a future ADR;
  not gating co-op promotion.

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

### Three federation modes: cloud, event, and mcp

The co-op proposes three complementary federation models. All write
through the same scrubber and `Recollection` shape; they differ in *where*
the shared vector store lives, *who* it is shared with, and *how* the
adapter reaches it on the wire.

**Cloud mode.** Async, global, always-on. Opted-in instances write solved
progress to a shared Qdrant Cloud collection and read it back at the
campaign-tier read sites. Best for cross-time learning — "what worked on
Lame last year, by anyone." Transport is the Qdrant Python client
directly against Qdrant Cloud's HTTP/gRPC endpoint.

**Event mode** *(planned)*. Per-event, peer-hosted, time-bounded. One
operator starts a session and becomes its **host**; their *local* Qdrant
becomes the shared source of truth for the event. Participants attach via
a **join key** the host shares out of band. For the duration of the
event, every participant's `memory_share_*` writes and
`memory_recall_coop` reads route through the host's vault. When the
event ends, each participant's local memory retains what it absorbed;
the host's local Qdrant accretes the full event corpus.

**MCP mode** *(planned)*. Same destinations as cloud mode (managed
Qdrant, optionally managed Redis), but the transport is an MCP server in
front of each backend rather than a Python client. The adapter speaks the
same `memory_*` shape; the wire underneath becomes
`mcp-server-qdrant` (for the co-op collection on Qdrant Cloud) and
`mcp-redis` (for the recall cache on Redis Cloud). This keeps every
remote dependency on the *same* protocol Mr. Robot itself already speaks
— a uniform pattern of "external service via MCP" — and pushes
credential handling out of `server/memory.py` and into Claude Code's MCP
config, where the rest of the project's secrets already live.

All three modes can be active at once on the same instance: writes fan
out to each configured backend (cloud + event-host + MCP), reads merge
results with `source ∈ {self, coop:cloud, coop:event, coop:mcp}` so the
brain and human readers can tell them apart.

Why event mode is wanted:

- HTB Battlegrounds, new-release box drops, university CTFs — anything
  time-bounded and collaborative wants its operators in *one session*
  sharing findings *now*, not consulting a vector store of months-old
  global solves.
- No third-party hosting required for a one-off event. A single trusted
  host (whoever starts the session) is the natural moderation point —
  much simpler than the cloud-mode trust model.
- HTB-specific events want a join-and-go ritual that fits the time
  pressure of a release night.

### Qdrant Cloud is the cloud-mode backend

The memory layer already runs on Qdrant locally (ADR-0014). Qdrant Cloud is
the same engine as a hosted service. Reusing it for cloud-mode means:

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

### MCP-routed cloud connectivity (mcp mode)

Cloud mode reaches Qdrant Cloud through the Qdrant Python client and (in
ADR-0014) reaches local Redis through `redis-py`. Both clients require
their credentials to live in `MR_ROBOT_*` environment variables that
`server/memory.py` reads at startup. That works, but it puts the project
in the awkward position of speaking MCP outward (Mr. Robot itself is an
MCP server) while speaking two unrelated client protocols inward, with
two more credentials Claude Code never sees.

This ADR proposes a third federation mode where the cloud-tier Qdrant
*and* the recall-cache Redis are reached through their official MCP
servers instead:

| Backend | MCP server | Hosted at | Credential lives in |
|---------|-----------|-----------|---------------------|
| Qdrant (co-op collection) | `mcp-server-qdrant` (Qdrant Inc., upstream) | Qdrant Cloud | Claude Code MCP config |
| Redis (recall cache, optional cloud tier) | `mcp-redis` (Redis Inc., upstream) | Redis Cloud (or self-hosted) | Claude Code MCP config |

Selection is opt-in via a new env knob:

```
MR_ROBOT_COOP_TRANSPORT=direct   # default — Python clients, as in cloud mode
MR_ROBOT_COOP_TRANSPORT=mcp      # route co-op Qdrant + Redis I/O via MCP
MR_ROBOT_COOP_TRANSPORT=both     # primary MCP, fall back to direct on MCP error
```

What the adapter does in MCP mode:

- **Qdrant calls** (`upsert`, `search`, `delete`) become tool calls on
  `mcp-server-qdrant` against the configured `mrrobot-coop` collection.
  The embedding step is **still local** (`all-MiniLM-L6-v2`, 384-dim,
  cosine) — `mcp-server-qdrant` accepts pre-computed vectors and the
  project keeps a single source of truth for embeddings across cloud and
  MCP modes.
- **Redis calls** (`GET`, `SET`, `INCR mrrobot:memory:gen`) become tool
  calls on `mcp-redis`. The generation-counter invalidation pattern from
  ADR-0014 is unchanged — `mcp-redis` exposes `INCR` and arbitrary key
  reads/writes, which is everything the cache needs.
- **The scrubber still runs first.** Transport selection is below the
  scrubber boundary; whatever leaves the scrubber is what the MCP server
  sees, no exceptions.

Why this is wanted:

- **Uniform external-services pattern.** Mr. Robot already exposes itself
  as an MCP server and already requires `claude mcp list` to show
  `mr-robot` at user scope. Putting Qdrant and Redis on the same surface
  means one mental model — "every external dependency is an MCP server"
  — and one place to register them.
- **Credentials out of process env.** Qdrant Cloud API keys and Redis
  Cloud auth tokens move into Claude Code's MCP config (per-server
  `env`), where they sit alongside any other secret an MCP server needs.
  `server/memory.py` stops needing to read them at all.
- **`doctor` already knows how to introspect MCP.** Its first row is
  `claude mcp list` parsing; extending that to assert
  `mcp-server-qdrant` ✓ and `mcp-redis` ✓ is cheaper than teaching it a
  new health-check shape per backend.
- **Lower setup friction for new operators.** A new contributor who
  already followed `how-to-install.md` to register `mr-robot` adds two
  more `claude mcp add` lines and is done — no Python virtualenv
  juggling for `qdrant-client` or `redis-py` versions.
- **Cloud-managed by default.** `mcp-redis` against Redis Cloud removes
  the "is your local Redis daemon up?" failure mode (today the most
  common cause of degraded recall on a fresh Kali). The cache stays a
  cache; if Redis Cloud blips, the layer degrades to direct
  FTS5/Qdrant exactly as it does today.

Why it's gated behind an opt-in transport and not the default:

- Adds a network hop per call. Cold recall in ADR-0014 measured ≈ 17 ms
  cold / ≈ 0.1 ms cached; MCP-routed calls re-cross a process boundary
  per request. Tolerable at heartbeat cadence, not yet measured in
  practice — the `direct` default protects ADR-0014's accepted
  performance envelope until we have numbers.
- Adds two more MCP servers to the operator's `claude mcp list`. That
  surface is small but real, and the project should not impose it on
  someone who is happy with the local stack.
- Two more upstream projects (`mcp-server-qdrant`, `mcp-redis`) join the
  dependency footprint. Their release cadence and breaking-change
  posture are now part of ours.

What was considered and rejected:

- *A single Mr. Robot-owned MCP server that proxies both backends.* Less
  code on disk but more code we'd own and have to keep in lockstep with
  upstream Qdrant / Redis MCP changes. Reusing the upstream servers
  keeps the maintenance surface in the hands of the projects that ship
  the backends.
- *MCP mode as a replacement for cloud mode rather than a parallel
  transport.* Rejected — direct clients are the lowest-friction path for
  someone who already has a Qdrant Cloud cluster wired the ADR-0014 way,
  and the two transports cost almost nothing to keep alongside each
  other behind the same adapter seam.
- *Routing the event-mode host's Qdrant through MCP too.* Out of scope
  for v1 — the host's Qdrant is *local* to the host, so the MCP-mode
  motivation (credentials, uniformity with cloud SaaS) doesn't apply.
  Revisit if a host ever wants to expose its vault to participants via
  MCP instead of the Qdrant wire protocol.

Like cloud mode and event mode, MCP mode is **opt-in and degrades
quietly**: with `MR_ROBOT_COOP_TRANSPORT=mcp` set but
`mcp-server-qdrant` not registered, the adapter logs once at startup
and falls back to direct Qdrant Cloud (if a URL/key are configured) or
to memory-only (if not). The orchestrator does not halt; `doctor` is
how the operator notices.

### The join key (event mode)

The host generates a join key on session start:

```
mr-robot coop host start --name "HTB Lame jam"
# → join key: KARP-V8K2-NEBU-72QC   (TTL 24h)
```

Properties of the key:

- **Short, dictation-friendly** — four chunks of four base32 characters,
  copy-paste or read-aloud friendly.
- **Shared secret** — possession of the key authorizes write *and* read
  against the host's Qdrant for the session. Not a long-lived credential.
- **Scoped** — tied to a specific event-name and the host's instance-id;
  cannot be silently retargeted at a different vault.
- **Time-bounded** — 24h TTL by default, extendable by the host while the
  session is alive.

Participants attach to the event:

```
mr-robot coop join KARP-V8K2-NEBU-72QC --host <host-url>
```

The participant's Mr. Robot now routes co-op writes to the host's Qdrant
(gated by the same scrubber and solved-only rule) and reads recollections
from the host's collection alongside (or instead of) the cloud
collection.

Discovery of the host's URL is intentionally out of scope: an event group
typically has an out-of-band channel and the host knows their own routable
address. Tunnel / STUN-style rendezvous is an open question below.

### HTB API as a sibling MCP server *(upcoming)*

The project prefaces HackTheBox, but knows nothing about HTB the platform —
there is no programmatic awareness of what's currently active, what's just
been released, who's working what, or which target an event's join key is
for. That gap is most acute in event mode: an event is fundamentally a
*thing happening on HTB right now*, and the orchestrator has no way to ask
HTB about it.

This ADR proposes a second MCP server alongside `mr-robot`, named
**`htb-api`**, that wraps the public HackTheBox v4 API. Read-only
capabilities (v1):

- list active boxes / challenges / labs the operator's account has access to;
- box metadata: difficulty, OS, points, release status;
- season / event metadata: which event is live, when it ends, official scope;
- the operator's own progress: own / root counts, current rank.

Why it's separate from `mr-robot`:

- Different auth surface (an HTB API token, not a local service).
- Different rate-limit profile (external, throttled).
- Independently useful — `htb-api` is valuable to an agent even when the
  orchestrator isn't running.

Why it surfaces here in ADR-0015:

- Event mode wants HTB context. A join key is more useful when the host's
  Mr. Robot can also tell participants *"this event is HTB Battlegrounds
  'XYZ', current target is box 'PQR', ends at 22:00 UTC."*
- The first concrete consumer of `htb-api` is the co-op's session
  bootstrapping; naming it here keeps the architecture diagram honest.

Promotion is via a separate ADR once the API surface is non-trivial. Until
then, `htb-api` is named here as an upcoming sibling so the `doctor`
command can plan to check it and the architecture story stays consistent.

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
| Co-op MCP — Qdrant | `claude mcp list` shows `mcp-server-qdrant` ✓ Connected, at user scope | co-op reads & shares when `MR_ROBOT_COOP_TRANSPORT ∈ {mcp, both}` |
| Co-op MCP — Redis | `claude mcp list` shows `mcp-redis` ✓ Connected, at user scope | recall cache when `MR_ROBOT_COOP_TRANSPORT ∈ {mcp, both}` |

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
- MCP mode adds two upstream MCP servers (`mcp-server-qdrant`, `mcp-redis`)
  to the project's effective dependency surface. Their release cadence
  and breaking-change posture become part of ours, and their auth model
  (credentials in Claude Code's MCP `env`) becomes the place co-op
  secrets live when that transport is selected.

## Open Questions

### Cloud mode

- Who hosts and pays for the Qdrant Cloud cluster, and what is the
  governance model when that owner moves on?
- Moderation: report-a-recollection, shadow-ban-a-handle, or trust the
  community filter? When does v1's no-moderation stance break?
- Poisoning resistance — does the brain need a "co-op recollections are
  evidence-grade only when N independent handles converge" rule?
- Identity hardening: do we eventually want signed writes (handle ↔ keypair)
  so handle squatting is detectable?

### Event mode

- Host availability — if the host goes offline mid-event, do participants
  fail closed (no co-op until host returns), fall back to the cloud (if
  also configured), or fall back to local memory only?
- Discovery — out-of-band today; is there a future role for a tiny
  "find this join key's host URL" rendezvous service, and would adding
  one undermine the event-mode trust story?
- Topology — can two hosts of two adjacent events share with each other,
  or is host topology strictly star? Federation invites multi-host
  consistency questions we may not want.
- Event end — does the host's Qdrant retain the event's data after closing,
  or is the corpus archived / purged? Defaults matter here.
- Network model — does event mode require the host to expose a public
  endpoint (forwarded port, tunnel, Tailscale-style mesh), and how does
  that interact with operators on locked-down corporate networks?

### MCP mode

- Per-call overhead — what does the MCP hop actually cost on cold and
  cached recall? The `direct` default stays the recommended path until
  the number is measured against ADR-0014's ≈ 17 ms / ≈ 0.1 ms baseline.
- Pre-computed-vector contract — `mcp-server-qdrant` is assumed to accept
  pre-computed vectors so the embedding model stays canonical in
  `server/memory.py`. Confirm against the upstream tool surface before
  promotion; if it embeds server-side with a different model, MCP mode
  would split the embedding pipeline and lose the "same vector space"
  property cloud mode relies on.
- Auth model for `mcp-redis` against Redis Cloud — token in MCP server
  `env`, or an ACL user-per-instance? Per-instance ACLs make
  shadow-banning a noisy writer tractable; a shared token does not.
- Fan-out semantics with `MR_ROBOT_COOP_TRANSPORT=both` — primary MCP
  with direct fallback is simple; "write to both and reconcile" is
  safer against transport-specific data loss but doubles the write
  cost. Default is fallback; reconcile-mode is deferred.
- Does MCP mode obviate the dedicated `MR_ROBOT_COOP_QDRANT_*` env vars
  long-term, or do both transports keep their own config so an operator
  can flip between them without re-wiring?

### `htb-api` sibling

- HTB Terms of Service — explicitly check that the `htb-api` server's
  usage profile (rate, endpoints, cached responses) is within HTB's API
  terms before publishing.
- Auth surface — single API token in env, or interactive login at first
  use? The single-token path is easier to automate but harder to rotate.
- Scope creep — `htb-api` is read-only in v1, but the temptation to add
  write endpoints (submit a flag, mark a box owned) will appear; resist
  until a separate ADR justifies it.

### Cross-cutting

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
- Future: a separate ADR for the `htb-api` sibling MCP server once its
  surface stabilises.
- External: Qdrant Cloud — https://cloud.qdrant.io
- External: `mcp-server-qdrant` — https://github.com/qdrant/mcp-server-qdrant
- External: Redis Cloud — https://redis.io/cloud/
- External: `mcp-redis` — https://github.com/redis/mcp-redis
- External: HackTheBox v4 API — https://app.hackthebox.com/api/v4
