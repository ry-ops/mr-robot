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

Register at **user scope** so the server is visible from any directory, not
just the one you ran `claude mcp add` from:

```bash
claude mcp add -s user mr-robot python3 "$HOME/Mr. Robot/server/mr_robot.py"
claude mcp list   # confirm "mr-robot: ... ✓ Connected"
```

If you omit `-s user`, Claude Code defaults to **local** scope — the
registration is bound to the current working directory and `claude mcp list`
will not show it from anywhere else. Easy mistake; user scope is the right
default for an MCP server you intend to drive the orchestrator with.

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

## 11. Optional — capture Claude Code in aiana

Aiana (step 4) can hold **everything Claude Code does in this project**,
not just Mr. Robot's engagement memory. Two independent integrations
land in the same `~/.aiana/conversations.db`:

- **Raw conversation transcripts** — captured by aiana's Claude Code
  hooks as each session runs.
- **Distilled auto-memory** — the markdown notes Claude Code maintains
  at `~/.claude/projects/*/memory/*.md`, mirrored into aiana by a
  small bridge container in `infra/auto-memory-bridge/`.

Both are optional and additive. Mr. Robot's orchestrator runs identically
whether they're on or off.

### 11a. Install aiana's Claude Code hooks

```bash
python3 -c "from aiana.hooks import install_hooks; install_hooks()"
```

This adds three entries (`SessionStart`, `SessionEnd`, `PostToolUse`) to
`~/.claude/settings.json`, each running `aiana hook ...` on PATH. Hooks
take effect on the **next** Claude Code session — the one running when
you install does not get captured.

Verify the next session lands a row:

```bash
sqlite3 ~/.aiana/conversations.db \
  "select id, started_at from sessions order by started_at desc limit 5;"
```

To uninstall later:

```bash
python3 -c "from aiana.hooks import uninstall_hooks; uninstall_hooks()"
```

### 11b. Run the auto-memory bridge

The bridge is a containerised watcher that mirrors auto-memory files
into aiana on change. Source lives in `infra/auto-memory-bridge/` and
talks to host-aiana's SQLite via a volume mount.

Prerequisites — the bridge runs in Docker, so you need group access
and the compose plugin:

```bash
sudo usermod -aG docker $USER
newgrp docker                              # take effect in this shell
sudo apt install -y docker-compose-plugin  # if not already installed
```

Bring up:

```bash
cd ~/Mr.\ Robot/infra/auto-memory-bridge
UID=$(id -u) GID=$(id -g) docker compose up -d --build
docker compose logs -f
# → [bridge] initial sync: wrote=N skipped=0 invalid=0 failed=0
# → [bridge] watching for changes
```

Smoke-test that a new auto-memory file is picked up:

```bash
cat > ~/.claude/projects/-home-ryan-Mr--Robot/memory/_smoke.md <<'EOF'
---
name: bridge-smoke
description: smoke-test entry
metadata:
  type: reference
---
hello from the bridge smoke test
EOF

# bridge logs should print:
#   [bridge] wrote: /claude/projects/.../memory/_smoke.md

# confirm the row:
sqlite3 ~/.aiana/conversations.db \
  "select substr(id, 1, 30), summary from sessions
   where metadata like '%auto-memory%' order by started_at desc limit 3;"

# clean up:
rm ~/.claude/projects/-home-ryan-Mr--Robot/memory/_smoke.md
```

Tear down:

```bash
cd ~/Mr.\ Robot/infra/auto-memory-bridge
docker compose down
```

The bridge is idempotent — re-running `docker compose up -d --build`
after a tear-down skips every file whose body hash is unchanged.
Content changes produce new versioned sessions; history is preserved.

If your environment is one where bind-mount inotify events don't
reach the container (some Docker Desktop setups), set
`BRIDGE_POLLING=1` in `docker-compose.yml` to fall back to
filesystem polling at `BRIDGE_POLL_INTERVAL` seconds (default 2).

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

**Hooks installed but the current session isn't captured (step 11a).**
Expected. Claude Code reads `settings.json` at session start, so any
hooks added mid-session apply only from the next session onward.
Restart Claude Code and re-check.

**`docker compose up` fails with "permission denied … docker.sock" (step 11b).**
The shell user isn't in the `docker` group. Run `sudo usermod -aG docker
$USER && newgrp docker` (or open a new shell). Confirm with `groups |
grep docker`.

**Bridge logs `initial sync: invalid=N` (step 11b).**
N memory files lack valid YAML frontmatter (the `---\n<yaml>\n---\n<body>`
shape). Inspect with `head -5 ~/.claude/projects/*/memory/*.md` and either
fix the frontmatter or delete the malformed file. `MEMORY.md` is the
index file and is intentionally skipped — it does not count as invalid.

## What you have now

- Layer 1 (the arsenal) registered with Claude Code as the `mr-robot` MCP server.
- Layer 2 (the orchestrator) ready to spawn Hat robots — mock or real.
- The memory layer wired to aiana, Qdrant, and Redis — each independently
  feature-detected and graceful when missing.
- If you did step 11: aiana also capturing raw Claude Code transcripts
  (via hooks) and the auto-memory bridge mirroring distilled notes into
  the same DB.

See [`README.md`](README.md) for the architecture overview and
[`adr/`](adr/) for the decision records that explain *why* every piece is
shaped the way it is.
