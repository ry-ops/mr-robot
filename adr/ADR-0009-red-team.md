---
adr: 0009
title: Red Team
hat: Red Team
color: red
class: Team
status: Accepted
posture: Objective-based offense
authorization: Authorized organization-wide engagement scope
date: 2026-05-20
---

# ADR-0009: Red Team

## Status

Accepted. A Red Team engagement reduces to "multiple offensive Hats sharing
one scope, coordinated by the orchestrator's reinforce/repurpose loop." The
arcade (ADR-0012) and the orchestrator (ADR-0013) already deliver multi-Hat
coordination, shared findings, and emergent gang-up on hot tasks. The
"objective" is the `flag` task type at the top of the playbook's priority
order — already a first-class type. Stealth tuning and the ATT&CK-mapped
report are intent layered onto a working substrate, not new runtime
behavior.

## Context

The Red Team emulates a real adversary end-to-end against an organization:
objective-driven, multi-phase campaigns — initial access, persistence,
escalation, lateral movement, and reaching defined "crown jewel" objectives —
testing the people, process, and technology of the defenders together.

Where the White Hat finds and lists vulnerabilities, the Red Team runs a
campaign toward an objective.

## Decision

### Posture & authorization

A Red Team engagement operates against the engagement scope's `box_ip`
allowlist — the same gate every other Hat uses. "Organization-wide scope"
on a HackTheBox engagement collapses to one box per engagement; the broader
form is future work for a multi-host engagement model.

The Team is not a separate persona — it is a *composition* of offensive
individual Hats (White, Black, Red, Purple — and Gray under operator
discretion) all working the same arcade. There is no Red Team robot. The
orchestrator spawns a mix of individual offensive Hats whose collective
behavior is the Red Team.

### Multi-Hat coordination model

The Team contract is expressed entirely in orchestrator policy
(ADR-0013), not in a new runtime layer:

- **Hat mix.** When the playbook selected is a Red Team playbook, the
  orchestrator's spawn policy draws from the offensive Hat set only. No
  Green, no Script Kiddie, no Blue.
- **Reinforce.** The `flag` task (or the named objective) sits at top
  priority. The orchestrator's existing reinforce policy — gang up on
  hot, high-priority tasks — naturally converges robots onto the
  objective as the kill chain progresses.
- **Repurpose.** When a foothold robot's blocker is unsatisfiable, the
  orchestrator pulls it onto privesc or lateral work — already the
  existing repurpose semantic.
- **Phasing.** Phases (access → escalation → objective) are an emergent
  property of the playbook's task graph, not a state machine. The `flag`
  task's `depends_on` graph encodes the kill chain.

### Tool envelope

Full offensive envelope across the composed Hats: recon, web, exploitation,
post-exploitation, credential attacks, cracking, lateral-movement tooling.
Stealth tuning (timing, opsec-aware tool selection) is an intent on the
robot personas, not a runtime gate. The recon wrapper is built; web and
post-exploitation wrappers are not, so the Team currently runs degraded
relative to the full contract.

Per-Hat tool gating is **not yet runtime-enforced** — each composed Hat's
envelope contract therefore relies on the persona. When `mr_robot.py`
grows per-Hat tool allowlists, the Red Team inherits the union of its
composed Hats' allowlists automatically.

### Rules of Engagement

- All work is bound by the engagement scope; no lateral movement that
  resolves to an out-of-scope address.
- Destructive actions require operator confirmation.
- The named objective is encoded as a `flag` task with the highest
  priority on the board.
- Stealth is intent on the robot persona, not a runtime enforcement —
  honour the persona's opsec hints, but the orchestrator will still
  reinforce a hot task even if reinforcement breaks stealth (operator
  tunes this via the playbook's reinforcement caps).
- The forensic report doubles as the attack narrative — no second
  report-writing pass.

### Integration with arcade & playbook

The Team consumes the full task type set (`port`, `service`, `web_path`,
`credential`, `cve`, `foothold`, `privesc_vector`, `flag`). The Red Team
playbook is a sibling of `htb-default.yaml` — same engine, different
priority weights and task graph reflecting the kill chain. The team's
robots coordinate through the arcade exactly as ADR-0012 describes:
findings unlock tasks, blockers create demand, the orchestrator's
heartbeat reinforces or repurposes. No team-private state.

ATT&CK mapping is metadata on the playbook's task templates — each task
type carries a `technique_id`, and the forensic report renderer joins
findings to techniques on the way out. This is a renderer change, not a
new arcade entity.

### Interaction with the memory layer (ADR-0014)

The Red Team writes campaign-tier memory through the orchestrator
(engagement summary, terminal findings — already ADR-0014's design). Each
composed Hat writes its own task-tier outcomes individually, tagged with
its own Hat plus the box fingerprint plus a `team:red` tag added by the
orchestrator when the engagement is a Red Team engagement.

On the ADR-0014 open question of Team-level recall scoping: a Red Team
engagement's orchestrator brain recalls **both** prior Red Team
engagements *and* relevant individual-Hat work tagged with offensive Hats
(White, Black, Red, Purple). The `team:red` tag is an additional axis,
not a partition — past offensive craft generalizes across team vs. solo
postures. Robots at the task tier recall against their *own* Hat as
ADR-0014's default already specifies; the team tag is an orchestrator
concern.

## Consequences

This Hat needs persistent, multi-step campaign state — a heavier execution
model than the single-action individual Hats.

## Open Questions

- ~~How is campaign state persisted between steps and sessions?~~ Resolved:
  the arcade is campaign state; phases are emergent from the playbook task
  graph.
- ~~How are objectives ("crown jewels") defined in the scope file?~~
  Resolved: as a top-priority `flag` task in the Red Team playbook, not a
  scope-file concern.
- Multi-host engagements — the current `box_ip` scope is single-target;
  a Red Team contract against a real organization needs a CIDR or
  host-list scope. Out of scope for v1; revisit when multi-host
  engagements arrive.
- ATT&CK technique metadata — keep it on the playbook task templates, or
  introduce a separate mapping artifact?
- Stealth-vs-reinforcement tension — should the orchestrator's
  reinforcement cap drop when a Red Team playbook is active, to honour
  opsec at the cost of speed?

## Related

- [ADR index](README.md)
- Pairs with [ADR-0010 Blue Team](ADR-0010-blue-team.md) via
  [ADR-0011 Purple Team](ADR-0011-purple-team.md)
