---
adr: 0008
title: Script Kiddie
hat: Script Kiddie
color: none
class: Individual Hat
status: Proposed
posture: Guarded automation
authorization: Maximum guardrails; high-risk operations hard-blocked
date: 2026-05-20
---

# ADR-0008: Script Kiddie

## Status

Proposed. The Hat's contract is built on guardrails the runtime does not yet
implement — a low-risk action allowlist, a mandatory preview/confirmation
prompt before destructive operations, and destructive-action throttling.
`server/scope.py` enforces target scope but does not classify actions by
risk. The Hat becomes Accepted once `server/mr_robot.py` gains a per-Hat
tool allowlist and a confirmation gate for the destructive-action set.

## Context

The Script Kiddie runs tools they don't understand — copy-pasting attacks with
no grasp of what they do or what damage they risk. It is the archetype Mr.
Robot exists to **counteract**, not imitate.

This ADR records that decision. The "Script Kiddie" Hat is a deliberately
constrained mode: it runs only safe, well-understood, automated checks with
maximum guardrails — and, critically, always explains what a command does
*before* running it. Comprehension is enforced, not optional.

## Decision

### Posture & authorization

A Script Kiddie robot operates against the `box_ip` scope like every other
Hat, but with the strictest tool envelope of any Hat — scope alone is not
the safety contract here. The Hat exists for unsupervised or low-experience
operator runs where the cost of a misclicked tool dwarfs the cost of a
slower engagement.

### Tool envelope

In-envelope: passive recon and read-only enumeration only — nmap default
scans, banner grabs, HTTP `GET`, directory listings against discovered web
paths, public CVE lookup. Out-of-envelope: anything that writes to the
target, any credential attack, any exploit module, any post-exploitation
tool, any cracking, any `POST`/`PUT`/`DELETE` web request, any tool that
fuzzes auth or login forms.

This envelope is a contract, **not yet runtime-enforced**. Today every robot
sees the full MCP tool surface via `server/mr_robot.py`. The runtime gate
this Hat requires is a per-Hat allowlist on the MCP tool dispatcher (read
from the Hat's frontmatter in `hats.py`) plus a destructive-action
classification on each tool — neither exists. Until they do, the envelope is
enforced only by the robot persona.

### Rules of Engagement

- Allowlist of low-risk passive actions is the entire envelope. New tools
  default to **denied**.
- Every command is previewed in plain English before execution and (when
  the gate exists) requires operator confirmation.
- Exploitation, credential attacks, destructive actions, and write
  operations are hard-blocked — refused even if scope-valid.
- Throttle: at most one active tool invocation at a time, with a hard cap
  on total invocations per engagement (set per playbook).
- A hard-block surfaces a suggestion to switch to Green Hat (ADR-0006) for
  guided learning, or White Hat (ADR-0001) for supervised offense.

### Integration with arcade & playbook

Script Kiddie robots produce `port`, `service`, and `web_path` findings
only. They never produce `credential`, `foothold`, `privesc_vector`, or
`flag` findings — those task types are not assigned to them by the
playbook. They are reinforcement-eligible on passive enumeration tasks but
never on exploitation tasks; the orchestrator's repurpose policy
(ADR-0013) treats them as ineligible for `foothold`/`privesc_vector` work
even when idle.

### Interaction with the memory layer (ADR-0014)

Script Kiddie gets a **reduced, read-only** `memory_*` surface:
`memory_recall_for_task` only. It does not write task outcomes. Rationale
matches Green Hat — the corpus exists to grow Mr. Robot's craft on
production work, and the Script Kiddie's narrow envelope produces little
that generalizes. Writing from this Hat would dilute recall quality for
the production Hats that share the store.

On the ADR-0014 open question of per-Hat gating, this is the explicit
reduced subset, alongside Green Hat and Gray Hat. Team-level recall scoping
is not applicable.

## Consequences

This Hat is the inverse of the real-world script kiddie: it makes
not-understanding-the-tool impossible to act on. It defines the strictest
guardrail tier; other Hats relax from this baseline.

## Open Questions

- The exact allowlist of low-risk actions — codify in the Hat frontmatter,
  a playbook-style file, or hard-code in `mr_robot.py`?
- How is "destructive" classified per tool — a static map maintained
  alongside the tool definitions, or a per-tool flag at registration time?
- Throttling cap — fixed per Hat, or playbook-tunable per engagement?
- ~~Should triggering a hard-block nudge the operator toward the Green
  Hat?~~ Resolved: yes — the refusal message names Green Hat and White Hat
  as alternatives.

## Related

- [ADR index](README.md)
- Contrasts with [ADR-0006 Green Hat](ADR-0006-green-hat.md)
