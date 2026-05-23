---
adr: 0003
title: Gray Hat
hat: Gray Hat
color: gray
class: Individual Hat
status: Proposed
posture: Non-intrusive / passive only
authorization: Incomplete or absent — capability deliberately constrained
date: 2026-05-20
---

# ADR-0003: Gray Hat

## Status

Proposed — the Gray Hat's defining contract is "passive only, no active
tooling". That is a *restriction* on the tool surface beyond what
`server/scope.py` enforces, and per-Hat tool gating does not yet exist in
runtime: every robot is handed the same `mr_robot` MCP server (see
`server/robots.py::AgentRobot`). Promote to Accepted when `mr_robot.py`
filters `allowed_tools` by the running Hat and the Gray Hat's passive-only
allowlist is wired in. Until then the contract is intent, not enforcement,
and shipping it as Accepted would misrepresent what the runtime guarantees.

## Context

The Gray Hat operates between White and Black: often well-intentioned, but
acting without full, explicit authorization — for example, probing a system out
of curiosity and then disclosing what they find. The legal and ethical risk
lives entirely in that authorization gap.

Mr. Robot treats the Gray Hat as the mode for when an engagement is **not yet
authorized**. Rather than enabling risky unsanctioned activity, this Hat
deliberately constrains capability to non-intrusive, passive, publicly
observable techniques — and steers the operator toward obtaining proper
authorization.

## Decision

The Gray Hat is the pre-authorization mode: a deliberately narrow envelope
that lets the operator gather public, non-touching information about a target
before an engagement is opened. It is the only Hat that can be active without
an Engagement row, and the only one whose contract is a *subtraction* from
the default tool surface.

### Posture & authorization

The Gray Hat does **not** depend on `box_ip`. It is the mode used when no
authorization exists yet. The scope guard (`server/scope.py`) is still
present and would refuse any active tool against a non-allowlisted IP, but
the Gray Hat's contract goes further: it forbids *any* tool that touches the
target, allowlisted or not. Authorization is replaced by capability
restriction.

When an Engagement is opened against the same target, the operator escalates
to the White Hat (or another offensive Hat) and the Gray Hat's restrictions
no longer apply.

### Tool envelope

Passive only. Permitted categories:

- Public OSINT (search, WHOIS, public registries).
- Passive DNS, certificate transparency.
- Reading public sources (org websites, leaked credential databases as
  read-only references, public code repositories).

Forbidden categories:

- Active scanning of any kind (`recon_portscan`, service probes, banner
  grabs that connect to the target).
- Web fetches against the target (any HTTP request to a target host counts
  as touching).
- Brute force, credential testing, exploitation, post-exploitation,
  cracking.

This is **not yet runtime-enforced**. Per-Hat tool gating would live in
`mr_robot.py`: the agent's `allowed_tools` list would be filtered against a
Hat-keyed allowlist (e.g., `gray-hat: [memory_*, arcade_post_finding, ...]`,
explicitly no `recon_*` or anything that opens a socket to the target).
Until that filter lands, the envelope is communicated to the robot through
its system prompt only — which is not a safety guarantee.

### Rules of Engagement

1. No tool that opens a connection to the target. Intent; not enforced.
2. Findings posted to the arcade are tagged with `confidence: speculative`
   or `likely` only — Gray Hat work does not produce `confirmed` findings,
   because confirmation requires touching the target.
3. The Gray Hat surfaces an escalate-to-White-Hat prompt as soon as any task
   on the board requires an active tool to make progress. It does not
   silently skip those tasks.
4. Memory writes are read-only intent — see below.

### Integration with arcade & playbook

The Gray Hat can run without an Engagement row, in which case its findings
are held in a draft workspace and promoted into a real Engagement on
escalation. Inside an Engagement, the Gray Hat produces low-confidence
findings of type `service` (inferred from public sources, e.g., shodan),
`web_path` (from passive web tech detection), and occasionally `cve`
(matched against public banners). It does **not** produce `port`,
`credential`, `foothold`, `privesc_vector`, or `flag`.

Task templates the Gray Hat accepts: only those whose `produces` set is a
subset of the above. The playbook engine does not currently filter task
offers by Hat; this is the same gap as the tool envelope.

### Interaction with the memory layer (ADR-0014)

**Reduced surface.** The Gray Hat gets `memory_recall_for_task` (read) but
**not** `memory_record_task_outcome` (write). Rationale: pre-authorization
reconnaissance is too noisy and too context-dependent to be worth
generalizing into durable craft, and the Gray Hat's confidence floor means
its outcomes are weak signal at best. Recall is still useful — "what did we
learn about this org / this fingerprint last time" — but writes would dilute
the corpus.

This is the per-Hat answer to ADR-0014's open question on whether some Hats
get a reduced `memory_*` subset: yes, and the Gray Hat is the case.

## Consequences

This Hat is a safety airlock: it lets discovery begin before an engagement is
formalized without crossing into unauthorized activity. Its contract is a
*subtraction* from the default tool surface, which is the first place
per-Hat tool gating becomes load-bearing rather than aspirational.

## Open Questions

- Which specific techniques qualify as truly "non-intrusive" — does a TLS
  handshake to read a cert count, or only passive CT log lookups?
- Should results gathered here auto-populate a draft engagement scope on
  escalation?
- Per-Hat tool gating implementation — Hat-keyed allowlist in
  `server/hats.py` consumed by `mr_robot.py` at agent construction, or a
  decorator on each MCP tool? The Gray Hat is the forcing function for this
  decision.

## Related

- [ADR index](README.md)
- Escalates to [ADR-0001 White Hat](ADR-0001-white-hat.md)
