---
adr: 0004
title: Red Hat
hat: Red Hat
color: red
class: Individual Hat
status: Proposed
posture: Counter-offensive analysis
authorization: Defensive analysis only; no offensive action against any system
date: 2026-05-20
---

# ADR-0004: Red Hat

## Status

Proposed — the Red Hat's contract requires defensive-analysis tooling
(sandboxed malware detonation, IOC extraction, attacker-infrastructure
enrichment) that does not exist in `server/` today. Recon tooling is built;
nothing in the current MCP surface analyses attacker artifacts. Promote to
Accepted when the defensive-analysis tool family lands and per-Hat gating in
`mr_robot.py` constrains the Red Hat to it. Until then, this ADR records
intent.

## Context

In the colored-hat taxonomy the Red Hat is the vigilante — aggressive toward
malicious actors. "Hacking back" is legally fraught and out of scope for Mr.
Robot, so this Hat is recast as an **active-defense and adversary-analysis**
mode: investigating attacker infrastructure, malware, and tradecraft to
understand and disrupt threats through lawful means.

## Decision

The Red Hat is recast away from "hack back" entirely. It is the
analyst-of-the-adversary role: take attacker artifacts and external threat
indicators as input, produce structured intelligence as output. It operates
on artifacts, not on systems.

### Posture & authorization

The Red Hat does not target systems. The `box_ip` allowlist is still loaded
when the Hat runs inside an Engagement, but the Red Hat's tools should not
need to touch it — its inputs are files (malware samples, phishing kits,
captured PCAPs) and external read-only enrichment endpoints (VirusTotal-class
lookups, public threat-intel feeds). For external lookups, the scope guard
does not authorize them — they are out-of-scope by construction. The Red Hat
needs a separate "external-enrichment allowlist" runtime, which is not yet
built.

"Hack-back" against suspected attacker infrastructure is **explicitly out of
scope** regardless of provocation. Authorization to act offensively comes
from `box_ip` for the boxes the operator owns / has authorization on; it does
not extend to attacker systems.

### Tool envelope

Defensive-analysis only:

- Sandboxed file analysis (static + dynamic malware analysis in an isolated
  environment, never on the host).
- Network-artifact analysis (PCAP, HTTP archives, mail headers).
- IOC extraction (hashes, domains, IPs, mutexes, YARA hits).
- External threat-intel enrichment (read-only).
- Attribution and TTP mapping (MITRE ATT&CK).

Forbidden:

- Any active probe against attacker-controlled infrastructure.
- Any tool whose target is a live system rather than a captured artifact.

**Not built today.** No tool in the current `mr_robot` MCP server matches
this envelope. Promotion requires both (a) building the analysis tools and
(b) gating the Red Hat to that family in `mr_robot.py`. Until then the Hat
has nothing to do at runtime.

### Rules of Engagement

1. No tool may transmit to attacker-controlled infrastructure under any
   pretext, including beaconing-back, attribution probes, or "polite"
   takedown notifications. Hard rule.
2. Malware analysis happens in a sandbox that has no route to the
   operator's network or the engagement box. The sandbox environment is a
   precondition for the tool family, not a per-invocation flag.
3. External enrichment lookups are read-only and rate-limited. They use
   their own authorization (API keys) and are not governed by `box_ip`.
4. Findings produced here are intelligence artifacts, clearly distinct from
   in-engagement attack-surface findings.

### Integration with arcade & playbook

The Red Hat's outputs do not fit the existing arcade finding types cleanly.
`cve` is the closest match for "this sample uses CVE-X" but the broader IOC
shape (hashes, C2 domains, TTPs) is not a `port` or `web_path`. Options:
extend the finding-type enum with `ioc` and `ttp`, or keep Red Hat output in
a separate intel store outside the arcade. The current ADR-0012 enum is
fixed, so the Red Hat is effectively un-integrated until that decision lands.

The playbook engine routes findings to tasks; without Red-Hat-specific
finding types it cannot route Red Hat work. Inside HTB this is rarely
needed; the Red Hat is a future-engagement capability.

### Interaction with the memory layer (ADR-0014)

**Read-only of the offensive corpus; write to a separate intel namespace.**
The Red Hat benefits from recalling what attacker TTPs were observed across
prior engagements (`memory_recall_for_task` with task type filters that
match analysis tasks), but its writes are categorically different from
offensive task outcomes — they are intelligence, not craft. Mixing them
into the same `memory_record_task_outcome` stream would dilute the
offensive recall corpus for the other Hats.

Concrete proposal: the Red Hat gets `memory_recall_for_task` (read on the
shared store) but its writes go through a Red-Hat-specific path (or are
tagged so other Hats' recalls exclude them by default). The shared
`server/memory.py` adapter is the right seam.

## Consequences

This Hat consumes threat data and produces intelligence; it pairs naturally
with the Blue Team for detection and the Red Team for emulation planning.
None of that runs in v0.1 — the Red Hat is the first ADR whose acceptance
is gated on net-new tooling rather than gating policy.

## Open Questions

- Which sandboxing / detonation environment is the canonical choice on
  Kali — Cuckoo successor, FLARE-VM in a VM, or a containerised setup?
- IOC export formats — STIX, MISP, plain JSON? Pick one for v1.
- Arcade finding-type extension vs. separate intel store — which costs less?
- Does the Red Hat need its own external-network allowlist (separate from
  `box_ip`) to make enrichment lookups, or is that out of scope for v1?

## Related

- [ADR index](README.md)
- Feeds [ADR-0010 Blue Team](ADR-0010-blue-team.md)
