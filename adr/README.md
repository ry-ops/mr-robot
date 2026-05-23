# Mr. Robot

An "everything" offensive **and** defensive security MCP server for Kali —
driven entirely by Architecture Decision Records (ADRs).

## Concept

Mr. Robot does not hard-code its behavior. Every operating mode — what tools it
may run, against which targets, with what posture, and how it reports — is
defined by an ADR. Each ADR prefaces a **Hat**: a named persona with its own
ethics, authorization model, rules of engagement, and capability envelope.

At runtime the server loads the active Hat's ADR and operates strictly within
that contract. Switching Hats switches the entire behavior of the tool.

## The Hats

### Individual Hats

| ADR | Hat | Posture |
|-----|-----|---------|
| [0001](ADR-0001-white-hat.md) | White Hat | Authorized offensive testing |
| [0002](ADR-0002-black-hat.md) | Black Hat | Adversary emulation (scoped) |
| [0003](ADR-0003-gray-hat.md) | Gray Hat | Non-intrusive / passive only |
| [0004](ADR-0004-red-hat.md) | Red Hat | Counter-offensive analysis |
| [0005](ADR-0005-blue-hat.md) | Blue Hat | Pre-deployment testing |
| [0006](ADR-0006-green-hat.md) | Green Hat | Educational / lab-only |
| [0007](ADR-0007-purple-hat.md) | Purple Hat | Self-assessment of owned assets |
| [0008](ADR-0008-script-kiddie.md) | Script Kiddie | Guarded automation |

### Teams

| ADR | Hat | Posture |
|-----|-----|---------|
| [0009](ADR-0009-red-team.md) | Red Team | Objective-based offense |
| [0010](ADR-0010-blue-team.md) | Blue Team | Detection & defense |
| [0011](ADR-0011-purple-team.md) | Purple Team | Collaborative validation |

## Architecture

ADRs that define structural components rather than Hat personas.

| ADR | Component | Role |
|-----|-----------|------|
| [0012](ADR-0012-the-arcade.md) | The Arcade | Shared findings store + task board, backed by SQLite |
| [0013](ADR-0013-the-orchestrator.md) | The Orchestrator | Mr. Robot — spawns and supervises Hat robots; the control loop |
| [0014](ADR-0014-the-memory.md) | The Memory | Cross-engagement recall via aiana; SQLite + Qdrant + Redis |
| [0015](ADR-0015-the-co-op.md) | The Co-op | *Proposed* — cross-operator memory; cloud + event (join-key) modes; htb-api sibling MCP server upcoming |

## ADR Lifecycle

```
Proposed  →  Accepted  →  ( Deprecated | Superseded )
```

ADR-0012, ADR-0013, and ADR-0014 are **Accepted** — built and verified.
ADR-0014's three backends (aiana/SQLite-FTS5, Qdrant, Redis) were verified
end-to-end on 2026-05-23 with all three services running; each is
feature-detected and degrades independently.

ADR-0015 (the co-op) is **Proposed**. Its promotion criterion is named in
the ADR: a wired Qdrant Cloud backend in `server/memory.py`, a scrubber on
the share paths, an opt-in env flag, a pseudonymous instance handle, and
a verified write→read round trip from one instance to another.

Hat ADRs have been finalized. Those whose contract reduces to "operate within
the engagement's `box_ip` scope using the wired toolset" — and is therefore
enforced today by `server/scope.py` — are **Accepted**: 0001 White Hat, 0002
Black Hat, 0005 Blue Hat, 0007 Purple Hat, 0009 Red Team. Those whose contract
requires runtime behavior not yet built (per-Hat tool gating, lab-mode flags,
destructive-action throttling, defensive tooling) remain **Proposed**: 0003
Gray Hat, 0004 Red Hat, 0006 Green Hat, 0008 Script Kiddie, 0010 Blue Team,
0011 Purple Team. Each ADR's Status section names its promotion criterion.

## Structure of an ADR

Each file carries machine-readable YAML frontmatter (so the server can load it)
followed by a human-readable record: Status, Context, Decision, Consequences,
Open Questions, and Related links.
