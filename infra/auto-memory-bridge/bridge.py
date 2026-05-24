#!/usr/bin/env python3
"""auto-memory → aiana bridge.

Watches ~/.claude/projects/*/memory/*.md (Claude Code's auto-memory
directory) and mirrors each file into aiana as a Session + Message. The
destination DB is shared with the local user's aiana install via a
volume mount.

Idempotent: session IDs are derived from project + slug + sha256(body),
so an unchanged file produces no new session, and a content change
produces a *new* versioned session (history preserved, latest wins on
slug at read time).

Run modes:
- normal — inotify (Observer). Best on Linux when the watched dir is
  on a native FS.
- polling — BRIDGE_POLLING=1. Use when the watched dir is a bind-mount
  whose inotify events don't reach the container (some Docker setups).

Env:
- CLAUDE_PROJECTS_DIR  (default /claude/projects)
- AIANA_DB_PATH        (default /aiana/conversations.db)
- BRIDGE_POLL_INTERVAL (default 2.0 seconds, polling mode only)
- BRIDGE_POLLING       set non-empty to force polling
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml
from aiana.config import load_config
from aiana.models import Message, MessageType, Session
from aiana.storage import AianaStorage
from watchdog.events import FileSystemEventHandler

if os.environ.get("BRIDGE_POLLING"):
    from watchdog.observers.polling import PollingObserver as Observer
else:
    from watchdog.observers import Observer


PROJECTS_DIR = Path(os.environ.get("CLAUDE_PROJECTS_DIR",
                                   "/claude/projects"))
DB_PATH = os.environ.get("AIANA_DB_PATH", "/aiana/conversations.db")
POLL_INTERVAL = float(os.environ.get("BRIDGE_POLL_INTERVAL", "2"))
MEMORY_GLOB = "*/memory/*.md"

# Match files under any project's memory/ directory, excluding the
# MEMORY.md index (it's a pointer file, not a memory entry).
MEMORY_FILE_RE = re.compile(r".*/memory/(?!MEMORY\.md$)[^/]+\.md$")


def make_storage() -> AianaStorage:
    cfg = load_config()
    cfg.storage.path = DB_PATH
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    return AianaStorage(cfg)


def parse_memory_file(path: Path) -> tuple[dict, str] | None:
    """Return (frontmatter, body) or None if frontmatter is missing /
    invalid. Auto-memory format is `---\\n<yaml>\\n---\\n<body>`."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not text.startswith("---\n"):
        return None
    try:
        _, frontmatter_text, body = text.split("---\n", 2)
    except ValueError:
        return None
    try:
        fm = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(fm, dict):
        return None
    return fm, body.lstrip("\n")


def session_id_for(project: str, slug: str, body: str) -> str:
    """Deterministic ID. Same project+slug+body → same ID (idempotency).
    Body change → new ID (versioning)."""
    sha8 = hashlib.sha256(body.encode("utf-8")).hexdigest()[:8]
    raw = f"auto-memory|{project}|{slug}|{sha8}"
    return f"auto-memory-{uuid.uuid5(uuid.NAMESPACE_OID, raw)}"


def project_from_path(path: Path) -> str:
    """`<projects>/<project-key>/memory/<file>.md` → `<project-key>`."""
    try:
        parts = path.relative_to(PROJECTS_DIR).parts
    except ValueError:
        return "unknown"
    return parts[0] if parts else "unknown"


def sync_file(storage: AianaStorage, path: Path) -> str:
    """Write the file's current content to aiana if not already present.
    Returns 'wrote', 'skipped', 'invalid', or 'failed'."""
    parsed = parse_memory_file(path)
    if parsed is None:
        return "invalid"
    fm, body = parsed
    slug = str(fm.get("name") or path.stem)
    description = str(fm.get("description") or "")
    mem_type = str((fm.get("metadata") or {}).get("type") or "unknown")
    project = project_from_path(path)
    sid = session_id_for(project, slug, body)

    try:
        existing = storage.get_session(sid)
    except Exception:
        existing = None
    if existing is not None:
        return "skipped"

    now = datetime.now(timezone.utc)
    sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    meta = {
        "kind": "auto-memory",
        "type": mem_type,
        "project": project,
        "slug": slug,
        "source_path": str(path),
        "source_sha256": sha,
    }
    try:
        storage.create_session(Session(
            id=sid,
            project_path=f"auto-memory/{project}",
            transcript_path=f"auto-memory://{project}/{slug}",
            started_at=now,
            metadata=meta,
        ))
        storage.append_message(Message(
            id=str(uuid.uuid4()),
            session_id=sid,
            type=MessageType.SYSTEM,
            content=body,
            timestamp=now,
            metadata=meta,
        ))
        storage.end_session(sid, summary=description or slug)
    except Exception as exc:
        print(f"[bridge] write failed for {path}: {exc}",
              file=sys.stderr, flush=True)
        return "failed"
    return "wrote"


def initial_sync(storage: AianaStorage) -> None:
    n_wrote = n_skipped = n_invalid = n_failed = 0
    for path in sorted(PROJECTS_DIR.glob(MEMORY_GLOB)):
        if path.name == "MEMORY.md":
            continue
        result = sync_file(storage, path)
        if result == "wrote":
            n_wrote += 1
        elif result == "skipped":
            n_skipped += 1
        elif result == "invalid":
            n_invalid += 1
        else:
            n_failed += 1
    print(f"[bridge] initial sync: wrote={n_wrote} skipped={n_skipped} "
          f"invalid={n_invalid} failed={n_failed}", flush=True)


class MemoryHandler(FileSystemEventHandler):
    def __init__(self, storage: AianaStorage) -> None:
        self.storage = storage

    def _handle(self, src_path: str) -> None:
        path = Path(src_path)
        if path.name == "MEMORY.md":
            return
        if not MEMORY_FILE_RE.match(str(path)):
            return
        if not path.exists():
            return
        result = sync_file(self.storage, path)
        print(f"[bridge] {result}: {path}", flush=True)

    def on_created(self, event) -> None:
        if event.is_directory:
            return
        self._handle(event.src_path)

    def on_modified(self, event) -> None:
        if event.is_directory:
            return
        self._handle(event.src_path)


def main() -> None:
    mode = "polling" if os.environ.get("BRIDGE_POLLING") else "inotify"
    print(f"[bridge] starting — projects={PROJECTS_DIR} db={DB_PATH} "
          f"mode={mode}", flush=True)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    storage = make_storage()
    initial_sync(storage)
    obs_kwargs = {"timeout": POLL_INTERVAL} if mode == "polling" else {}
    observer = Observer(**obs_kwargs)
    observer.schedule(MemoryHandler(storage), str(PROJECTS_DIR),
                      recursive=True)
    observer.start()
    print("[bridge] watching for changes", flush=True)
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
