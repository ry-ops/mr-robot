---
date: 2026-05-23
tags: [journey, memory, adr-0014, hats]
related-adrs: [ADR-0014, ADR-0001, ADR-0002, ADR-0005, ADR-0007, ADR-0009]
---

# 2026-05-23 — Memory end-to-end

Two threads in one day: **(1)** close out the open Hat ADRs and **(2)** finish
the memory layer (ADR-0014) all the way through live-service verification.

## TL;DR

- Hat ADRs 0001–0011 finalized. Five flipped to **Accepted** (White, Black,
  Blue, Purple, Red Team) — the ones whose contract reduces to "operate
  within `box_ip` using the wired toolset." Six stayed **Proposed** with a
  named promotion criterion (Gray, Red, Green, Script Kiddie, Blue Team,
  Purple Team).
- Memory layer wired: Qdrant (semantic, `all-MiniLM-L6-v2`, 384-d, cosine)
  alongside FTS5 with reciprocal-rank-fusion at k=60, Redis as a recall
  cache with generation-counter invalidation. Adapter surface unchanged.
- Brought up Redis (user-mode daemon, no sudo) and Qdrant (Docker
  container `mr-robot-qdrant`, image `qdrant/qdrant:1.18.1`).
- One bug found at verification: `QdrantClient.search()` is gone in
  current qdrant-client; replaced with `query_points(...).points`.
- ADR-0014 → **Accepted**. Cold recall ~17 ms, cached ~0.1 ms — ~140× —
  which actually justifies the cache rather than just hand-waving about
  read amplification.

## What happened, in order

### Pass 1 — three agents in parallel

- **Agent A** finalized ADRs 0001–0005.
- **Agent B** finalized ADRs 0006–0011.
- **Agent C** wrote the Qdrant + Redis integration into `server/memory.py`
  and amended ADR-0014.

The two ADR agents touched disjoint files; the memory agent touched
`server/memory.py` + `adr/ADR-0014` + `adr/README.md`. Zero conflicts.

### Pass 2 — bring up the services

- Redis: started without sudo as a user daemon —
  `redis-server --daemonize yes --port 6379 --bind 127.0.0.1 --dir ~/redis-data ...`.
  PID file at `~/redis-data/redis.pid`.
- Qdrant: ran via Docker after one `!`-prefix sudo from the operator —
  `sudo docker run -d --name mr-robot-qdrant -p 6333:6333 -v /home/ryan/qdrant_storage:/qdrant/storage qdrant/qdrant`.
- Storage paths: `~/qdrant_storage` (bind mount) and `~/.aiana/conversations.db`
  (aiana's default).

### Pass 3 — verify

`/tmp/mr_robot_memory_e2e.py` (deleted after cleanup) ran the full
record/recall/cache-invalidate cycle. First run exposed the qdrant-client
API drift; one-line fix; second run all green.

## Decisions worth remembering

### Hat status promotion rule

Accept iff the Hat's contract reduces to "operate within `box_ip` using
the wired toolset" — i.e., what `server/scope.py` enforces universally
already covers it. Stay Proposed if the contract needs unbuilt runtime
behavior (per-Hat tool gating, lab-mode flag, destructive-action
throttling, defensive tooling). Each Proposed Hat's Status section names
its promotion criterion.

### Teams are compositions, not new personas

ADR-0009 Red Team flips to Accepted because a team engagement is just
"multiple offensive Hats sharing one scope, coordinated by the
orchestrator's reinforce/repurpose loop." The arcade + orchestrator
already do multi-Hat coordination; the team is identified by
`engagement.playbook` + a `team:<color>` memory tag. No new robot class
needed.

### Per-Hat memory surface

ADR-0014's open question on whether all Hats get the full `memory_*`
surface was answered per-Hat:

- **Full surface** for unrestricted offensive Hats and Purple Hat.
- **Read-only** for Gray Hat and Script Kiddie (no
  `memory_record_task_outcome`) — keeps recall quality high by not
  diluting writes with low-confidence work.
- **Separate intel namespace** for Red Hat — reads the offensive
  corpus, writes to an intel namespace so analyst output doesn't
  pollute task recall.

### Three backends, three independent degradation paths

Each of aiana / Qdrant / Redis is feature-detected at import and at
init, and degrades to no-op without halting the adapter. The init log
lines are intentional — when a service is missing the operator should
see *why* the layer is running in reduced mode.

### Cache invalidation by generation counter

`mrrobot:memory:gen` is `INCR`'d on every write. Cache keys are
`sha256(gen|query|k|kind_filter)`, so a bumped gen invalidates the
entire cache namespace without an `SCAN`. Coarse but correct; fine at
heartbeat cadence, revisit if write rate climbs.

## The bug

`server/memory.py:_qdrant_search` originally called:

```python
self._qdrant.search(collection_name=..., query_vector=vec, ...)
```

`QdrantClient.search` was removed in current `qdrant-client` in favor of
the unified-query API. Fix:

```python
self._qdrant.query_points(collection_name=..., query=vec, ...).points
```

`.points` because `query_points` returns a `QueryResponse` wrapper, not
a bare list. Cache + writes weren't affected — only the semantic read
leg fell back to FTS5-only, which is the documented degraded mode.

## Reproduce later

```
# Services
redis-server --daemonize yes --port 6379 --bind 127.0.0.1 \
  --dir ~/redis-data --logfile ~/redis-data/redis.log \
  --pidfile ~/redis-data/redis.pid --save "" --appendonly no

sudo docker run -d --name mr-robot-qdrant -p 6333:6333 \
  -v /home/ryan/qdrant_storage:/qdrant/storage qdrant/qdrant

# Smoke
python3 -c "import sys; sys.path.insert(0, '/home/ryan/Mr. Robot/server'); \
            from memory import Memory; m = Memory(); \
            print(m.available, m._qdrant is not None, m._redis is not None)"
```

To stop:

```
redis-cli shutdown
sudo docker stop mr-robot-qdrant
```

## Open threads

- Per-Hat tool gating in `mr_robot.py` — the forcing function for the
  six Proposed Hats. Picking this up promotes Gray, Script Kiddie, and
  unblocks Green (which also needs a lab-mode attestation on the
  engagement).
- Defensive tooling for Blue Team / Red Hat / Purple Team — `tshark`,
  `volatility`, `sigma`, `lynis`, `trivy` wrappers and new arcade task
  types (`detection_rule`, `hardening_gap`, `telemetry_gap`,
  `incident_artifact`).
- Web / exploitation wrappers for the offensive Hats — the existing
  recon-only robot toolset is the bottleneck on real engagement runs.
- ADR-0014 *open question still live*: where do the engagement-summary
  and task-outcome prompts live — orchestrator/robot code, or
  playbook-style files alongside `htb-default.yaml`?

## Files touched

- `adr/ADR-0001` through `adr/ADR-0011` — finalized Decision sections,
  per-Hat Status updates.
- `adr/ADR-0014-the-memory.md` — Redis added, Qdrant integration
  detailed, status flipped to Accepted.
- `adr/README.md`, `README.md` — status tables.
- `server/memory.py` — Qdrant + Redis behind the existing adapter; the
  `_qdrant_search` fix.
