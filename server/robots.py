"""Robots — the workers Mr. Robot spawns and supervises (ADR-0013).

A robot is bound to one Hat for life. It claims a task from the arcade, works
it, posts findings, and completes or dead-ends it — then persists, idle, ready
to be re-tasked within its Hat.

  Robot      — the interface every robot implements.
  MockRobot  — a deterministic, no-LLM robot for exercising the control loop.
  AgentRobot — a real Claude agent (Claude Agent SDK), driven by its Hat ADR.
"""
from __future__ import annotations

import abc
import asyncio
import os
import time
from pathlib import Path

import mr_robot  # arcade tool functions + ARC (shared engine state)

try:
    from claude_agent_sdk import (
        query, ClaudeAgentOptions,
        AssistantMessage, TextBlock, ToolUseBlock, ResultMessage,
    )
    _SDK = True
except ImportError:                                   # pragma: no cover
    _SDK = False

_SERVER = str(Path(__file__).resolve().parent / "mr_robot.py")


class Robot(abc.ABC):
    """One worker. Bound to a single Hat; persists across tasks."""

    def __init__(self, robot_id: str, hat: str, box_name: str):
        self.id = robot_id
        self.hat = hat
        self.box_name = box_name
        self.status = "idle"           # idle | working
        self.current_task: int | None = None
        self.started_at: float | None = None
        self.tasks_done = 0

    @abc.abstractmethod
    async def _execute(self, task: dict) -> None:
        """Hat-specific work: post findings, then complete or block the task."""

    async def run_task(self, task: dict) -> str:
        """Claim a task, execute it, and finalise. Returns an outcome string."""
        self.current_task = task["id"]
        self.status = "working"
        self.started_at = time.time()
        claimed = mr_robot.arcade_claim_task(self.box_name, task["id"], self.id)
        if claimed.startswith("X"):
            self._reset()
            return "claim-failed"
        try:
            await self._execute(task)
        except Exception as exc:                      # noqa: BLE001
            mr_robot.ARC.mark_dead_end(task["id"])
            outcome = f"error: {exc}"
        else:
            # safety net: if the robot left the task in_progress, close it
            t = mr_robot.ARC.get_task(task["id"])
            if t and t["status"] == "in_progress":
                mr_robot.ARC.complete_task(task["id"])
            outcome = "done"
        self.tasks_done += 1
        self._reset()
        return outcome

    def _reset(self) -> None:
        self.status = "idle"
        self.current_task = None
        self.started_at = None


# --- MockRobot -------------------------------------------------------------

# A believable HackTheBox happy path: task type -> findings the robot "finds".
# {ip} is substituted with the engagement box_ip at run time.
_DEFAULT_SCRIPT: dict[str, list[tuple[str, dict]]] = {
    "recon.portscan": [
        ("service", {"port": 22, "service": "ssh"}),
        ("service", {"port": 80, "service": "http", "url": "http://{ip}:80/"}),
    ],
    "enum.web.content": [
        ("web_path", {"path": "/admin", "url": "http://{ip}:80/",
                      "interesting": True}),
    ],
    "enum.web.vulns": [
        ("cve", {"cve_id": "CVE-2021-41773", "target": "http://{ip}:80/"}),
    ],
    "enum.web.path": [
        ("credential", {"username": "admin", "password": "hunter2"}),
    ],
    "exploit.cve": [
        ("foothold", {"host": "{ip}", "user": "www-data",
                      "privilege": "user"}),
    ],
    "privesc.enum": [
        ("privesc_vector", {"host": "{ip}", "summary": "sudo misconfig"}),
    ],
    "privesc.exploit": [
        ("foothold", {"host": "{ip}", "user": "root", "privilege": "root"}),
    ],
    "loot.user-flag": [
        ("flag", {"which": "user", "value": "USER-FLAG-mock"}),
    ],
    "loot.root-flag": [
        ("flag", {"which": "root", "value": "ROOT-FLAG-mock"}),
    ],
}


class MockRobot(Robot):
    """Deterministic robot: 'works' a task by sleeping briefly, then posting
    scripted findings keyed off the task type. No LLM, no real tools — purely
    for exercising the orchestrator control loop and the playbook cascade."""

    speed = 0.3  # simulated seconds per task

    def __init__(self, robot_id: str, hat: str, box_name: str, box_ip: str,
                 script: dict | None = None):
        super().__init__(robot_id, hat, box_name)
        self.box_ip = box_ip
        self.script = script or _DEFAULT_SCRIPT

    async def _execute(self, task: dict) -> None:
        await asyncio.sleep(self.speed)
        for ftype, raw in self.script.get(task["type"], []):
            data = {k: (v.replace("{ip}", self.box_ip)
                        if isinstance(v, str) else v)
                    for k, v in raw.items()}
            mr_robot.arcade_post_finding(self.box_name, ftype, data,
                                         source_hat=self.hat,
                                         source_robot=self.id)
        mr_robot.arcade_complete_task(self.box_name, task["id"])


# --- AgentRobot ------------------------------------------------------------

def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("\n---\n", 1)
        if len(parts) == 2:
            return parts[1].lstrip()
    return text


class AgentRobot(Robot):
    """A real Claude agent (Claude Agent SDK). It adopts its Hat ADR as its
    persona, is handed the mr-robot MCP server, and works one task
    autonomously. The orchestrator treats it identically to a MockRobot."""

    def __init__(self, robot_id: str, hat: str, box_name: str, *,
                 model: str = "claude-sonnet-4-6", max_turns: int = 25):
        super().__init__(robot_id, hat, box_name)
        if not _SDK:
            raise RuntimeError(
                "claude-agent-sdk not installed — "
                "pip install --break-system-packages claude-agent-sdk")
        self.model = model
        self.max_turns = max_turns
        self.last_cost = 0.0
        self.transcript: list[str] = []

    def _persona(self) -> str:
        hat = mr_robot.HATS.get(self.hat)
        title = hat.title if hat else self.hat
        adr = ""
        if hat:
            try:
                adr = _strip_frontmatter(
                    Path(hat.path).read_text(encoding="utf-8"))
            except OSError:
                pass
        return (
            f"You are a {title} robot in the Mr. Robot framework — an "
            f"autonomous operative on an authorized HackTheBox-style "
            f"engagement. You embody this Hat; its intent, ethics and "
            f"behavior govern how you work:\n\n"
            f"{adr}\n\n"
            f"--- ENGAGEMENT RULES ---\n"
            f"- You work exactly ONE assigned task, then stop.\n"
            f"- Use only the `mr_robot` MCP tools. recon_portscan enforces "
            f"engagement scope in code; never try to reach a host outside "
            f"the scope.\n"
            f"- Record discoveries with arcade_post_finding — types: port, "
            f"service, web_path, credential, cve, foothold, privesc_vector, "
            f"flag. Tools that record their own results (recon_portscan "
            f"posts the ports/services it finds) need no re-posting — only "
            f"post what you discover yourself.\n"
            f"- Finish by calling arcade_complete_task. If you cannot make "
            f"progress for lack of information, call arcade_report_blocker "
            f"with a structured resolved_by predicate instead.\n"
            f"- Be terse. Act through tools; do not narrate at length."
        )

    def _mcp_env(self) -> dict:
        env = {}
        for var in ("MR_ROBOT_HOME", "MR_ROBOT_PLAYBOOKS",
                    "MR_ROBOT_ENGAGEMENTS"):
            if var in os.environ:
                env[var] = os.environ[var]
        return env

    def _task_prompt(self, task: dict) -> str:
        eng = mr_robot.ARC.get_engagement(self.box_name)
        box_ip = eng["box_ip"] if eng else "?"
        return (
            f"ENGAGEMENT: {self.box_name}   (scope: {box_ip})\n"
            f"TASK #{task['id']} [{task['type']}]: {task['summary']}\n\n"
            f"This task is already claimed for you. Work it now: use the "
            f"mr_robot tools, post what you find to the arcade, and call "
            f"arcade_complete_task on task {task['id']} when done. Pass "
            f'box_name="{self.box_name}" to every arcade tool.'
        )

    async def _execute(self, task: dict) -> None:
        opts = ClaudeAgentOptions(
            system_prompt=self._persona(),
            mcp_servers={"mr_robot": {
                "type": "stdio",
                "command": "python3",
                "args": [_SERVER],
                "env": self._mcp_env(),
            }},
            strict_mcp_config=True,
            setting_sources=[],
            allowed_tools=["mcp__mr_robot"],
            permission_mode="bypassPermissions",
            model=self.model,
            max_turns=self.max_turns,
            cwd=str(Path(_SERVER).parent),
        )
        async for message in query(prompt=self._task_prompt(task),
                                   options=opts):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, ToolUseBlock):
                        self.transcript.append(f"tool {block.name}")
                    elif isinstance(block, TextBlock):
                        snippet = block.text.strip().replace("\n", " ")
                        if snippet:
                            self.transcript.append(f"say  {snippet[:90]}")
            elif isinstance(message, ResultMessage):
                self.last_cost = message.total_cost_usd or 0.0
                if message.is_error:
                    raise RuntimeError(f"agent error: {message.subtype}")
