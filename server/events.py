"""Engagement lifecycle event bus (ADR-0016).

Per-orchestrator dispatcher. Subscribers attach in `__init__`; events fire
from the control loop at named lifecycle points. The bus decouples
terminal-state work (memory persistence, reporting, future co-op share,
future htb-research enrichment) from `Orchestrator.run()`.

Subscriber exceptions are logged but never propagate — one bad subscriber
must not break the control loop.

Events emitted by the orchestrator (v1):
- engagement_started(engagement)  — once, after the engagement row exists
  and before the first tick.
- engagement_ended(engagement)    — once, after the loop drains and before
  `run()` returns. Fires regardless of outcome (complete, exhausted,
  aborted, budget-exhausted).
"""
from __future__ import annotations

import sys
from typing import Any, Callable


class EventBus:
    """Minimal in-process pub/sub.

    Per-orchestrator, not a process singleton — two orchestrators in the
    same process get two buses, so their subscribers do not collide.
    """

    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[..., Any]]] = {}

    def subscribe(self, event: str, fn: Callable[..., Any]) -> None:
        self._subs.setdefault(event, []).append(fn)

    def emit(self, event: str, **payload: Any) -> None:
        for fn in self._subs.get(event, []):
            try:
                fn(**payload)
            except Exception as exc:
                name = getattr(fn, "__name__", repr(fn))
                print(f"[events] subscriber {name!s} on '{event}' "
                      f"failed: {exc}", file=sys.stderr)
