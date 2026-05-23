# Mr. Robot — server

The `mr-robot` MCP server (layer 1, "the arsenal") and the orchestrator
(layer 2, "Mr. Robot"). Design records: `../adr/`.

## Layout

| File | Layer | Role |
|------|-------|------|
| `mr_robot.py`     | 1 | FastMCP server — engagement / arcade / hat / recon tools |
| `arcade.py`       | 1 | SQLite findings store + task board (ADR-0012) |
| `playbook.py`     | 1 | loads `~/playbooks/*.yaml`, turns findings into tasks |
| `hats.py`         | 1 | loads the Hat personas from `../adr/` |
| `scope.py`        | 1 | the ethics axis — target allowlist, enforced in code |
| `orchestrator.py` | 2 | Mr. Robot — the heartbeat control loop (ADR-0013) |
| `robots.py`       | 2 | Robot interface · MockRobot · AgentRobot |
| `brain.py`        | 2 | heuristic direction judgment (LLM seam marked) |

Dependencies (`mcp`, `PyYAML`, `claude-agent-sdk`) are installed in the
system / user Python — no venv required.

## Run the MCP server

```
python3 "/home/ryan/Mr. Robot/server/mr_robot.py"
```

Already registered with Claude Code as `mr-robot` (`claude mcp list`).

## Run the orchestrator

```
# mock — deterministic, no tokens, exercises the whole control loop
python3 "/home/ryan/Mr. Robot/server/orchestrator.py" <box> <ip> --mock

# real — spawns Claude-agent robots, one Hat each (costs tokens)
python3 "/home/ryan/Mr. Robot/server/orchestrator.py" <box> <ip> [--pool N] [--model M]
```

## Environment

| Var | Default | Purpose |
|-----|---------|---------|
| `MR_ROBOT_HOME` | the project dir | ADRs + default data location |
| `MR_ROBOT_PLAYBOOKS` | `~/playbooks` | playbook directory |
| `MR_ROBOT_ENGAGEMENTS` | `<home>/engagements` | arcade.db + workspaces (override to isolate tests) |

## How it fits together

```
orchestrator.py ── spawns ──> robots (MockRobot | AgentRobot)
      │                            │
      │ reads/writes               │  AgentRobot = a Claude agent:
      ▼                            ▼  Hat ADR persona + mr-robot MCP tools
   the arcade  <── findings unlock tasks ── playbook
```

The orchestrator reads the arcade directly; AgentRobots reach it through the
`mr-robot` MCP server. A finding posted → the playbook spawns tasks → the loop
assigns robots → repeat, until both flags are captured or the board drains.

## Not yet built

- Robot tooling beyond recon — scope-checked web / exploitation wrappers.
- The LLM brain — `brain.py` has the seam; today's brain is heuristic.
