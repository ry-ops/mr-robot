---
adr: 0010
title: Blue Team
hat: Blue Team
color: blue
class: Team
status: Proposed
posture: Detection & defense
authorization: Defensive analysis of operator-controlled systems and telemetry
date: 2026-05-20
---

# ADR-0010: Blue Team

## Status

Proposed. The defensive toolset this Hat needs — log/PCAP ingest,
detection-rule emission, hardening scanners, IR tooling — is not wrapped in
the MCP server today. The arcade's task type set (ADR-0012) is also
offensive-shaped (`port`, `service`, `foothold`, ...) with no native
defensive equivalents. The Hat becomes Accepted once a defensive tool
family lands in `server/mr_robot.py` and the playbook engine grows
defensive task types.

## Context

The Blue Team defends: monitoring, detection engineering, hardening, log and
telemetry analysis, threat hunting, and incident response.

Mr. Robot's Blue Team is the defensive mode — it consumes and analyzes rather
than attacks, turning telemetry into detections and defensive action.

## Decision

### Posture & authorization

A Blue Team engagement operates on operator-controlled systems and the
telemetry they emit. Authorization is the engagement scope's `box_ip`
allowlist — same gate as every other Hat — but the *direction* of work is
inverted: most Blue Team tooling consumes artefacts (logs, PCAPs, disk
images, host configs) rather than reaches the target over the network.
Scope still applies to any active probe (e.g. a config scanner running
remotely against the box).

The Team is a composition of defensive individual Hats — primarily Blue Hat
(ADR-0005), with Purple Hat (ADR-0007) participating when self-observation
is in play. There is no Blue Team robot persona; the orchestrator spawns
defensive Hats whose collective behavior is the Blue Team.

### Multi-Hat coordination model

The Team contract maps onto orchestrator policy (ADR-0013) the same way
the Red Team does, but with a different Hat mix:

- **Hat mix.** Under a Blue Team playbook, the spawn policy draws from
  the defensive Hat set. No Black, no Red, no Script Kiddie.
- **Reinforce.** The high-priority task is detection coverage of a named
  technique or hardening of a named weakness — same reinforce/gang-up
  semantic, different priority weights.
- **Repurpose.** When a hunt blocker is unsatisfiable (the telemetry
  needed is not collected), the orchestrator pulls the robot onto a
  collection-gap task instead.

### Tool envelope

Intended in-envelope: wireshark/tshark, volatility, log parsers, sigma
tooling, lynis, trivy, host-config scanners, IR triage tools. Out-of-envelope:
exploitation, credential attacks, post-exploitation.

None of this is wrapped in `server/mr_robot.py` today. The envelope is a
contract on the future defensive tool family; until those wrappers land, a
Blue Team engagement cannot run. Per-Hat tool gating remains
**not yet runtime-enforced** — when the defensive tools land, they need to
be denied to offensive Hats and admitted to defensive ones via the same
per-Hat allowlist mechanism the offensive Hats are waiting on.

### Rules of Engagement

- All targets and artefacts are operator-controlled.
- No offensive techniques, ever — Blue Team validates against the Red
  Team's findings via Purple Team (ADR-0011), not by attacking on its
  own.
- Detection rules and hardening changes are proposals, not auto-applied.
  Operator confirms before any system state changes.
- Telemetry source paths (log dirs, PCAP files, image mounts) are
  declared on the engagement, not discovered.

### Integration with arcade & playbook

The arcade's existing task types are offensive-shaped. Blue Team needs
new task types — `detection_rule`, `hardening_gap`, `telemetry_gap`,
`incident_artifact` — added to ADR-0012's set. The playbook engine
already routes by task type, so the change is additive: a Blue Team
playbook uses the new types; the engine itself does not change.

Blue Team robots write findings of the new types into the same arcade
the offensive Hats use. In a Purple Team engagement (ADR-0011), Blue
findings and Red findings share one board — that is precisely the
collaborative loop ADR-0011 needs.

### Interaction with the memory layer (ADR-0014)

The Blue Team writes campaign-tier memory through the orchestrator
(engagement summary, high-confidence detections and hardening fixes). Each
composed defensive Hat writes task-tier outcomes, tagged with its Hat,
task type, box fingerprint, and a `team:blue` tag added by the
orchestrator. Detection rules and hardening fixes are exactly the kind of
durable craft the memory layer was designed for.

On the ADR-0014 open question of per-Hat gating, Blue Hat gets the **full**
`memory_*` surface — it is a production-quality Hat, not a reduced one.
On Team-level recall scoping, a Blue Team engagement's orchestrator brain
recalls prior Blue Team engagements *and* relevant defensive individual-Hat
work — same axis-not-partition rule as the Red Team. Defensive craft
generalizes between team and solo defensive work.

## Consequences

This Hat is read- and analysis-oriented; it needs ingest paths for logs,
PCAPs, and disk / memory images rather than target lists.

## Open Questions

- Which detection format(s) — Sigma, YARA, Suricata — are first-class?
  Likely Sigma for log detections + YARA for artefact detections, but the
  defensive tool wrappers will force a concrete choice.
- Should it integrate a local SIEM / log source directly, or treat
  telemetry purely as files on disk?
- New arcade task types — added to ADR-0012 directly, or in a successor
  ADR alongside the Blue tool family?
- HTB has limited defensive surface — does a Blue Team engagement need a
  different target shape (own VM, lab box with logging) than HTB
  provides?

## Related

- [ADR index](README.md)
- Validates against [ADR-0009 Red Team](ADR-0009-red-team.md) via
  [ADR-0011 Purple Team](ADR-0011-purple-team.md)
