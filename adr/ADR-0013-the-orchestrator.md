---
adr: 0013
title: The Orchestrator
component: orchestrator
class: Architecture Component
status: Accepted
date: 2026-05-20
---

# ADR-0013: The Orchestrator

## Status

Accepted — built and verified in v0.1 (`~/Mr. Robot/server/orchestrator.py`).
Depends on ADR-0012 (the arcade).

## Context

Layer 1 is built: the arcade (ADR-0012) is a shared task board, and the
`mr-robot` MCP server exposes it — but nothing *drives* it. Findings have to be
posted by hand; the board does not move on its own.

Layer 2 is the part that does: **the orchestrator — "Mr. Robot" itself.** It is
the component that runs an engagement end to end — spawns Hat robots, works the
board, watches them, and adapts.

This is the project's standout. The tools are commodity; every Kali box has
them. The differentiator is *judgment*: read a box, decide the campaign,
reinforce what is paying off, and pull robots off what is stuck. The design
discussion settled several constraints this ADR must honour:

- Robots run concurrently; a Hat is bound at robot creation, for life.
- The orchestrator chooses direction *at runtime* (assist vs. gang up) — so
  workers must be spawnable, killable, and re-taskable on the fly. That rules
  out single-session sub-agents.
- Robots report **structured blockers**, not freeform status.
- The host is 4 vCPU / 7.8 GB — the robot pool is bounded.

## Decision

### Mr. Robot is a standalone program

The orchestrator does not run *inside* a Claude session; it *drives* them. It
is a Python program that:

- reads and writes the arcade directly (`import arcade` — no MCP round-trip for
  its own control loop),
- spawns and supervises **robots**,
- runs a heartbeat-driven control loop until the engagement terminates.

### What a robot is

A robot is a Claude agent created via the **Claude Agent SDK**, configured with:

- **Persona** — one Hat ADR (ADR-0001..0011) as its system contract, supplying
  the intent / ethics / behavior axes.
- **Tools** — the `mr-robot` MCP server (arcade + recon) plus the Kali toolset.
- **Assignment** — one task drawn from the arcade.

A robot is **bound to its Hat for life**. It claims its task, works it, posts
findings, reports blockers, and completes or dead-ends it. It then **persists**
and is **re-tasked** onto another task *of its Hat*. If the board holds no task
for a robot's Hat, the orchestrator retires that robot and spawns the Hat the
board now needs.

### The control loop

Each heartbeat, Mr. Robot:

1. Reads the board and robot statuses from the arcade.
2. Per robot, decides: **leave** (progressing), **reinforce** (its task is hot
   — gang up), or **repurpose** (stuck, blocker unsatisfiable).
3. Assigns idle robots the highest-priority `ready` task matching their Hat.
4. Spawns or retires robots to stay within the pool budget.
5. Checks terminal conditions: both flags captured, no actionable work left, or
   budget exhausted.

"Assist vs. gang up" is never a mode that is selected — it is emergent. Assist
is robots spread across many `ready` tasks; gang up is many robots converged on
one. Mr. Robot only ever keeps robots on high-value actionable work.

### The brain is hybrid

- **Mechanical scheduling** — assigning `ready` tasks, heartbeats, budget
  arithmetic — is plain code: deterministic, fast, predictable.
- **Direction judgment** — *is this task worth ganging? is a robot genuinely
  stuck or just slow? what is the campaign?* — is a **reasoning step**: Mr.
  Robot consults an LLM with the board state and receives directives.

This split is deliberate. The plumbing must be reliable; the judgment is the
product. Pure heuristics would make the orchestrator unremarkable.

### Reinforcement policy (first pass)

Reinforce a task — assign extra robots — when any of:

- its priority is top-tier **and** it has been `in_progress` past a time
  threshold without producing a finding, or
- multiple blockers' `resolved_by` predicates point at the finding type it
  `produces` (demand pile-up), or
- its robot reports partial progress ("close").

Cap robots-per-task to bound diminishing returns (default 3). When nothing
qualifies for reinforcement, robots spread.

### Repurpose policy

Pull a robot off its task when its blocker's `resolved_by` predicate cannot be
satisfied by any current or in-flight task, and reassign it to the
highest-priority actionable task for its Hat.

### Robot budget

A fixed pool sized to the host (default 4, env-tunable). Reinforcement and
spreading draw from the same pool; the orchestrator never exceeds it.

### Triage — the engagement opening

Every engagement starts the same way: one recon robot on the seed scan. Once
recon findings land and the board populates, the first real direction decision
fires — spread across the discovered services, or, if recon shows one dominant
service, gang it from the start.

### Safety

Every robot inherits the scope guard through the `mr-robot` MCP server, and the
orchestrator itself refuses to spawn work against an out-of-scope target. The
Hat ethics axis is enforced per robot, by its persona.

## Consequences

**Gains**

- Real autonomy — the arcade no longer needs a human to post findings.
- Assist vs. gang up becomes adaptive and emergent, not a manual choice.
- The standout — Mr. Robot's judgment — has a concrete home.

**Costs / tradeoffs**

- New dependency: the Claude Agent SDK, plus child-process supervision
  (crashes, restarts, timeouts).
- Cost — every robot is a Claude agent burning tokens; a full pool is a real
  spend, and the LLM brain adds its own calls and latency to every loop.
- The reinforcement thresholds are guesses until real boxes tune them.

## Open Questions

- Heartbeat cadence, and whether the LLM brain runs every tick or only on
  board state-change.
- How a robot surfaces "I'm close" in a structured way — extend the blocker /
  heartbeat schema?
- Token-budget governance — a hard cost ceiling per engagement?
- Build order: a heuristic-only brain first, with the LLM step added behind a
  seam, or the LLM brain from the start?

## Related

- Consumes [ADR-0012 The Arcade](ADR-0012-the-arcade.md)
- Robots instantiate the Hats — [ADR-0001](ADR-0001-white-hat.md) through
  [ADR-0011](ADR-0011-purple-team.md)
- Unlock rules: `~/playbooks/htb-default.yaml`
