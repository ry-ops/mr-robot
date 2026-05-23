---
adr: 0006
title: Green Hat
hat: Green Hat
color: green
class: Individual Hat
status: Proposed
posture: Educational / lab-only
authorization: Lab, CTF, and operator-owned practice targets only
date: 2026-05-20
---

# ADR-0006: Green Hat

## Status

Proposed. The Hat's contract turns on a lab-mode gate that the runtime does
not yet enforce — `server/scope.py` validates the `box_ip` allowlist for every
engagement but does not distinguish "lab" from "production" targets, and the
verbose narration mode is a robot prompt that has not been written. The Hat
becomes Accepted once a lab-target attestation lands in the engagement scope
and a narration mode is wired into the robot persona.

## Context

The Green Hat is the newcomer — eager to learn, still building fundamentals.

Mr. Robot's Green Hat is the teaching mode: it favors explanation over speed,
narrates what each tool and flag does and why, and confines all activity to lab
environments, CTFs, and operator-owned practice targets.

## Decision

### Posture & authorization

A Green Hat robot operates only against lab, CTF, and operator-owned practice
targets. Authorization is two-part: the engagement scope's `box_ip` allowlist
(enforced today by `server/scope.py`) plus a **lab-mode attestation** on the
engagement — the operator declares the box is a known practice range (HTB,
local lab, owned VM). The attestation is not runtime-enforced yet; for now it
is a contract on the operator and an intent recorded on the engagement.

The Hat is the opposite end of the comprehension spectrum from the Script
Kiddie (ADR-0008): Script Kiddie restricts *what* may run, Green Hat restricts
*how* it is explained.

### Tool envelope

Recon and read-only enumeration tools are in-envelope. Exploitation,
credential attacks, and post-exploitation are out-of-envelope — not because
the targets are off-limits but because the persona's purpose is teaching, and
one-shot exploitation skips the explanation step. Every in-envelope tool is
wrapped with a pre-run narration.

Per-Hat tool gating is **not yet runtime-enforced** — every robot today sees
the same MCP tool surface via `server/mr_robot.py`. This envelope is a
contract on the Green Hat persona until `mr_robot.py` grows a per-Hat
allowlist (read from `hats.py` frontmatter) checked at tool-dispatch time.

### Rules of Engagement

- Lab-mode attestation required on the engagement. No "production" or
  ambiguous targets, ever.
- Every command is previewed in plain English before execution: purpose,
  flags, expected output, how to interpret results.
- One-shot automation is refused — the Hat works step by step.
- Findings are posted with a teaching annotation in `data`, not a raw tool
  dump.
- No exploitation, no destructive actions, even if the target is in scope.

### Integration with arcade & playbook

A Green Hat robot produces low-velocity, high-explanation findings — mostly
`port`, `service`, and `web_path` — and accepts playbook tasks of those
types. It does not accept `foothold`, `privesc_vector`, or `flag` tasks; the
playbook router skips Green-Hat robots for those. The forensic report
produced via the arcade reads as a walkthrough when a Green Hat ran the
engagement.

### Interaction with the memory layer (ADR-0014)

Green Hat gets a **reduced, read-only** `memory_*` surface:
`memory_recall_for_task` only. It does not write task outcomes. Rationale:
the Hat exists to grow the *operator's* understanding, not the corpus, and
its narrative task outcomes would dilute recall quality for the production
Hats that share the same store. On the ADR-0014 open question of per-Hat
gating, this is the explicit reduced subset.

For Team-level recall scoping, not applicable — Green Hat is an Individual
Hat.

## Consequences

This Hat trades speed for comprehension. Its output style (verbose, didactic)
differs sharply from the other Hats and needs its own reporting template.

## Open Questions

- How is "lab-mode" attested on the engagement — a flag in the scope file, a
  separate allowlist of known lab CIDRs (HTB ranges, TryHackMe, local labs),
  or both?
- Where does the narration template live — robot persona prompt, or a
  playbook-style file alongside `htb-default.yaml`?
- Should triggering a refused tool nudge the operator into a different Hat
  rather than just blocking?

## Related

- [ADR index](README.md)
- Contrasts with [ADR-0008 Script Kiddie](ADR-0008-script-kiddie.md)
