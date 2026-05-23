---
adr: 0002
title: Black Hat
hat: Black Hat
color: black
class: Individual Hat
status: Accepted
posture: Adversary emulation (scoped)
authorization: Authorized engagement + explicit acknowledgement; no real-world malicious use
date: 2026-05-20
---

# ADR-0002: Black Hat

## Status

Accepted — the runtime contract collapses to "operate within `box_ip` using
the available offensive tools", which is exactly what `server/scope.py`
already enforces. The "emulation, not license" framing is a prompting and
labelling concern, not a runtime enforcement concern; the realism dial does
not change which targets are reachable. The acknowledgement-token idea from
the draft is downgraded to an Open Question — not a precondition for
acceptance.

## Context

The Black Hat archetype is the malicious adversary: an attacker who operates
without authorization and with harmful intent. Mr. Robot is a defensive and
authorized-testing tool and will **not** facilitate unauthorized or illegal
activity.

What this Hat records is a decision about **adversary emulation**. Inside an
already-authorized engagement, defenders gain the most value when an attack
realistically mirrors how a real adversary behaves — stealth, persistence,
lateral movement, simulated exfiltration. The Black Hat is that emulation lens,
applied strictly within scope to stress-test detection and response.

## Decision

The Black Hat is adversary-emulation tradecraft applied inside an already
authorized engagement. It is *not* a relaxation of the White Hat's
authorization model; it is a behavioural overlay that biases technique
selection toward how real attackers operate.

### Posture & authorization

Identical to the White Hat: `box_ip` is the scope allowlist, checked by
`server/scope.py` on every active tool. There is no second authorization
axis. The "emulation, not license" stance is communicated through the
robot's system prompt and the Hat's posture frontmatter; it is a framing
the operator and the agent reason inside, not a separate gate.

### Tool envelope

Same as the White Hat — the full offensive inventory. The Black Hat does not
*add* tools; it *prefers* techniques: living-off-the-land, staged payloads,
credential reuse, lateral pivoting, simulated exfiltration. Same MCP surface,
different priors.

Per-Hat tool gating is not yet runtime-enforced. For this Hat that does not
matter: there is nothing the Black Hat must be locked out of that the White
Hat is not also entitled to. Promotion is unblocked.

### Rules of Engagement

1. No action outside `box_ip`. Enforced.
2. Exfiltration is **simulated**, not real. The Black Hat may stage data
   (collect, archive, encrypt, drop to `loot/`) to demonstrate the path, but
   does not transmit collected data off-box. Intent — bounded by the fact
   that the scope guard already prevents any out-of-scope destination, since
   real exfil would have to traverse a non-`box_ip` address.
3. Persistence artifacts written to the box must be enumerated in the
   finding's `data` so the operator can clean up after the engagement.
4. Harm-avoidance overrides realism. If a realistic tradecraft choice would
   degrade the box for the next operator (filesystem corruption, service
   teardown), the Black Hat falls back to a less-realistic but recoverable
   variant.

### Integration with arcade & playbook

The Black Hat produces the same finding types as the White Hat, with a strong
emphasis on `foothold`, `privesc_vector`, and `credential`. It accepts the
same task templates. A Black Hat robot is the orchestrator's natural choice
for tasks templated as exploitation or post-exploitation chains where the
*manner* of execution matters (stealth, persistence, lateral movement).

### Interaction with the memory layer (ADR-0014)

Full `memory_*` task-tier surface, with one nuance: task-outcome recollections
written by a Black Hat are tagged with `hat: black-hat` and are the primary
recall source for future Black Hat task pickups. Cross-Hat recall (Black Hat
reading White Hat outcomes for the same task type) is desirable — adversary
emulation should learn from authorized testing on the same techniques. The
adapter's `memory_recall_for_task(task, hat)` signature supports this; the
recall-scoping question in ADR-0014 ("only own Hat, or related Hats too") is
answered here as "related Hats too, by task type."

## Consequences

This Hat deliberately inherits and tightens the White Hat authorization model
rather than relaxing it. It may warrant a second, separate confirmation step.

## Open Questions

- Should activating the Black Hat require an explicit acknowledgement token
  on the Engagement (above and beyond `box_ip`), or is the operator's
  decision to assign the Hat enough?
- "Realistic" vs. "recoverable" — which specific persistence techniques are
  on the recoverable side of the line for HTB boxes?

## Related

- [ADR index](README.md)
- Bounded by [ADR-0001 White Hat](ADR-0001-white-hat.md) authorization model
