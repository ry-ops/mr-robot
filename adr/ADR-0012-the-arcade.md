---
adr: 0012
title: The Arcade
component: arcade
class: Architecture Component
status: Accepted
date: 2026-05-20
---

# ADR-0012: The Arcade

## Status

Accepted — built and verified in v0.1 (`~/Mr. Robot/server/`).

## Context

Mr. Robot runs multiple Hat robots concurrently against a single HackTheBox
box (see ADR-0001 through ADR-0011). Concurrency only compresses time if the
robots' work *converges* — two robots running side by side without shared
state are just two separate engagements producing two reports to reconcile by
hand.

Three forces require a shared state layer:

- **Convergence.** One robot's confirmed attack surface must feed another's
  exploitation; duplicate findings must collapse.
- **Live orchestration.** Mr. Robot's reinforce / repurpose decisions need
  structured, real-time visibility into what every robot is doing and why it
  is stuck.
- **Live forensics.** The forensic writeup should accrete *during* the
  engagement, not be compiled afterward.

This ADR records the decision to build that layer. It is named **the arcade**,
after fsociety's headquarters — the shared space every member returns to.

## Decision

The arcade is a stateful component of the Mr. Robot MCP server: a shared
**findings store + task board**, scoped to one engagement, accessed by robots
only through MCP tools, and backed by SQLite.

### Data model

Five entities.

**Engagement** — one per box.
`id · box_name · box_ip · playbook · started_at · status · flags{user, root}`
`box_ip` is the scope allowlist — the single value every robot action is
checked against (the ethics axis from the Hat ADRs).

**Finding** — immutable, append-only. The atoms of progress.
`id · type · data · source_robot · source_hat · confidence · created_at · related_to[]`
- `type`: port | service | web_path | credential | cve | foothold |
  privesc_vector | flag
- `confidence`: confirmed | likely | speculative
- deduped on `(type, data)`

**Task** — a unit of work on the board.
`id · type · summary · status · depends_on · priority · hat · claimed_by · produces[] · produced[] · created_by`
- `status`: blocked → ready → in_progress → done, plus dead_end
- `depends_on`: a predicate over findings
- `created_by`: seed | rule:<id> | blocker | robot

**Robot** — a running Hat worker (a "robot").
`id · hat · current_task · status · heartbeat_at · blocker`
- `status`: working | blocked | idle | done

**Blocker** — the structured stuck-signal.
`need (human text) · resolved_by (a finding predicate)`

### Mechanics

1. **Findings unlock tasks.** A posted finding is matched against the active
   playbook's unlock rules; matching rules spawn tasks. Every `blocked` task's
   `depends_on` predicate is re-evaluated; satisfied tasks flip to `ready`.

2. **Blockers create demand.** A robot's `resolved_by` predicate is matched
   against the board. Match → the robot's task returns to `ready`. No match →
   the engine spawns or boosts the task template whose `produces` includes the
   needed finding type. A blocker is therefore a self-routing demand signal.

3. **The orchestrator loop.** On a heartbeat, Mr. Robot reads robot status and
   board state and, per robot: leaves it (progressing), reinforces it (hot
   task — gang up), or repurposes it (stuck, blocker unsatisfiable — assign the
   highest-priority `ready` task). Idle robots pull the next `ready` task.

"Assist vs. gang up" is emergent: assist = robots spread across many `ready`
tasks; gang up = many robots converged on one.

### Interface

Robots never touch storage directly. The MCP server exposes:

- `arcade_post_finding(type, data, confidence)`
- `arcade_list_tasks(status)` · `arcade_claim_task(id)`
- `arcade_report_blocker(task, need, resolved_by)`
- `arcade_complete_task(id, produced[])` · `arcade_mark_dead_end(id, reason)`
- `arcade_heartbeat(robot, status)`

The MCP server serializes every write — claims are atomic, so two robots
cannot take one task, and concurrent finding posts dedupe cleanly.

### Storage

Each engagement gets a workspace directory:

```
engagements/<box_name>/
  arcade.db      -- SQLite: engagement, findings, tasks, robots
  report.md      -- live forensic writeup, re-rendered on every change
  loot/          -- scan output, downloaded files, screenshots, evidence
```

Findings are immutable; the report is a *rendered view* of the database,
maintained by a Blue/Purple robot so the writeup is current at all times.

### Unlock rules

The finding→task rules are **not** code. They are declared in a playbook file
under `~/playbooks/` (default: `~/playbooks/htb-default.yaml`). Methodology is
tuned by editing data, and a per-box playbook can be selected on the
Engagement.

## Consequences

**Gains**

- Parallel robots converge instead of forking the engagement.
- The forensic report is finished when `root.txt` is — the "compile it later"
  problem is gone.
- Every finding carries its source Hat and timestamp: the evidence trail is
  free.
- HTB methodology is tunable without code changes (the playbook).
- Atomic, serialized writes remove all robot-vs-robot race conditions.

**Costs / tradeoffs**

- SQLite is effectively single-writer; acceptable because the MCP server
  already serializes writes, but it caps raw write throughput.
- Engagement lifecycle (create, archive, clean up workspaces) is new surface
  to build.
- The playbook becomes a maintained artifact — wrong rules silently misroute
  work.
- The orchestrator's *reinforcement policy* — the exact gang-up threshold — is
  deliberately out of scope here and deferred to the orchestrator ADR.

## Open Questions

- Heartbeat cadence — fixed interval, or event-driven on status change?
- One SQLite DB per engagement, or one shared DB with engagement-scoped rows?
- ~~Does the arcade retain anything across engagements (a cross-box memory),
  or is each engagement fully isolated?~~ **Resolved by
  [ADR-0014](ADR-0014-the-memory.md):** each engagement is fully isolated;
  cross-engagement state lives in a separate component, *the memory*, backed
  by aiana.

## Related

- [ADR index](README.md)
- Robots are runtime instances of the Hats — [ADR-0001](ADR-0001-white-hat.md)
  through [ADR-0011](ADR-0011-purple-team.md)
- Unlock rules: `~/playbooks/htb-default.yaml`
- The reinforcement policy that consumes the arcade — future orchestrator ADR
