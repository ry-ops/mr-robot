"""The memory — cross-engagement recall via aiana (ADR-0014).

A single adapter over aiana, used at both tiers:
- the orchestrator imports `MEMORY` (or `Memory()`) and calls it directly,
- the `mr-robot` MCP server exposes `memory_*` tools backed by the same
  instance, so robots reach the same store without a second MCP server.

If aiana is not installed (or its storage fails to initialise) the adapter
degrades to a no-op — writes are dropped, reads return []. This keeps the
orchestrator and the mock loop working when the memory layer hasn't been
provisioned.

Backends per ADR-0014: SQLite/FTS5 (via aiana), Qdrant for semantic recall,
and Redis as a recall cache. Each backend degrades independently — Qdrant
unavailable → FTS5-only reads; Redis unavailable → no caching, direct reads.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

try:
    from aiana.config import load_config as _aiana_load_config
    from aiana.models import Message, MessageType, Session
    from aiana.storage import AianaStorage
    _AIANA_AVAILABLE = True
except ImportError:
    _AIANA_AVAILABLE = False

try:
    from qdrant_client import QdrantClient
    from qdrant_client import models as qmodels
    _QDRANT_AVAILABLE = True
except ImportError:
    _QDRANT_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer
    _EMBED_AVAILABLE = True
except ImportError:
    _EMBED_AVAILABLE = False

try:
    import redis as _redis
    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False


# --- types ----------------------------------------------------------------

@dataclass(frozen=True)
class Fingerprint:
    """Recall key for a box. Derived from arcade state by `compute_fingerprint`.

    Same arcade state always yields the same fingerprint, so it is a stable
    embedding input and a stable tag for writes.
    """
    os_family: str | None = None
    ports: tuple[int, ...] = ()
    services: tuple[str, ...] = ()
    web_tech: tuple[str, ...] = ()

    def as_text(self) -> str:
        """Flat string suitable as an embedding / FTS input."""
        parts: list[str] = []
        if self.os_family:
            parts.append(f"os:{self.os_family}")
        if self.ports:
            parts.append("ports:" + ",".join(str(p) for p in self.ports))
        if self.services:
            parts.append("svc:" + ",".join(self.services))
        if self.web_tech:
            parts.append("web:" + ",".join(self.web_tech))
        return " ".join(parts) or "(empty)"


@dataclass
class Recollection:
    """One past memory entry returned to a caller. Aiana types do not leak
    past this — callers see Recollection only."""
    box_name: str
    summary: str
    score: float
    tags: dict = field(default_factory=dict)


# --- fingerprint helper ---------------------------------------------------

def compute_fingerprint(findings: list[dict]) -> Fingerprint:
    """Derive a fingerprint from a list of arcade findings.

    Pure function — no arcade coupling. Versions on service banners are
    normalized to major.minor so cosmetic patch differences don't fork
    recall.
    """
    ports: set[int] = set()
    services: set[str] = set()
    web_tech: set[str] = set()
    for f in findings:
        data = f.get("data") or {}
        ftype = f.get("type")
        if ftype == "port":
            try:
                ports.add(int(data["port"]))
            except (KeyError, TypeError, ValueError):
                continue
        elif ftype == "service":
            svc = data.get("service")
            if not svc:
                continue
            token = svc
            product = (data.get("product") or "").strip()
            version = (data.get("version") or "").strip()
            if product:
                token += f":{product}"
            if version:
                token += ":" + ".".join(version.split(".")[:2])
            services.add(token)
        elif ftype == "web_path":
            tech = data.get("tech")
            if tech:
                web_tech.add(str(tech))
    return Fingerprint(
        ports=tuple(sorted(ports)),
        services=tuple(sorted(services)),
        web_tech=tuple(sorted(web_tech)),
    )


# --- the adapter ----------------------------------------------------------

class Memory:
    """Cross-engagement memory adapter (ADR-0014).

    All callers go through this class. Backends: aiana's `AianaStorage`
    (SQLite + FTS5), Qdrant for semantic recall, Redis for read caching.
    Each backend degrades independently.
    """

    HIGH_CONF_TYPES = frozenset({"foothold", "privesc_vector", "flag"})
    KIND_ENGAGEMENT = "engagement"
    KIND_FINDING = "finding"
    KIND_TASK = "task_outcome"

    _QDRANT_VECTOR_SIZE = 384  # all-MiniLM-L6-v2
    _RRF_K = 60                # reciprocal rank fusion constant
    _CACHE_NS = "mrrobot:memory:search:"
    _GEN_KEY = "mrrobot:memory:gen"

    def __init__(self) -> None:
        self.available = False
        self._store = None
        self._qdrant = None
        self._embed = None
        self._collection = os.environ.get(
            "MR_ROBOT_QDRANT_COLLECTION", "mrrobot-memory")
        self._redis = None
        try:
            self._cache_ttl = int(os.environ.get(
                "MR_ROBOT_MEMORY_CACHE_TTL_SECONDS", "600"))
        except ValueError:
            self._cache_ttl = 600
        # Declared deadlines on external calls (ADR-0016).
        try:
            self._qdrant_deadline = int(os.environ.get(
                "MR_ROBOT_QDRANT_DEADLINE_SECONDS", "5"))
        except ValueError:
            self._qdrant_deadline = 5
        try:
            self._redis_deadline = float(os.environ.get(
                "MR_ROBOT_REDIS_DEADLINE_SECONDS", "2"))
        except ValueError:
            self._redis_deadline = 2.0

        if not _AIANA_AVAILABLE:
            return
        try:
            cfg = _aiana_load_config()
            cfg.storage.path = str(Path(cfg.storage.path).expanduser())
            Path(cfg.storage.path).parent.mkdir(parents=True, exist_ok=True)
            self._store = AianaStorage(cfg)
            self.available = True
        except Exception as exc:
            print(f"[memory] aiana init failed: {exc} — running no-op",
                  file=sys.stderr)
            return

        # Qdrant + embedding model — semantic recall. Both must succeed; on
        # any failure we keep the FTS5-only path.
        if _QDRANT_AVAILABLE and _EMBED_AVAILABLE:
            try:
                self._embed = SentenceTransformer("all-MiniLM-L6-v2")
                url = os.environ.get(
                    "MR_ROBOT_QDRANT_URL", "http://localhost:6333")
                self._qdrant = QdrantClient(
                    url=url, timeout=self._qdrant_deadline)
                self._ensure_collection()
            except Exception as exc:
                print(f"[memory] qdrant init failed: {exc} — running without "
                      "semantic recall", file=sys.stderr)
                self._qdrant = None
                self._embed = None
        else:
            missing = []
            if not _QDRANT_AVAILABLE:
                missing.append("qdrant_client")
            if not _EMBED_AVAILABLE:
                missing.append("sentence_transformers")
            print(f"[memory] qdrant init failed: missing {','.join(missing)}"
                  " — running without semantic recall", file=sys.stderr)

        # Redis — recall cache. Optional.
        if _REDIS_AVAILABLE:
            try:
                url = os.environ.get(
                    "MR_ROBOT_REDIS_URL", "redis://localhost:6379/0")
                client = _redis.Redis.from_url(
                    url, decode_responses=True,
                    socket_timeout=self._redis_deadline,
                    socket_connect_timeout=self._redis_deadline,
                )
                client.ping()
                self._redis = client
            except Exception as exc:
                print(f"[memory] redis init failed: {exc} — running without "
                      "recall cache", file=sys.stderr)
                self._redis = None
        else:
            print("[memory] redis init failed: missing redis — running "
                  "without recall cache", file=sys.stderr)

    def _ensure_collection(self) -> None:
        """Create the Qdrant collection if it does not yet exist."""
        existing = {c.name for c in self._qdrant.get_collections().collections}
        if self._collection in existing:
            return
        self._qdrant.create_collection(
            collection_name=self._collection,
            vectors_config=qmodels.VectorParams(
                size=self._QDRANT_VECTOR_SIZE,
                distance=qmodels.Distance.COSINE,
            ),
        )

    # ----- campaign tier (orchestrator, direct import) -------------------

    def recall_similar(self, fingerprint: Fingerprint,
                       k: int = 5) -> list[Recollection]:
        """Past engagements similar to `fingerprint`. Triage-time call."""
        if not self.available:
            return []
        return self._search(fingerprint.as_text(), k,
                            kind_filter=self.KIND_ENGAGEMENT)

    def recall_for_blocker(self, blocker: dict, findings: list[dict],
                           k: int = 5) -> list[Recollection]:
        """Past work matching a structured blocker + current findings.
        Reinforce/repurpose-time call."""
        if not self.available:
            return []
        q = (blocker.get("need") or "").strip() or "(blocker)"
        return self._search(q, k)

    def record_engagement(self, summary: dict) -> None:
        """Write the engagement-end summary. One entry per engagement.

        Expected keys (validated by the writer, not here):
          box_name, fingerprint, services, path_that_worked, dead_ends,
          time_to_user, time_to_root, outcome
        """
        if not self.available:
            return
        box = str(summary.get("box_name") or "unknown")
        fp_text = str(summary.get("fingerprint") or "")
        content = json.dumps(summary, default=str, sort_keys=True)
        self._record(
            kind=self.KIND_ENGAGEMENT, box=box,
            content=content, msg_type=MessageType.SUMMARY,
            extra_meta={"fingerprint": fp_text,
                        "outcome": str(summary.get("outcome") or "")},
            session_summary=fp_text,
        )

    def record_finding(self, finding: dict,
                       fingerprint: Fingerprint) -> None:
        """Write a high-confidence terminal finding tagged with the box's
        fingerprint. Silently ignores findings that don't qualify."""
        if not self.available:
            return
        if finding.get("confidence") != "confirmed":
            return
        if finding.get("type") not in self.HIGH_CONF_TYPES:
            return
        ftype = finding["type"]
        data = finding.get("data") or {}
        # Box is not on the finding — derive from data when possible; else
        # fall back to the fingerprint as a coarse key.
        box = str(data.get("host") or data.get("box") or fingerprint.as_text())
        content = json.dumps(
            {"type": ftype, "data": data,
             "hat": finding.get("source_hat"),
             "robot": finding.get("source_robot"),
             "fingerprint": fingerprint.as_text()},
            default=str, sort_keys=True,
        )
        self._record(
            kind=self.KIND_FINDING, box=box, content=content,
            msg_type=MessageType.SYSTEM,
            extra_meta={"finding_type": ftype,
                        "fingerprint": fingerprint.as_text(),
                        "hat": str(finding.get("source_hat") or "")},
            session_summary=f"{ftype}@{box}",
        )

    # ----- task tier (robots, exposed as MCP tools) ----------------------

    def recall_for_task(self, task: dict, hat: str,
                        k: int = 5) -> list[Recollection]:
        """Past approaches this Hat tried for similar tasks. Robot pickup."""
        if not self.available:
            return []
        q = f"{task.get('type', '')} {task.get('summary', '')} hat:{hat}".strip()
        return self._search(q, k, kind_filter=self.KIND_TASK)

    def record_task_outcome(self, task: dict, hat: str,
                            outcome: dict) -> None:
        """Robot's per-task recollection at complete or dead_end.

        Expected outcome keys (validated by the writer, not here):
          approach, result ('complete'|'dead_end'), learned
        """
        if not self.available:
            return
        ttype = str(task.get("type") or "task")
        content = json.dumps(
            {"task_type": ttype,
             "task_summary": task.get("summary"),
             "hat": hat, "outcome": outcome},
            default=str, sort_keys=True,
        )
        self._record(
            kind=self.KIND_TASK, box=f"task:{ttype}", content=content,
            msg_type=MessageType.SYSTEM,
            extra_meta={"task_type": ttype, "hat": hat,
                        "result": str(outcome.get("result") or "")},
            session_summary=f"{hat}/{ttype}",
        )

    # ----- aiana helpers (private) ---------------------------------------

    def _record(self, *, kind: str, box: str, content: str,
                msg_type: "MessageType", extra_meta: dict | None = None,
                session_summary: str | None = None) -> None:
        """Create a session, append one message, end the session. One
        atomic write from the caller's perspective."""
        now = datetime.now(timezone.utc)
        sid = f"mrrobot-{kind}-{uuid.uuid4()}"
        meta = {"kind": kind, "box": box}
        if extra_meta:
            meta.update(extra_meta)
        try:
            self._store.create_session(Session(
                id=sid,
                project_path=f"mrrobot/{box}",
                transcript_path=f"mrrobot://{kind}/{box}/{sid}",
                started_at=now,
                metadata=meta,
            ))
            self._store.append_message(Message(
                id=str(uuid.uuid4()), session_id=sid, type=msg_type,
                content=content, timestamp=now, metadata=meta,
            ))
            self._store.end_session(sid, summary=session_summary)
        except Exception as exc:
            print(f"[memory] write failed ({kind}/{box}): {exc}",
                  file=sys.stderr)
            return

        # Semantic side-write. Best-effort; FTS5 is the source of truth.
        if self._qdrant is not None and self._embed is not None:
            try:
                vec = self._embed.encode(content).tolist()
                # Stable point ID derived from sid; Qdrant accepts uuid strings.
                point_id = str(uuid.uuid5(uuid.NAMESPACE_OID, sid))
                payload = {
                    "kind": kind,
                    "box": box,
                    "session_id": sid,
                    "snippet": content[:240],
                    "meta": meta,
                }
                if extra_meta and "fingerprint" in extra_meta:
                    payload["fingerprint"] = extra_meta["fingerprint"]
                self._qdrant.upsert(
                    collection_name=self._collection,
                    points=[qmodels.PointStruct(
                        id=point_id, vector=vec, payload=payload)],
                )
            except Exception as exc:
                print(f"[memory] qdrant upsert failed ({kind}/{box}): {exc}",
                      file=sys.stderr)

        # Bump the cache generation — invalidates all cached reads without
        # an exhaustive key scan.
        if self._redis is not None:
            try:
                self._redis.incr(self._GEN_KEY)
            except Exception as exc:
                print(f"[memory] redis incr failed: {exc}", file=sys.stderr)

    @staticmethod
    def _fts_query(q: str) -> str:
        """Turn free text into a safe FTS5 OR-of-quoted-tokens query.

        FTS5 treats `.` `:` `-` and bare AND/OR/NOT as syntax. Quoting each
        token sidesteps that. Tokens shorter than 3 chars (and IP-octet
        noise) are dropped; the query is capped at 20 terms.
        """
        tokens = [t for t in re.findall(r"[A-Za-z0-9]+", q) if len(t) >= 3]
        if not tokens:
            return '""'
        return " OR ".join(f'"{t}"' for t in tokens[:20])

    def _cache_key(self, gen: str, query: str, k: int,
                   kind_filter: str | None) -> str:
        raw = f"{gen}|{query}|{k}|{kind_filter or ''}"
        return self._CACHE_NS + hashlib.sha256(raw.encode()).hexdigest()

    def _cache_get(self, query: str, k: int,
                   kind_filter: str | None) -> list[Recollection] | None:
        if self._redis is None:
            return None
        try:
            gen = self._redis.get(self._GEN_KEY) or "0"
            raw = self._redis.get(self._cache_key(gen, query, k, kind_filter))
            if not raw:
                return None
            return [Recollection(**d) for d in json.loads(raw)]
        except Exception as exc:
            print(f"[memory] redis get failed: {exc}", file=sys.stderr)
            return None

    def _cache_set(self, query: str, k: int, kind_filter: str | None,
                   results: list[Recollection]) -> None:
        if self._redis is None:
            return
        try:
            gen = self._redis.get(self._GEN_KEY) or "0"
            key = self._cache_key(gen, query, k, kind_filter)
            payload = json.dumps([asdict(r) for r in results], default=str)
            self._redis.setex(key, self._cache_ttl, payload)
        except Exception as exc:
            print(f"[memory] redis setex failed: {exc}", file=sys.stderr)

    def _fts_search(self, query: str, k: int,
                    kind_filter: str | None) -> list[tuple[str, Recollection]]:
        """FTS5 leg of the hybrid search. Returns (session_id, recollection)
        tuples in rank order so the fuser can dedupe across legs."""
        try:
            fetch = k * 3 if kind_filter else k
            msgs = self._store.search(self._fts_query(query), limit=fetch)
        except Exception as exc:
            print(f"[memory] fts search failed ({query!r}): {exc}",
                  file=sys.stderr)
            return []
        out: list[tuple[str, Recollection]] = []
        for m in msgs:
            try:
                sess = self._store.get_session(m.session_id)
            except Exception:
                sess = None
            meta = (sess.metadata if sess else {}) or {}
            if kind_filter and meta.get("kind") != kind_filter:
                continue
            box = meta.get("box") or "(unknown)"
            out.append((m.session_id, Recollection(
                box_name=str(box),
                summary=(m.content or "")[:240],
                score=0.0,
                tags=dict(meta),
            )))
            if len(out) >= k:
                break
        return out

    def _qdrant_search(self, query: str, k: int,
                       kind_filter: str | None
                       ) -> list[tuple[str, Recollection]]:
        """Qdrant leg of the hybrid search."""
        if self._qdrant is None or self._embed is None:
            return []
        try:
            vec = self._embed.encode(query).tolist()
            qfilter = None
            if kind_filter:
                qfilter = qmodels.Filter(must=[qmodels.FieldCondition(
                    key="kind",
                    match=qmodels.MatchValue(value=kind_filter),
                )])
            hits = self._qdrant.query_points(
                collection_name=self._collection,
                query=vec, limit=k, query_filter=qfilter,
            ).points
        except Exception as exc:
            print(f"[memory] qdrant search failed ({query!r}): {exc}",
                  file=sys.stderr)
            return []
        out: list[tuple[str, Recollection]] = []
        for h in hits:
            payload = h.payload or {}
            meta = payload.get("meta") or {}
            sid = payload.get("session_id") or str(h.id)
            out.append((sid, Recollection(
                box_name=str(payload.get("box") or "(unknown)"),
                summary=str(payload.get("snippet") or ""),
                score=0.0,
                tags=dict(meta),
            )))
        return out

    def _search(self, query: str, k: int,
                kind_filter: str | None = None) -> list[Recollection]:
        """Hybrid FTS5 + Qdrant search fused by reciprocal rank fusion.

        Falls back to FTS5-only (with the legacy pseudo-score) when Qdrant
        is unavailable. Cached via Redis when available.
        """
        cached = self._cache_get(query, k, kind_filter)
        if cached is not None:
            return cached

        fts_hits = self._fts_search(query, k, kind_filter)

        if self._qdrant is None or self._embed is None:
            # FTS5-only path — preserve the rank-based pseudo-score.
            out: list[Recollection] = []
            for i, (_sid, rec) in enumerate(fts_hits):
                rec.score = max(0.0, 1.0 - (i * (1.0 / max(k, 1))))
                out.append(rec)
                if len(out) >= k:
                    break
            self._cache_set(query, k, kind_filter, out)
            return out

        qdrant_hits = self._qdrant_search(query, k, kind_filter)

        # Reciprocal rank fusion. Ties broken by FTS5 rank (it's first in
        # the iteration order below), which mirrors the legacy ordering when
        # Qdrant returns nothing useful.
        fused: dict[str, dict] = {}
        for rank, (sid, rec) in enumerate(fts_hits):
            entry = fused.setdefault(sid, {"score": 0.0, "rec": rec,
                                           "order": rank})
            entry["score"] += 1.0 / (self._RRF_K + rank + 1)
        for rank, (sid, rec) in enumerate(qdrant_hits):
            entry = fused.get(sid)
            if entry is None:
                fused[sid] = {"score": 1.0 / (self._RRF_K + rank + 1),
                              "rec": rec,
                              "order": len(fused) + rank}
            else:
                entry["score"] += 1.0 / (self._RRF_K + rank + 1)

        ranked = sorted(fused.values(),
                        key=lambda e: (-e["score"], e["order"]))
        out = []
        for entry in ranked[:k]:
            rec = entry["rec"]
            rec.score = entry["score"]
            out.append(rec)
        self._cache_set(query, k, kind_filter, out)
        return out


# Singleton — mirrors the `ARC = Arcade(...)` pattern in mr_robot.py so the
# MCP tools and the orchestrator share one backend.
MEMORY = Memory()
