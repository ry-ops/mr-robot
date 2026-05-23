#!/usr/bin/env python3
"""Mr. Robot — the orchestrator (ADR-0013).

A standalone control program. It starts/loads an engagement, spawns Hat robots,
and runs a heartbeat loop that assigns work, scales the pool, and adapts — until
both flags are captured or the board runs dry.

Usage:
    python3 orchestrator.py <box_name> <box_ip> [--mock] [--pool N]

Only --mock (deterministic MockRobots) works today; AgentRobot is next.
"""
from __future__ import annotations

import argparse
import asyncio
import itertools
import sys

import memory
import mr_robot
from brain import HeuristicBrain
from robots import AgentRobot, MockRobot


class Orchestrator:
    def __init__(self, box_name: str, box_ip: str, *, pool_size: int = 4,
                 mock: bool = True, heartbeat: float = 0.5,
                 max_ticks: int = 400, model: str = "claude-sonnet-4-6",
                 brain=None):
        self.box_name = box_name
        self.box_ip = box_ip
        self.pool_size = pool_size
        self.mock = mock
        self.model = model
        self.heartbeat = heartbeat
        self.max_ticks = max_ticks
        self.brain = brain or HeuristicBrain()
        self.robots: list = []
        self._spawned = 0                 # total robots ever spawned
        self._running: dict = {}          # robot.id -> asyncio.Task
        self._ids = itertools.count(1)
        self.tick = 0
        self._last_note = ""
        # --- memory layer (ADR-0014) ---
        self._triage_recs: list | None = None       # set once, on first non-empty fp
        self._blocker_recs: dict = {}               # task_id -> [Recollection]
        self._memory_persisted = False

    # --- engagement --------------------------------------------------------
    def _ensure_engagement(self) -> dict:
        if not mr_robot.ARC.get_engagement(self.box_name):
            print(mr_robot.engagement_start(self.box_name, self.box_ip))
        return mr_robot.ARC.require_engagement(self.box_name)

    # --- robot pool --------------------------------------------------------
    def _spawn_robot(self, hat: str):
        rid = f"{hat}-{next(self._ids)}"
        if self.mock:
            robot = MockRobot(rid, hat, self.box_name, self.box_ip)
        else:
            robot = AgentRobot(rid, hat, self.box_name, model=self.model)
        self.robots.append(robot)
        self._spawned += 1
        self._log(f"+ spawned robot {rid}")
        return robot

    def _idle_robots(self, hat: str) -> list:
        return [r for r in self.robots if r.hat == hat
                and r.status == "idle" and r.id not in self._running]

    def _acquire(self, hat: str, needed_hats: set):
        """Get a robot for `hat`: reuse idle, else spawn, else retire+respawn."""
        idle = self._idle_robots(hat)
        if idle:
            return idle[0]
        if len(self.robots) < self.pool_size:
            return self._spawn_robot(hat)
        # pool full — retire an idle robot whose Hat is no longer needed
        for r in list(self.robots):
            if (r.status == "idle" and r.id not in self._running
                    and r.hat not in needed_hats):
                self.robots.remove(r)
                self._log(f"- retired robot {r.id} (hat '{r.hat}' idle, "
                          f"no work)")
                return self._spawn_robot(hat)
        return None

    # --- the control loop --------------------------------------------------
    async def run(self) -> None:
        eng = self._ensure_engagement()
        self._log(f"engagement '{self.box_name}' ({self.box_ip}) — "
                  f"pool={self.pool_size} brain={self.brain.name} "
                  f"mock={self.mock}")
        while self.tick < self.max_ticks:
            self.tick += 1
            self._reap()
            eng = mr_robot.ARC.require_engagement(self.box_name)
            board = mr_robot.ARC.list_tasks(eng["id"])
            if self._terminal(eng, board):
                break
            findings = mr_robot.ARC.list_findings(eng["id"])
            recollections = self._update_recollections(findings, board)
            plan = self.brain.decide(board, self.robots,
                                     recollections=recollections)
            if plan.note != self._last_note:
                self._log(f"brain: {plan.note}")
                self._last_note = plan.note
            self._dispatch(plan, board)
            await asyncio.sleep(self.heartbeat)
        await self._drain()
        self._persist_memory()
        self._report()

    # --- memory layer (ADR-0014) -------------------------------------------
    def _update_recollections(self, findings: list, board: list) -> dict:
        """Refresh triage + per-blocker recollections from the memory layer.

        Fires the triage read once, the first heartbeat with a non-empty
        fingerprint. Fires a blocker read once per newly-blocked task. Both
        are no-ops when aiana is not installed.
        """
        fp = memory.compute_fingerprint(findings)
        if self._triage_recs is None and (fp.ports or fp.services):
            self._triage_recs = memory.MEMORY.recall_similar(fp)
            if self._triage_recs:
                self._log(f"memory: triage recalled "
                          f"{len(self._triage_recs)} similar box(es)")
        for t in board:
            if t["status"] != "blocked" or t["id"] in self._blocker_recs:
                continue
            blocker = {"need": t["summary"], "resolved_by": t["depends_on"]}
            recs = memory.MEMORY.recall_for_blocker(blocker, findings)
            self._blocker_recs[t["id"]] = recs
            if recs:
                self._log(f"memory: blocker on #{t['id']} recalled "
                          f"{len(recs)} match(es)")
        return {
            "triage": self._triage_recs or [],
            "blockers": self._blocker_recs,
            "fingerprint": fp,
        }

    def _persist_memory(self) -> None:
        """Write engagement summary + terminal findings at terminal."""
        if self._memory_persisted:
            return
        eng = mr_robot.ARC.require_engagement(self.box_name)
        findings = mr_robot.ARC.list_findings(eng["id"])
        tasks = mr_robot.ARC.list_tasks(eng["id"])
        fp = memory.compute_fingerprint(findings)
        summary = self._build_summary(eng, findings, tasks, fp)
        memory.MEMORY.record_engagement(summary)
        terminal = [f for f in findings
                    if f["type"] in memory.Memory.HIGH_CONF_TYPES
                    and f["confidence"] == "confirmed"]
        for f in terminal:
            memory.MEMORY.record_finding(f, fp)
        if memory.MEMORY.available:
            self._log(f"memory: recorded engagement summary + "
                      f"{len(terminal)} finding(s)")
        self._memory_persisted = True

    @staticmethod
    def _build_summary(eng: dict, findings: list, tasks: list,
                       fp: "memory.Fingerprint") -> dict:
        started = eng["created_at"]
        flag_at = {(f.get("data") or {}).get("which"): f["created_at"]
                   for f in findings if f["type"] == "flag"}
        active = any(t["status"] in ("ready", "in_progress") for t in tasks)
        if eng["flag_user"] and eng["flag_root"]:
            outcome = "complete"
        elif not active:
            outcome = "exhausted"
        else:
            outcome = "aborted"
        return {
            "box_name": eng["box_name"],
            "fingerprint": fp.as_text(),
            "open_ports": list(fp.ports),
            "services": list(fp.services),
            "web_tech": list(fp.web_tech),
            "outcome": outcome,
            "time_to_user": (flag_at["user"] - started
                             if flag_at.get("user") else None),
            "time_to_root": (flag_at["root"] - started
                             if flag_at.get("root") else None),
            "dead_end_tasks": [t["summary"] for t in tasks
                               if t["status"] == "dead_end"],
            "terminal_findings": [
                {"type": f["type"], "data": f["data"],
                 "hat": f["source_hat"]}
                for f in findings
                if f["type"] in memory.Memory.HIGH_CONF_TYPES
                and f["confidence"] == "confirmed"
            ],
        }

    def _reap(self) -> None:
        for rid in [rid for rid, t in self._running.items() if t.done()]:
            self._running.pop(rid)

    def _dispatch(self, plan, board: list) -> None:
        needed_hats = {t["hat"] for t in board
                       if t["status"] in ("ready", "in_progress")}
        for task, hat in plan.assign:
            cur = mr_robot.ARC.get_task(task["id"])
            if not cur or cur["status"] != "ready":
                continue                       # claimed/changed since read
            robot = self._acquire(hat, needed_hats)
            if robot is None:
                continue                       # pool saturated — wait
            self._launch(robot, cur)

    def _launch(self, robot, task: dict) -> None:
        robot.status = "working"
        robot.current_task = task["id"]
        self._log(f"  {robot.id}  ->  #{task['id']} {task['summary'][:52]}")
        self._running[robot.id] = asyncio.create_task(robot.run_task(task))

    def _terminal(self, eng: dict, board: list) -> bool:
        if eng["flag_user"] and eng["flag_root"]:
            self._log("[*] both flags captured")
            return True
        active = any(t["status"] in ("ready", "in_progress") for t in board)
        if not active and not self._running:
            self._log("[*] board drained — no actionable work")
            return True
        return False

    async def _drain(self) -> None:
        if self._running:
            await asyncio.gather(*self._running.values(),
                                 return_exceptions=True)

    # --- output ------------------------------------------------------------
    def _log(self, msg: str) -> None:
        print(f"[t{self.tick:>3}] {msg}", flush=True)

    def _report(self) -> None:
        eng = mr_robot.ARC.require_engagement(self.box_name)
        print("\n" + mr_robot.engagement_status(self.box_name))
        print(f"\nrobots: {len(self.robots)} active / {self._spawned} spawned"
              f"   ticks: {self.tick}   "
              f"flags: user={'Y' if eng['flag_user'] else 'N'} "
              f"root={'Y' if eng['flag_root'] else 'N'}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Mr. Robot orchestrator")
    ap.add_argument("box_name")
    ap.add_argument("box_ip")
    ap.add_argument("--mock", action="store_true",
                    help="use deterministic MockRobots (no LLM, no real tools)")
    ap.add_argument("--pool", type=int, default=4, help="robot pool size")
    ap.add_argument("--heartbeat", type=float, default=0.5)
    ap.add_argument("--model", default="claude-sonnet-4-6",
                    help="model for AgentRobots")
    args = ap.parse_args()
    orch = Orchestrator(args.box_name, args.box_ip, pool_size=args.pool,
                        mock=args.mock, heartbeat=args.heartbeat,
                        model=args.model)
    try:
        asyncio.run(orch.run())
    except KeyboardInterrupt:
        print("\ninterrupted")
        sys.exit(130)


if __name__ == "__main__":
    main()
