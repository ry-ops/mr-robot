---
adr: 0001
title: White Hat
hat: White Hat
color: white
class: Individual Hat
status: Accepted
posture: Authorized offensive
authorization: Explicit written scope required for every engagement
date: 2026-05-20
---

# ADR-0001: White Hat

## Status

Accepted — runtime enforces the authorization model this Hat depends on. The
engagement's `box_ip` allowlist is the single scope axis and is checked on
every active tool through `server/scope.py`. The tool envelope below is a
contract: it describes the inventory this Hat is entitled to, not a per-Hat
runtime gate (every robot today sees the same MCP surface). Destructive-action
confirmation is intent, not enforcement; it does not affect promotion because
HTB engagements are operator-driven and the operator is in the loop.

## Context

The White Hat is the ethical hacker: a security professional who uses offensive
techniques **only** against systems they are explicitly authorized to test, with
the goal of finding and reporting weaknesses so they can be fixed. This is the
default and primary operating mode of Mr. Robot.

In this mode the full Kali arsenal is available, but every action is bound to a
documented engagement scope and rules of engagement. Intent is constructive:
discover, evidence, report, remediate.

## Decision

The White Hat is the canonical Hat. It defines the authorization model the
other offensive Hats reference; deviations are stated relative to it.

### Posture & authorization

Authorization is per-engagement and concrete: an Engagement row (ADR-0012)
carries `box_ip`, which is the scope allowlist. `server/scope.py` checks every
target against that allowlist before any active tool runs; out-of-scope
targets raise `ScopeError` and the tool is refused. For HTB this is sufficient
— one box, one IP, one ROE — and matches the spirit of a written engagement
scope. There is no second authorization axis above `box_ip` today.

### Tool envelope

The White Hat is entitled to the full offensive inventory: recon, web
testing, exploitation, post-exploitation, credential testing, and cracking.
This is the widest envelope of any Hat. In runtime terms, "entitled to the
full inventory" reduces to "operates within `box_ip` using whatever MCP tools
are wired in" — which is exactly what the system already enforces.

Per-Hat tool gating is **not yet runtime-enforced**: `server/hats.py` is a
pure registry and every `AgentRobot` is handed the same MCP server (the
`mr_robot` server in `server/robots.py`). The envelope is a contract intended
to wrap the existing MCP surface; gating it would require `mr_robot.py` to
filter `allowed_tools` by the robot's Hat at agent construction time. For the
White Hat that filter is a no-op, so promotion is not blocked.

### Rules of Engagement

1. No action outside `box_ip`. Enforced.
2. Destructive or high-impact actions (filesystem writes outside loot,
   service kill, account/credential modification, anything that changes box
   state in a way the next operator would notice) require an explicit
   operator confirmation step. Intent only — not yet enforced; flagged for the
   robot prompt and the operator UI.
3. Every active tool invocation, finding, and task transition is recorded in
   the arcade (`arcade.db`) — the evidence trail is a byproduct of normal
   operation, not a separate logging path.
4. Credentials harvested in-engagement stay in-engagement (`loot/`); they are
   not promoted into the memory layer.

### Integration with arcade & playbook

The White Hat produces the full set of arcade finding types: `port`,
`service`, `web_path`, `credential`, `cve`, `foothold`, `privesc_vector`,
`flag`. It accepts every task template in `~/playbooks/htb-default.yaml` —
there is no template the White Hat is forbidden from claiming. In practice
the orchestrator will route most exploitation and post-ex tasks here.

### Interaction with the memory layer (ADR-0014)

The White Hat gets the **full** `memory_*` task-tier surface:
`memory_recall_for_task` on task pickup and `memory_record_task_outcome` on
complete / dead-end. Past White Hat work on similar boxes is the highest-value
recollection for this Hat, and there is no posture reason to constrain its
writes. Engagement-end summaries are still written by the orchestrator, not
by the White Hat itself.

This is the per-Hat answer to ADR-0014's open question on the `memory_*`
surface: the White Hat is the unrestricted baseline. Other Hats narrow from
here.

## Consequences

This Hat defines the canonical authorization and scope model that other Hats
reference. The engagement-scope format and the "destructive action" list are
shared dependencies and must be designed first.

## Open Questions

- Which concrete actions count as "destructive" and trigger the confirmation
  step? (Per-Hat list, or one shared list referenced by every offensive Hat?)
- Should the destructive-action confirmation be a tool-wrapper concern in
  `mr_robot.py`, an orchestrator-loop concern, or a UI concern?
- Per-Hat tool gating — where does the filter live (`mr_robot.py` at agent
  construction, or a Hat-keyed allowlist in `server/hats.py`)?

## Related

- [ADR index](README.md)
- Bounds [ADR-0002 Black Hat](ADR-0002-black-hat.md)
