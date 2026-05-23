---
adr: 0011
title: Purple Team
hat: Purple Team
color: purple
class: Team
status: Proposed
posture: Collaborative validation
authorization: Authorized scope shared by the Red Team and Blue Team contracts
date: 2026-05-20
---

# ADR-0011: Purple Team

## Status

Proposed. The Purple Team is a composition of Red Team (ADR-0009, now
Accepted) and Blue Team (ADR-0010, still Proposed). Until the Blue
defensive tool family lands, half of the loop has no robots to run. The
Hat becomes Accepted once Blue Team is Accepted — no additional runtime
work is needed beyond what each composed team requires.

## Context

The Purple Team is not a separate team but a way of working: Red and Blue
operating together in a tight loop — run an attack technique, check whether
Blue detected it, tune the detection, repeat — so every offensive action
directly improves defensive coverage.

## Decision

### Posture & authorization

A Purple Team engagement operates against the engagement scope's `box_ip`
allowlist, on a system the operator owns *and* controls the telemetry of —
i.e. the engagement requires both Red Team's offensive authorization *and*
Blue Team's defensive access to the target's logs and host state. In
practice this means own-VM, lab range, or HTB Pwnbox-style boxes that
expose their own logs to the operator.

This is a *composition*, not a new persona. The Team is the union of the
Red Team's offensive Hat mix and the Blue Team's defensive Hat mix, all
working the same arcade in a single engagement.

### Multi-Hat coordination model

The Purple loop — attack, observe, tune, repeat — maps onto orchestrator
policy (ADR-0013) without new mechanisms:

- **Hat mix.** Under a Purple Team playbook, the spawn policy draws from
  both offensive and defensive Hat sets. Both `team:red` and `team:blue`
  tags are applied; the orchestrator does not partition the board.
- **The loop is a task-graph shape, not a runtime mode.** Each
  offensive `foothold`/`privesc_vector`/`flag` task in the Purple
  playbook has a paired `detection_check` task (Blue's new task type
  from ADR-0010) with a `depends_on` that fires once the offensive task
  produces a finding. Blue's detection check inherits the technique
  metadata from the offensive task it was spawned alongside.
- **Reinforce.** When detection coverage of a hot technique is missing,
  Blue robots gang up on the gap; when offensive progress stalls, Red
  robots gang up. Same reinforcement policy, both sides.
- **Repurpose.** A Blue robot whose detection-check is unsatisfiable
  (no telemetry collected for the technique) becomes a
  `telemetry_gap` task — captured as a finding, not silently dropped.

### Tool envelope

Union of Red Team's and Blue Team's envelopes — full offensive plus full
defensive. Same gating story as both halves: per-Hat tool gating is
**not yet runtime-enforced** in `server/mr_robot.py`, so the envelope is a
contract on the composed personas until that gate exists. Purple Team is
strictly downstream of Blue Team's envelope; nothing about composition
adds new tool requirements.

### Rules of Engagement

- Both Red Team and Blue Team rules apply in full. The stricter rule
  wins on any conflict.
- The detection-gap matrix is the engagement's primary output, not the
  attack narrative or the hardening checklist (those are byproducts).
- Detection rules proposed by Blue are validated against the matched
  Red technique before being recorded — no untested detections in the
  output.
- Destructive Red actions still require operator confirmation, even
  when the point is to exercise Blue's response.

### Integration with arcade & playbook

A Purple Team playbook is a sibling of `htb-default.yaml` whose task
graph encodes the offensive/defensive pairings. It uses the full task
type set — Red's offensive types from ADR-0012 plus Blue's defensive
types added in ADR-0010 (`detection_rule`, `hardening_gap`,
`telemetry_gap`, `incident_artifact`). The forensic report renderer
adds a detection-gap matrix view: per-technique, the offensive finding,
the detection-check outcome, and any tuning action recorded as a
follow-up task.

The arcade itself does not need a "team" entity. Engagement.playbook
identifies the team flavour; orchestrator policy reads it.

### Interaction with the memory layer (ADR-0014)

Purple Team writes campaign-tier memory through the orchestrator: the
engagement summary, terminal offensive findings, and high-confidence
detections all flow in. Task-tier writes come from each composed Hat
individually, tagged with `team:purple` in addition to the Hat tag.

On the ADR-0014 open question of Team-level recall scoping, a Purple
Team engagement's orchestrator brain recalls prior Purple Team
engagements *plus* both prior Red and Blue team engagements *plus*
relevant individual-Hat work from both sides. Purple is the broadest
recall scope, by design: its judgment depends on knowing both what
attackers and defenders have done before. Robots at the task tier
recall against their own Hat, per ADR-0014's default; the team tag is
an orchestrator concern.

On per-Hat gating: every Hat the Purple Team composes is a production
Hat with the full `memory_*` surface (no reduced-subset Hats
participate).

## Consequences

This Hat composes the Red Team and Blue Team contracts rather than defining a
new capability set. It depends on both ADRs being settled first.

## Open Questions

- ~~Is the loop driven interactively, or run as a full batch campaign?~~
  Resolved: batch campaign — the loop is a task-graph shape in the
  playbook, executed by the orchestrator's normal heartbeat.
- ~~Where is the ATT&CK coverage matrix stored between runs?~~ Resolved:
  the arcade for the live matrix; the memory layer for cross-engagement
  coverage trends.
- Target shape — HTB boxes do not expose defender-side telemetry; what
  target classes are realistically in scope for a Purple Team
  engagement (own-VM, lab range, instrumented HTB)?
- Tuning action follow-through — when Blue proposes a detection rule
  that Red's next attempt evades, is that another loop iteration
  inside the same engagement, or a follow-up engagement?

## Related

- [ADR index](README.md)
- Composes [ADR-0009 Red Team](ADR-0009-red-team.md) and
  [ADR-0010 Blue Team](ADR-0010-blue-team.md)
