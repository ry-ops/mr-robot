"""Hat registry — loads the Hat personas from the ADR files.

Each Hat ADR (ADR-0001..0011) carries YAML frontmatter describing the persona
along the intent / ethics / behavior axes. A robot runs as exactly one Hat;
the playbook assigns Hats to tasks. The canonical key is the filename slug,
e.g. ADR-0001-white-hat.md -> "white-hat".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_SLUG = re.compile(r"ADR-\d+-(.+)\.md$")


@dataclass
class Hat:
    key: str            # filename slug, e.g. "white-hat"
    title: str
    color: str
    klass: str          # "Individual Hat" | "Team"
    posture: str
    authorization: str
    status: str
    adr: str
    path: str


def _slug(path: Path) -> str:
    m = _SLUG.match(path.name)
    return m.group(1) if m else path.stem


def load_hats(adr_dir: str | Path) -> dict[str, Hat]:
    """Return {slug: Hat} for every Hat ADR found in `adr_dir`."""
    adr_dir = Path(adr_dir)
    hats: dict[str, Hat] = {}
    if not adr_dir.is_dir():
        return hats
    for path in sorted(adr_dir.glob("ADR-*.md")):
        text = path.read_text(encoding="utf-8")
        m = _FRONTMATTER.match(text)
        if not m:
            continue
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            continue
        # a Hat ADR has a `hat` field and class Individual Hat / Team
        if not fm.get("hat") or fm.get("class") not in ("Individual Hat", "Team"):
            continue
        key = _slug(path)
        hats[key] = Hat(
            key=key,
            title=str(fm.get("title", key)),
            color=str(fm.get("color", "")),
            klass=str(fm.get("class", "")),
            posture=str(fm.get("posture", "")),
            authorization=str(fm.get("authorization", "")),
            status=str(fm.get("status", "")),
            adr=str(fm.get("adr", "")),
            path=str(path),
        )
    return hats
