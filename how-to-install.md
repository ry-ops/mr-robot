# How to install Mr. Robot

A step-by-step setup for getting Mr. Robot running on a Kali host. Everything
is feature-detected: if a backend is missing, the layer that needs it degrades
quietly and the rest of the system keeps running. You can do a mock run with
nothing but Python — then add the memory backends when you want compounding
judgment.

Tested on Kali Linux 2026.1 (kernel 6.19.x) with Python 3.13. Should work on
any Debian-derived distro with equivalent versions.

## 1. Prerequisites

| Tool | Why | How to get it on Kali |
|------|-----|-----------------------|
| Python 3.11+ | runtime | ships with Kali |
| `git` | clone | ships with Kali |
| `docker` | runs Qdrant | `sudo apt install -y docker.io && sudo systemctl enable --now docker` |
| `redis-server` | recall cache | `sudo apt install -y redis-server` (run unprivileged — see step 5) |
| [Claude Code](https://docs.claude.com/en/docs/claude-code) | drives the MCP server and the agent robots | follow the official installer for your platform |

The `mcp` and `PyYAML` Python packages already ship with Kali's system
Python; `server/requirements.txt` lists them for portability.

## 2. Clone the repo

```bash
git clone https://github.com/ry-ops/mr-robot.git ~/Mr.\ Robot
cd ~/Mr.\ Robot
```

The directory name has a space on purpose — it matches the project title.
Quote it in shell commands, or use tab-completion.

## 3. Install Python dependencies

```bash
pip install --user --break-system-packages -r server/requirements.txt
```

For real (non-mock) runs you also need the Claude Agent SDK so the
orchestrator can spawn Hat robots as actual Claude agents:

```bash
pip install --user --break-system-packages claude-agent-sdk
```

## 4. Install aiana (the memory backend)

The cross-engagement memory layer (ADR-0014) is provided by
[aiana](https://github.com/ry-ops/aiana). It is not on PyPI; install from the
repo:

```bash
pip install --user --break-system-packages git+https://github.com/ry-ops/aiana.git
```

If you skip this step, `server/memory.py` degrades to a no-op. The
orchestrator runs unchanged but its judgment does not compound across
engagements.

## 5. Start Redis (recall cache)

The memory layer caches reads in Redis with a generation-counter invalidation
scheme (ADR-0014). Run it as your user, no root, no system service:

```bash
mkdir -p ~/redis-data
redis-server --daemonize yes --port 6379 --bind 127.0.0.1 \
  --dir ~/redis-data --save "" --appendonly no
```

Verify:

```bash
redis-cli ping   # → PONG
```

If Redis is unavailable, recall reads bypass the cache and hit
SQLite/Qdrant directly. Writes are unaffected.

## 6. Start Qdrant (vector store)

The memory layer's semantic-recall side runs on Qdrant. Easiest is the
official container:

```bash
mkdir -p ~/qdrant_storage
docker run -d --name mr-robot-qdrant \
  -p 6333:6333 \
  -v ~/qdrant_storage:/qdrant/storage \
  qdrant/qdrant
```

Verify:

```bash
curl -fsS http://localhost:6333/readyz   # → "all shards are ready"
```

If Qdrant is unavailable, the memory layer **degrades to FTS5-only** —
brain quality drops; the orchestrator does not halt.

## 7. Register the MCP server with Claude Code

The `mr-robot` MCP server is the arsenal layer — Claude Code (and the
AgentRobots the orchestrator spawns) reach the arcade, playbook, and Hat
registry through it.

```bash
claude mcp add mr-robot python3 "$HOME/Mr. Robot/server/mr_robot.py"
claude mcp list   # confirm "mr-robot" is present
```

## 8. Verify with a mock run

A mock run uses deterministic stand-in robots — no tokens spent, no network,
exercises the entire control loop:

```bash
python3 "server/orchestrator.py" Lame 10.10.10.3 --mock
```

You should see heartbeats tick, findings post into the arcade, the playbook
unlock new tasks, and the loop converge on terminal condition. The
engagement workspace lands under `engagements/Lame/` with a live
`report.md` and the engagement's `arcade.db`.

## 9. First real run

A real run spawns Claude-agent robots, one per Hat, against a HackTheBox
target you are authorized to test:

```bash
python3 "server/orchestrator.py" <box> <ip>
```

Tokens are billed to whichever Anthropic account Claude Code is signed in
to. Start small — one or two pool slots — to get a feel for cost before
scaling up.

## 10. Optional — environment overrides

| Var | Default | Purpose |
|-----|---------|---------|
| `MR_ROBOT_HOME` | the project dir | ADRs + default data location |
| `MR_ROBOT_PLAYBOOKS` | `~/playbooks` | playbook directory |
| `MR_ROBOT_ENGAGEMENTS` | `<home>/engagements` | arcade.db + per-box workspaces |
| `MR_ROBOT_QDRANT_URL` | `http://localhost:6333` | local Qdrant endpoint |
| `MR_ROBOT_QDRANT_COLLECTION` | `mrrobot-memory` | local Qdrant collection |
| `MR_ROBOT_REDIS_URL` | `redis://localhost:6379/0` | recall cache |
| `MR_ROBOT_MEMORY_CACHE_TTL_SECONDS` | `600` | cache TTL |

The co-op (ADR-0015) is **Proposed** and not wired yet —
`MR_ROBOT_COOP_*` variables are reserved for the eventual implementation.

## Troubleshooting

**`claude mcp list` does not show `mr-robot`.**
Re-run step 7. The path passed to `claude mcp add` must be the absolute path
to `server/mr_robot.py`, with the space in `Mr. Robot` either escaped or
quoted.

**Memory layer logs `aiana unavailable` at startup.**
Step 4 was skipped or `pip install` landed in a different Python. Confirm
with `python3 -c "import aiana; print(aiana.__version__)"`. If that fails,
re-run step 4 — the `--user --break-system-packages` combination is what
Kali expects.

**`redis-cli ping` returns nothing or `Connection refused`.**
Step 5 did not start a daemon. Re-run the `redis-server --daemonize yes ...`
line. Confirm with `pgrep -a redis-server`.

**Qdrant container exited.**
Check `docker logs mr-robot-qdrant`. Most common cause: port 6333 already
in use. Either free the port or start the container on a different one and
set `MR_ROBOT_QDRANT_URL` to match.

**Mock run prints nothing and exits.**
You probably ran it from a directory other than the project root. Either
`cd ~/Mr.\ Robot` first, or set `MR_ROBOT_HOME` to the absolute path.

## What you have now

- Layer 1 (the arsenal) registered with Claude Code as the `mr-robot` MCP server.
- Layer 2 (the orchestrator) ready to spawn Hat robots — mock or real.
- The memory layer wired to aiana, Qdrant, and Redis — each independently
  feature-detected and graceful when missing.

See [`README.md`](README.md) for the architecture overview and
[`adr/`](adr/) for the decision records that explain *why* every piece is
shaped the way it is.
