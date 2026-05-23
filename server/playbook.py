"""Playbook engine — loads unlock rules and turns findings into tasks (ADR-0012).

A playbook is declarative YAML (see ~/playbooks/htb-default.yaml): `seeds`
created at engagement start, and `rules` whose `on` predicate, when matched by
a posted finding, `spawn` new task templates onto the board.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class TaskTemplate:
    type: str
    summary: str
    priority: int = 50
    hat: str | None = None
    depends_on: dict | None = None
    produces: list = field(default_factory=list)
    tools: list = field(default_factory=list)


@dataclass
class Rule:
    id: str
    when: dict
    spawn: list  # list[TaskTemplate]


def _template(d: dict) -> TaskTemplate:
    return TaskTemplate(
        type=str(d.get("task", "task")),
        summary=str(d.get("summary", "")),
        priority=int(d.get("priority", 50)),
        hat=d.get("hat"),
        depends_on=d.get("depends_on"),
        produces=list(d.get("produces") or []),
        tools=list(d.get("tools") or []),
    )


def _on_matches(finding: dict, on: dict) -> bool:
    if on.get("type") and finding.get("type") != on["type"]:
        return False
    data = finding.get("data") or {}
    for fld, want in (on.get("match") or {}).items():
        have = data.get(fld)
        if isinstance(want, list):
            if have not in want:
                return False
        elif have != want:
            return False
    return True


_INTERP = re.compile(r"\{([a-zA-Z0-9_.]+)\}")


def render(text: str, engagement: dict, finding: dict | None = None) -> str:
    """Interpolate {box_ip}, {box_name}, {data.<field>} into a template string."""
    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key == "box_ip":
            return str(engagement.get("box_ip", ""))
        if key == "box_name":
            return str(engagement.get("box_name", ""))
        if key.startswith("data.") and finding:
            return str((finding.get("data") or {}).get(key[5:], m.group(0)))
        return m.group(0)
    return _INTERP.sub(sub, text or "")


class Playbook:
    def __init__(self, name: str, seeds: list, rules: list, path: str):
        self.name = name
        self.seeds = seeds  # list[TaskTemplate]
        self.rules = rules  # list[Rule]
        self.path = path

    @classmethod
    def load(cls, path: str | Path) -> "Playbook":
        path = Path(path)
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        seeds = [_template(t) for t in (doc.get("seeds") or [])]
        rules = [
            Rule(
                id=str(r.get("id", "?")),
                when=r.get("when") or {},
                spawn=[_template(t) for t in (r.get("spawn") or [])],
            )
            for r in (doc.get("rules") or [])
        ]
        return cls(str(doc.get("playbook", path.stem)), seeds, rules, str(path))

    def match(self, finding: dict) -> list[tuple[str, TaskTemplate]]:
        """Return [(rule_id, template)] for every rule whose `on` matches."""
        out: list[tuple[str, TaskTemplate]] = []
        for rule in self.rules:
            if _on_matches(finding, rule.when):
                for tmpl in rule.spawn:
                    out.append((rule.id, tmpl))
        return out
