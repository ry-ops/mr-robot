---
adr: 0007
title: Purple Hat
hat: Purple Hat
color: purple
class: Individual Hat
status: Accepted
posture: Self-assessment of owned assets
authorization: Operator-attested ownership of every target
date: 2026-05-20
---

# ADR-0007: Purple Hat

## Status

Accepted. The Hat reduces to "operate within `box_ip` scope using the wired
offensive toolset"; the operator's act of starting an engagement against
their own asset *is* the ownership attestation. The self-observation half of
the loop is intent — described below as a robot-prompt contract, not a
runtime gate.

## Context

The Purple Hat practises on systems they own — testing their own machines and
networks to learn offense and defense together, on the safest possible target:
themselves.

Mr. Robot's Purple Hat is the solo self-assessment mode: the operator points it
at their own assets to find and fix their own weaknesses, running both the
attack and the observation side by side. It is the individual counterpart to
the organizational [Purple Team](ADR-0011-purple-team.md).

## Decision

### Posture & authorization

A Purple Hat robot operates against assets the operator owns. Authorization
collapses to the engagement scope: starting an engagement against a `box_ip`
is the operator's attestation of ownership. No separate "owned" registry —
the scope guard in `server/scope.py` is the only authorization gate, same as
every other Hat.

This Hat is the individual, solo counterpart of ADR-0011 Purple Team. The
team version requires Blue capabilities that are not yet built; this
individual version intentionally does not — the "observation" half is the
operator inspecting their own host while the offensive half runs, not a
parallel Blue robot.

### Tool envelope

Full offensive envelope — recon, web, exploitation, post-exploitation,
cracking — subject to scope. Same envelope as White Hat (ADR-0001); the
difference is intent (self-improvement), not capability.

Per-Hat tool gating is **not yet runtime-enforced**. Because Purple Hat's
envelope is the full offensive surface, the current undifferentiated MCP
tool exposure in `server/mr_robot.py` matches this contract by accident; no
gating is needed for this Hat to behave correctly.

### Rules of Engagement

- Targets are operator-owned; ownership is attested by the act of scoping
  the engagement.
- Every technique is paired with a self-observation note: what would have
  logged this, what would have detected this, what was missed.
- Findings are written as "weakness + concrete hardening step", not as an
  external pentest writeup.
- Destructive actions still require operator confirmation — owning the
  target is not a license to wipe it.

### Integration with arcade & playbook

A Purple Hat robot consumes the same playbook task types as White Hat
(`port`, `service`, `web_path`, `credential`, `cve`, `foothold`,
`privesc_vector`, `flag`). What changes is the report side: the live arcade
report (`engagements/<box>/report.md`) is rendered as a personal hardening
checklist — finding paired with the fix the operator should apply on their
own box — rather than a remediation report addressed to a client.

### Interaction with the memory layer (ADR-0014)

Purple Hat gets the **full** `memory_*` surface — recall and write. Its
task outcomes are high-signal: the operator's own boxes, repeated over time,
are exactly the corpus where "what worked on my stack last time" pays off.
Tagged with the Hat plus task type plus box fingerprint, same as the other
production Hats.

On the ADR-0014 open question of per-Hat gating, Purple Hat sits with the
production offensive Hats (White, Red, Black) — full surface. On Team-level
recall scoping, not applicable — Individual Hat.

## Consequences

This Hat is the safe on-ramp to Purple Team practice: same loop, single
operator, owned assets only.

## Open Questions

- ~~How is asset ownership attested and recorded?~~ Resolved: the engagement
  scope is the attestation; no separate registry.
- Should this Hat's hardening checklist render share a template with the
  Purple Team detection-gap matrix once that Hat lands?

## Related

- [ADR index](README.md)
- Individual counterpart of [ADR-0011 Purple Team](ADR-0011-purple-team.md)
