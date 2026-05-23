"""The Arcade — shared findings store + task board (ADR-0012).

One SQLite database holds every engagement's findings, tasks and robots. All
access goes through the Arcade class, which serialises operations behind a lock
so parallel robots can never race (per ADR-0012). One DB, engagement-scoped
rows — resolving ADR-0012's open question that way for v0.1.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS engagement (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    box_name    TEXT UNIQUE NOT NULL,
    box_ip      TEXT NOT NULL,
    playbook    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',
    flag_user   TEXT,
    flag_root   TEXT,
    created_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS finding (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    engagement_id INTEGER NOT NULL,
    type          TEXT NOT NULL,
    data          TEXT NOT NULL,
    confidence    TEXT NOT NULL DEFAULT 'confirmed',
    source_hat    TEXT,
    source_robot  TEXT,
    created_at    REAL NOT NULL,
    UNIQUE(engagement_id, type, data)
);
CREATE TABLE IF NOT EXISTS task (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    engagement_id INTEGER NOT NULL,
    type          TEXT NOT NULL,
    summary       TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'ready',
    priority      INTEGER NOT NULL DEFAULT 50,
    hat           TEXT,
    depends_on    TEXT,
    produces      TEXT,
    produced      TEXT,
    claimed_by    TEXT,
    created_by    TEXT,
    created_at    REAL NOT NULL,
    UNIQUE(engagement_id, type, summary)
);
CREATE TABLE IF NOT EXISTS robot (
    id            TEXT NOT NULL,
    engagement_id INTEGER NOT NULL,
    hat           TEXT NOT NULL,
    current_task  INTEGER,
    status        TEXT NOT NULL DEFAULT 'idle',
    blocker       TEXT,
    heartbeat_at  REAL,
    PRIMARY KEY (engagement_id, id)
);
"""


def finding_matches(finding: dict, predicate: dict | None) -> bool:
    """True if `finding` satisfies a predicate {type, match:{field: value|list}}."""
    if not predicate:
        return True
    if predicate.get("type") and finding.get("type") != predicate["type"]:
        return False
    data = finding.get("data") or {}
    for field, want in (predicate.get("match") or {}).items():
        have = data.get(field)
        if isinstance(want, list):
            if have not in want:
                return False
        elif have != want:
            return False
    return True


class Arcade:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ----- engagements -----------------------------------------------------
    def start_engagement(self, box_name: str, box_ip: str, playbook: str) -> dict:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO engagement(box_name,box_ip,playbook,created_at) "
                    "VALUES(?,?,?,?)",
                    (box_name, box_ip, playbook, time.time()),
                )
                self._conn.commit()
            except sqlite3.IntegrityError:
                raise ValueError(f"engagement '{box_name}' already exists")
        return self.get_engagement(box_name)

    def get_engagement(self, box_name: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM engagement WHERE box_name=?", (box_name,)
            ).fetchone()
        return dict(row) if row else None

    def require_engagement(self, box_name: str) -> dict:
        eng = self.get_engagement(box_name)
        if not eng:
            raise ValueError(
                f"no engagement '{box_name}' — call engagement_start first"
            )
        return eng

    def list_engagements(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM engagement ORDER BY id"
            ).fetchall()
        return [dict(r) for r in rows]

    def set_flag(self, eng_id: int, which: str, value: str) -> None:
        col = "flag_user" if which == "user" else "flag_root"
        with self._lock:
            self._conn.execute(
                f"UPDATE engagement SET {col}=? WHERE id=?", (value, eng_id)
            )
            self._conn.commit()

    # ----- findings --------------------------------------------------------
    def post_finding(self, eng_id: int, ftype: str, data: dict,
                     confidence: str = "confirmed", source_hat: str | None = None,
                     source_robot: str | None = None) -> tuple[dict, bool]:
        """Insert a finding. Returns (finding, created). Dedupes on (type, data)."""
        data_json = json.dumps(data, sort_keys=True)
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM finding WHERE engagement_id=? AND type=? AND data=?",
                (eng_id, ftype, data_json),
            ).fetchone()
            if row:
                return self._finding(row), False
            cur = self._conn.execute(
                "INSERT INTO finding(engagement_id,type,data,confidence,"
                "source_hat,source_robot,created_at) VALUES(?,?,?,?,?,?,?)",
                (eng_id, ftype, data_json, confidence, source_hat,
                 source_robot, time.time()),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM finding WHERE id=?", (cur.lastrowid,)
            ).fetchone()
        return self._finding(row), True

    def list_findings(self, eng_id: int, ftype: str | None = None) -> list[dict]:
        with self._lock:
            if ftype:
                rows = self._conn.execute(
                    "SELECT * FROM finding WHERE engagement_id=? AND type=? "
                    "ORDER BY id", (eng_id, ftype),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM finding WHERE engagement_id=? ORDER BY id",
                    (eng_id,),
                ).fetchall()
        return [self._finding(r) for r in rows]

    @staticmethod
    def _finding(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["data"] = json.loads(d["data"])
        return d

    # ----- tasks -----------------------------------------------------------
    def add_task(self, eng_id: int, ttype: str, summary: str, priority: int = 50,
                 hat: str | None = None, depends_on: dict | None = None,
                 produces: list | None = None,
                 created_by: str = "rule") -> tuple[dict | None, bool]:
        """Add a task. Returns (task, created). Identical tasks are skipped."""
        status = "blocked" if depends_on else "ready"
        with self._lock:
            try:
                cur = self._conn.execute(
                    "INSERT INTO task(engagement_id,type,summary,status,priority,"
                    "hat,depends_on,produces,produced,created_by,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (eng_id, ttype, summary, status, priority, hat,
                     json.dumps(depends_on) if depends_on else None,
                     json.dumps(produces or []), json.dumps([]),
                     created_by, time.time()),
                )
                self._conn.commit()
            except sqlite3.IntegrityError:
                return None, False
            row = self._conn.execute(
                "SELECT * FROM task WHERE id=?", (cur.lastrowid,)
            ).fetchone()
        return self._task(row), True

    def get_task(self, tid: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM task WHERE id=?", (tid,)
            ).fetchone()
        return self._task(row) if row else None

    def list_tasks(self, eng_id: int, status: str | None = None) -> list[dict]:
        with self._lock:
            if status:
                rows = self._conn.execute(
                    "SELECT * FROM task WHERE engagement_id=? AND status=? "
                    "ORDER BY priority DESC, id", (eng_id, status),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM task WHERE engagement_id=? "
                    "ORDER BY priority DESC, id", (eng_id,),
                ).fetchall()
        return [self._task(r) for r in rows]

    @staticmethod
    def _task(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["depends_on"] = json.loads(d["depends_on"]) if d["depends_on"] else None
        d["produces"] = json.loads(d["produces"]) if d["produces"] else []
        d["produced"] = json.loads(d["produced"]) if d["produced"] else []
        return d

    def claim_task(self, tid: int, robot: str) -> dict:
        task = self.get_task(tid)
        if not task:
            raise ValueError(f"no task #{tid}")
        if task["status"] not in ("ready", "in_progress"):
            raise ValueError(f"task #{tid} is '{task['status']}', not claimable")
        if task["claimed_by"] and task["claimed_by"] != robot:
            raise ValueError(
                f"task #{tid} already claimed by {task['claimed_by']}"
            )
        with self._lock:
            self._conn.execute(
                "UPDATE task SET status='in_progress', claimed_by=? WHERE id=?",
                (robot, tid),
            )
            self._conn.commit()
        return self.get_task(tid)

    def complete_task(self, tid: int, produced: list | None = None) -> dict:
        if not self.get_task(tid):
            raise ValueError(f"no task #{tid}")
        with self._lock:
            self._conn.execute(
                "UPDATE task SET status='done', produced=? WHERE id=?",
                (json.dumps(produced or []), tid),
            )
            self._conn.commit()
        return self.get_task(tid)

    def mark_dead_end(self, tid: int) -> dict:
        if not self.get_task(tid):
            raise ValueError(f"no task #{tid}")
        with self._lock:
            self._conn.execute(
                "UPDATE task SET status='dead_end' WHERE id=?", (tid,)
            )
            self._conn.commit()
        return self.get_task(tid)

    def report_blocker(self, tid: int, need: str, resolved_by: dict | None) -> dict:
        """Block a task on a finding predicate. It auto-unblocks via
        reevaluate_blocked() once a matching finding lands."""
        if not self.get_task(tid):
            raise ValueError(f"no task #{tid}")
        with self._lock:
            self._conn.execute(
                "UPDATE task SET status='blocked', depends_on=? WHERE id=?",
                (json.dumps(resolved_by) if resolved_by else None, tid),
            )
            self._conn.commit()
        return {"need": need, "resolved_by": resolved_by}

    def reevaluate_blocked(self, eng_id: int) -> list[dict]:
        """Flip blocked tasks to ready when their depends_on is satisfied."""
        findings = self.list_findings(eng_id)
        unlocked: list[dict] = []
        for task in self.list_tasks(eng_id, status="blocked"):
            pred = task["depends_on"]
            if pred and any(finding_matches(f, pred) for f in findings):
                with self._lock:
                    self._conn.execute(
                        "UPDATE task SET status='ready' WHERE id=?", (task["id"],)
                    )
                    self._conn.commit()
                unlocked.append(self.get_task(task["id"]))
        return unlocked
