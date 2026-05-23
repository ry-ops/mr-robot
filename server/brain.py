"""The brain — Mr. Robot's direction judgment (ADR-0013).

v0.1 is heuristic: deterministic rules over the board state — fast, predictable,
zero token cost. The LLM judgment step plugs into the same `decide()` interface
(see the seam in `decide`), so the orchestrator never needs to know which brain
it is talking to.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Plan:
    """The brain's output for one heartbeat."""
    assign: list = field(default_factory=list)     # [(task, hat)], priority order
    reinforce: list = field(default_factory=list)  # [task_id] — gang up
    note: str = ""                                 # the direction call, in words


class HeuristicBrain:
    """Deterministic direction logic."""

    name = "heuristic"
    HIGH = 90  # priority at/above which a task counts as high-value

    def decide(self, board: list[dict], robots: list,
               recollections: dict | None = None) -> Plan:
        """Choose direction for one heartbeat.

        `recollections` is the orchestrator's memory-layer snapshot per
        ADR-0014: `{'triage': [Recollection], 'blockers': {task_id:
        [Recollection]}, 'fingerprint': Fingerprint}`. The heuristic brain
        ignores it; the LLM brain consumes it as additional context.
        """
        del recollections  # heuristic brain doesn't read memory
        ready = sorted((t for t in board if t["status"] == "ready"),
                       key=lambda t: -t["priority"])
        in_progress = [t for t in board if t["status"] == "in_progress"]

        plan = Plan(assign=[(t, t["hat"]) for t in ready])
        plan.note = self._direction(ready, in_progress)

        # --- LLM seam ----------------------------------------------------
        # A future LLMBrain.decide() replaces the logic above: hand the
        # board, robot states, AND recollections to a Claude reasoning step
        # and parse back the assign / reinforce plan. Same return type — the
        # orchestrator is agnostic to which brain produced it.
        return plan

    def _direction(self, ready: list, in_progress: list) -> str:
        """The visible 'choose the direction' call — assist vs. gang up."""
        if not ready and not in_progress:
            return "idle — no actionable work"
        hot = [t for t in ready if t["priority"] >= self.HIGH]
        if len(ready) <= 1 and in_progress:
            return "GANG UP — single front, converge robots"
        if hot:
            return (f"ASSIST — {len(ready)} fronts, "
                    f"{len(hot)} high-value in focus")
        return f"ASSIST — spread across {len(ready)} fronts"
