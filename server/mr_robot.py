#!/usr/bin/env python3
"""Mr. Robot — an MCP server for orchestrated HackTheBox engagements.

v0.1, the "arsenal" layer: the arcade (findings store + task board), the
playbook engine, the Hat registry, the scope guard, and one scope-checked
recon tool. The orchestrator / robot-spawning layer comes later.

See ~/Mr. Robot/adr/ for the design.
"""
from __future__ import annotations

import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from mcp.server.fastmcp import FastMCP

import scope
from arcade import Arcade
from hats import load_hats
from memory import MEMORY
from playbook import Playbook, render

# --- paths --------------------------------------------------------------
HOME = Path(os.environ.get("MR_ROBOT_HOME",
                           Path(__file__).resolve().parent.parent))
ADR_DIR = HOME / "adr"
PLAYBOOK_DIR = Path(os.environ.get("MR_ROBOT_PLAYBOOKS",
                                   Path.home() / "playbooks"))
ENGAGE_DIR = Path(os.environ.get("MR_ROBOT_ENGAGEMENTS",
                                 HOME / "engagements"))
DB_PATH = ENGAGE_DIR / "arcade.db"

ENGAGE_DIR.mkdir(parents=True, exist_ok=True)

# --- wiring -------------------------------------------------------------
mcp = FastMCP("mr-robot")
ARC = Arcade(DB_PATH)
HATS = load_hats(ADR_DIR)


def _playbook(name: str) -> Playbook:
    path = PLAYBOOK_DIR / f"{name}.yaml"
    if not path.exists():
        raise ValueError(f"playbook '{name}' not found at {path}")
    return Playbook.load(path)


def _apply_unlock(eng: dict, finding: dict, pb: Playbook) -> tuple[list, list]:
    """Run the playbook against a new finding. Returns (spawned, unlocked)."""
    spawned = []
    for rule_id, tmpl in pb.match(finding):
        task, created = ARC.add_task(
            eng["id"], tmpl.type, render(tmpl.summary, eng, finding),
            priority=tmpl.priority, hat=tmpl.hat,
            depends_on=tmpl.depends_on, produces=tmpl.produces,
            created_by=f"rule:{rule_id}",
        )
        if created:
            spawned.append(task)
    unlocked = ARC.reevaluate_blocked(eng["id"])
    return spawned, unlocked


def _fmt_task(t: dict) -> str:
    return (f"  #{t['id']:>3} [{t['status']:^11}] p{t['priority']:>3} "
            f"{t['summary']}  (hat:{t['hat']})")


# --- tools : engagement -------------------------------------------------
@mcp.tool()
def engagement_start(box_name: str, box_ip: str,
                     playbook: str = "htb-default") -> str:
    """Start an engagement against a box. Creates the arcade workspace, locks
    scope to box_ip, loads the playbook, and seeds the task board."""
    try:
        pb = _playbook(playbook)
        eng = ARC.start_engagement(box_name, box_ip, playbook)
    except Exception as exc:
        return f"X {exc}"
    (ENGAGE_DIR / box_name / "loot").mkdir(parents=True, exist_ok=True)
    seeded = []
    for tmpl in pb.seeds:
        task, created = ARC.add_task(
            eng["id"], tmpl.type, render(tmpl.summary, eng, None),
            priority=tmpl.priority, hat=tmpl.hat,
            depends_on=tmpl.depends_on, produces=tmpl.produces,
            created_by="seed",
        )
        if created:
            seeded.append(task)
    lines = [f">> engagement '{box_name}' started — scope locked to {box_ip}",
             f"   playbook: {pb.name}   workspace: {ENGAGE_DIR / box_name}",
             f"   seeded {len(seeded)} task(s):"]
    lines += [_fmt_task(t) for t in seeded]
    return "\n".join(lines)


@mcp.tool()
def engagement_status(box_name: str = "") -> str:
    """Show an engagement's task board, or list all engagements if box_name
    is omitted."""
    try:
        if not box_name:
            engs = ARC.list_engagements()
            if not engs:
                return "(no engagements yet — call engagement_start)"
            return "\n".join(
                f"- {e['box_name']}  ({e['box_ip']})  status={e['status']}  "
                f"flags[user={'Y' if e['flag_user'] else '-'} "
                f"root={'Y' if e['flag_root'] else '-'}]" for e in engs)
        eng = ARC.require_engagement(box_name)
    except Exception as exc:
        return f"X {exc}"
    findings = ARC.list_findings(eng["id"])
    tasks = ARC.list_tasks(eng["id"])
    lines = [f">> {box_name}  ({eng['box_ip']})  status={eng['status']}",
             f"   flags: user={eng['flag_user'] or '-'}  "
             f"root={eng['flag_root'] or '-'}",
             f"   findings: {len(findings)}   tasks: {len(tasks)}",
             "-- task board --"]
    for status in ("ready", "in_progress", "blocked", "done", "dead_end"):
        for t in [x for x in tasks if x["status"] == status]:
            lines.append(_fmt_task(t))
    return "\n".join(lines)


# --- tools : arcade -----------------------------------------------------
@mcp.tool()
def arcade_post_finding(box_name: str, type: str, data: dict,
                        confidence: str = "confirmed", source_hat: str = "",
                        source_robot: str = "") -> str:
    """Post a finding to the arcade and fire the playbook's unlock rules.
    `type` is one of: port, service, web_path, credential, cve, foothold,
    privesc_vector, flag. A `flag` finding records the engagement flag."""
    try:
        eng = ARC.require_engagement(box_name)
        pb = _playbook(eng["playbook"])
        finding, created = ARC.post_finding(
            eng["id"], type, data, confidence,
            source_hat or None, source_robot or None)
        if not created:
            return f"~ duplicate {type} finding — already on board as #{finding['id']}"
        if type == "flag":
            ARC.set_flag(eng["id"], data.get("which", "user"),
                         str(data.get("value", "captured")))
        spawned, unlocked = _apply_unlock(eng, finding, pb)
        lines = [f"+ finding #{finding['id']} posted: {type} {data}"]
        if spawned:
            lines.append(f"  unlocked {len(spawned)} task(s):")
            lines += [_fmt_task(t) for t in spawned]
        if unlocked:
            lines.append(f"  {len(unlocked)} blocked task(s) became ready:")
            lines += [_fmt_task(t) for t in unlocked]
        if not spawned and not unlocked:
            lines.append("  (no rules matched — no new tasks)")
        return "\n".join(lines)
    except Exception as exc:
        return f"X {exc}"


@mcp.tool()
def arcade_list_tasks(box_name: str, status: str = "") -> str:
    """List tasks on the board, optionally filtered by status
    (ready, in_progress, blocked, done, dead_end)."""
    try:
        eng = ARC.require_engagement(box_name)
        tasks = ARC.list_tasks(eng["id"], status or None)
    except Exception as exc:
        return f"X {exc}"
    if not tasks:
        return f"(no tasks{' with status ' + status if status else ''})"
    out = []
    for t in tasks:
        extra = f"  @{t['claimed_by']}" if t["claimed_by"] else ""
        if t["depends_on"]:
            extra += f"  needs:{t['depends_on']}"
        out.append(_fmt_task(t) + extra)
    return "\n".join(out)


@mcp.tool()
def arcade_claim_task(box_name: str, task_id: int, robot: str) -> str:
    """Claim a ready task for a robot — marks it in_progress."""
    try:
        ARC.require_engagement(box_name)
        t = ARC.claim_task(task_id, robot)
        return f"+ task #{t['id']} claimed by {robot} — {t['summary']}"
    except Exception as exc:
        return f"X {exc}"


@mcp.tool()
def arcade_complete_task(box_name: str, task_id: int,
                         produced: list[int] | None = None) -> str:
    """Mark a task done. `produced` is the list of finding IDs it yielded."""
    try:
        ARC.require_engagement(box_name)
        t = ARC.complete_task(task_id, produced or [])
        return f"+ task #{t['id']} done — {t['summary']}"
    except Exception as exc:
        return f"X {exc}"


@mcp.tool()
def arcade_report_blocker(box_name: str, task_id: int, need: str,
                          resolved_by: dict) -> str:
    """Report a task is blocked. `need` is human text; `resolved_by` is a
    finding predicate, e.g. {"type":"credential","match":{"service":"ssh"}}.
    The task auto-unblocks when a matching finding lands."""
    try:
        ARC.require_engagement(box_name)
        ARC.report_blocker(task_id, need, resolved_by)
        return (f"! task #{task_id} blocked — need: {need}\n"
                f"  unblocks when a finding matches: {resolved_by}")
    except Exception as exc:
        return f"X {exc}"


# --- tools : hats -------------------------------------------------------
@mcp.tool()
def list_hats() -> str:
    """List the Hat personas defined by the ADRs."""
    if not HATS:
        return "(no Hat ADRs found)"
    return "\n".join(
        f"ADR-{h.adr}  {h.key:<14} {h.klass:<16} {h.posture}"
        for h in sorted(HATS.values(), key=lambda x: x.adr))


@mcp.tool()
def get_hat(name: str) -> str:
    """Get the full contract for a Hat (e.g. 'white-hat', 'black-hat')."""
    h = HATS.get(name)
    if not h:
        return f"X unknown hat '{name}' — known: {', '.join(sorted(HATS))}"
    return (f"{h.title}  (ADR-{h.adr}, {h.klass})\n"
            f"  color:         {h.color}\n"
            f"  posture:       {h.posture}\n"
            f"  authorization: {h.authorization}\n"
            f"  status:        {h.status}\n"
            f"  ADR file:      {h.path}")


# --- tools : memory -----------------------------------------------------
@mcp.tool()
def memory_recall_for_task(box_name: str, task_id: int, hat: str,
                           k: int = 5) -> str:
    """Surface past approaches this Hat has tried for similar tasks. Context
    for a robot's planning — not a directive. Returns [] if the memory layer
    is not provisioned (aiana not installed)."""
    try:
        eng = ARC.require_engagement(box_name)
        task = ARC.get_task(task_id)
        if not task or task["engagement_id"] != eng["id"]:
            return f"X no task #{task_id} in engagement '{box_name}'"
    except Exception as exc:
        return f"X {exc}"
    recs = MEMORY.recall_for_task(task, hat, k=k)
    if not recs:
        return ("(no recollections)" if MEMORY.available
                else "(memory layer not provisioned — no recall)")
    return "\n".join(
        f"  [{r.score:.2f}] {r.box_name}  {r.summary}" for r in recs)


@mcp.tool()
def memory_record_task_outcome(box_name: str, task_id: int, hat: str,
                               approach: str, result: str,
                               learned: str = "") -> str:
    """Write a short recollection of this robot's work on this task. Called
    at complete or dead_end. `result` is 'complete' or 'dead_end'. No-op if
    the memory layer is not provisioned."""
    try:
        eng = ARC.require_engagement(box_name)
        task = ARC.get_task(task_id)
        if not task or task["engagement_id"] != eng["id"]:
            return f"X no task #{task_id} in engagement '{box_name}'"
    except Exception as exc:
        return f"X {exc}"
    if result not in ("complete", "dead_end"):
        return f"X result must be 'complete' or 'dead_end', got '{result}'"
    MEMORY.record_task_outcome(
        task, hat,
        {"approach": approach, "result": result, "learned": learned})
    return (f"+ task outcome recorded for #{task_id} ({hat}, {result})"
            if MEMORY.available
            else "~ memory layer not provisioned — outcome dropped")


# --- tools : recon ------------------------------------------------------
def _parse_nmap_xml(xml_text: str) -> list[dict]:
    out: list[dict] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for host in root.findall("host"):
        for port in host.findall("./ports/port"):
            state = port.find("state")
            if state is None or state.get("state") != "open":
                continue
            svc = port.find("service")
            out.append({
                "port": int(port.get("portid")),
                "proto": port.get("protocol") or "tcp",
                "service": (svc.get("name") if svc is not None else None)
                or "unknown",
                "product": (svc.get("product") if svc is not None else "")
                or "",
                "version": (svc.get("version") if svc is not None else "")
                or "",
            })
    return out


@mcp.tool()
def recon_portscan(box_name: str, target: str, top_ports: int = 100) -> str:
    """Scope-checked nmap scan. Resolves `target`, refuses anything outside the
    engagement scope, runs a TCP connect + service scan, and posts the open
    ports/services to the arcade — which unlocks further tasks."""
    try:
        eng = ARC.require_engagement(box_name)
    except Exception as exc:
        return f"X {exc}"
    # the ethics axis: scope enforcement happens before nmap ever runs
    try:
        detail = scope.enforce(target, [eng["box_ip"]])
    except scope.ScopeError as exc:
        return (f"[STOP] {exc}\n"
                f"  recon_portscan refused — target is not in engagement scope.")
    cmd = ["nmap", "-Pn", "-sT", "-T4", "--open", "-sV",
           "--top-ports", str(top_ports), "-oX", "-", target]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return f"X nmap timed out after 600s on {target}"
    except FileNotFoundError:
        return "X nmap not found on PATH"
    if proc.returncode != 0 and not proc.stdout.strip():
        return f"X nmap failed: {proc.stderr.strip()[:300]}"

    ports = _parse_nmap_xml(proc.stdout)
    pb = _playbook(eng["playbook"])
    lines = [f"+ scope check: {detail}",
             f"+ nmap {target} (top {top_ports}) — {len(ports)} open port(s)"]
    spawned: list = []
    for p in ports:
        ARC.post_finding(eng["id"], "port",
                         {"port": p["port"], "proto": p["proto"]},
                         source_hat="script-kiddie", source_robot="recon")
        sdata = {"port": p["port"], "service": p["service"]}
        if p["product"]:
            sdata["product"] = p["product"]
        if p["version"]:
            sdata["version"] = p["version"]
        if p["service"] in ("http", "https", "http-proxy", "http-alt"):
            sproto = "https" if p["service"] == "https" else "http"
            sdata["url"] = f"{sproto}://{target}:{p['port']}/"
        f_svc, created = ARC.post_finding(eng["id"], "service", sdata,
                                          source_hat="script-kiddie",
                                          source_robot="recon")
        lines.append(f"  {p['port']:>5}/{p['proto']:<3} {p['service']:<13}"
                     f"{p['product']} {p['version']}".rstrip())
        if created:
            s, _ = _apply_unlock(eng, f_svc, pb)
            spawned += s
    # close the recon seed task
    for t in ARC.list_tasks(eng["id"]):
        if t["type"] == "recon.portscan" and t["status"] in (
                "ready", "in_progress"):
            ARC.complete_task(t["id"], [])
    if spawned:
        lines.append(f"-- arcade unlocked {len(spawned)} task(s) --")
        lines += [_fmt_task(t) for t in spawned]
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
