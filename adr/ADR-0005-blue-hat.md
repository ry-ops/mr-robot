---
adr: 0005
title: Blue Hat
hat: Blue Hat
color: blue
class: Individual Hat
status: Accepted
posture: Pre-deployment offensive testing
authorization: Authorized scope, restricted to pre-production targets
date: 2026-05-20
---

# ADR-0005: Blue Hat

## Status

Accepted — the Blue Hat is scope-bound offensive testing against a target
that happens to be pre-production. From the runtime's perspective that is
the White Hat contract with a different label on the Engagement. The
"pre-production" attestation is a property of the Engagement, not a runtime
enforcement point; `server/scope.py` and the existing MCP surface support
the contract today. Release-gating output framing is a prompting / report
concern, not a gating concern.

## Context

The Blue Hat (in the Microsoft sense) is an outside specialist invited to test a
system **before it goes live** — a fresh, external set of eyes during
pre-release or pre-deployment hardening.

Mr. Robot's Blue Hat is the pre-production assessment mode: testing staging
environments, release candidates, and new infrastructure against an authorized
scope, before they reach production or the public.

## Decision

The Blue Hat is the White Hat applied to a pre-production target with a
release-gate output framing. Microsoft Blue Hat lineage: outside specialists
testing a system before it ships.

### Posture & authorization

Same authorization model as the White Hat: an Engagement row with a
`box_ip` allowlist, checked by `server/scope.py` on every active tool. The
*environment* property — that the target is staging, a release candidate,
or otherwise non-production — is an attestation captured on the Engagement,
not a runtime gate. The operator is responsible for not pointing the Blue
Hat at a production IP; the runtime cannot tell the difference.

This is a deliberate choice: trying to mechanically distinguish "pre-prod"
from "prod" IPs is unreliable and not the scope guard's job. The Hat label
on the Engagement is the contract.

### Tool envelope

Same as the White Hat — the full offensive inventory. The Blue Hat does not
need a different tool surface; it needs the same surface against a different
class of target. Per-Hat tool gating is not yet runtime-enforced, and for
this Hat that is fine: the Blue Hat is entitled to everything the White Hat
is entitled to.

### Rules of Engagement

1. No action outside `box_ip`. Enforced.
2. Engagement metadata declares the target environment (`environment:
   staging | rc | preprod`) on creation. Operator attestation, not runtime
   detection.
3. Output framing is release-gating: each finding carries a severity that
   maps to a go / no-go recommendation. This is a reporting concern handled
   by the live report renderer (ADR-0012); the underlying findings use the
   same arcade types.
4. Time-boxing is the operator's responsibility — the Blue Hat does not
   self-terminate at a release deadline.

### Integration with arcade & playbook

The Blue Hat produces the same finding types as the White Hat: `port`,
`service`, `web_path`, `credential`, `cve`, `foothold`, `privesc_vector`,
`flag`. It accepts the same task templates from `~/playbooks/`. A
pre-production-specific playbook (e.g., `preprod-default.yaml`) can be
selected on the Engagement to bias task generation toward release-gating
priorities — supply-chain checks, default credentials, exposed
debug/staging endpoints — without changing the runtime contract.

The live report's go / no-go verdict is a Blue-Hat-specific rendering of
the arcade state. The renderer is a Blue or Purple robot's job (see
ADR-0012); the data is the same data the White Hat would produce.

### Interaction with the memory layer (ADR-0014)

Full `memory_*` task-tier surface, same as the White Hat. Recollections from
prior Blue Hat engagements are high-value for future ones — release-gating
patterns (default creds, exposed staging endpoints, common CI/CD missteps)
generalize especially well across products. Cross-Hat recall: a Blue Hat
robot picking up a foothold task benefits from reading both Blue Hat and
White Hat outcomes on similar fingerprints; the `memory_recall_for_task`
shape supports this with task-type filtering.

## Consequences

This Hat is time-boxed to a release cycle. It shares the White Hat's
authorization model but adds an environment constraint (non-production only)
that is attested rather than enforced.

## Open Questions

- Severity-to-go/no-go threshold — codify in the playbook, the renderer, or
  the Engagement metadata?
- Does the live report need a Blue-Hat-specific template separate from the
  generic forensic writeup?
- Should the Engagement's `environment` attestation be surfaced to robots in
  their system prompt as a behavioural prior (e.g., bias toward business-
  logic findings on staging web apps)?

## Related

- [ADR index](README.md)
- Shares the authorization model of [ADR-0001 White Hat](ADR-0001-white-hat.md)
