# -*- coding: utf-8 -*-
"""Memory Router - ticket 04 (spec section 8).

Six memory namespaces:

  user        ~/.jarvis/memory/user/             profile.md / preferences.md
  secretary   ~/.jarvis/memory/secretary/        MEMORY.md / operating-lessons.md
  agent       ~/.jarvis/agents/<id>/memory/      MEMORY.md index + topic files
  project     ~/.jarvis/projects/<p>/memory/     background/decisions/progress.md
  task        ~/.jarvis/tasks/<tid>/             working-memory.md + memory-candidates/
  checkpoint  NOT part of this router: the langgraph checkpointer owns
              conversation/execution state (spec 8.1 - "Checkpoint is not
              semantic memory").

Recall strategy (8.3): index-first (a MEMORY.md index entry wins), no-index
namespaces fall back to file title + first line; token budget uses the
chars/4 heuristic; every returned item records its source path.

Write strategy (8.4/8.5): workers never overwrite memory files directly.
They append candidate records (SQLite upsert + a JSONL mirror under the task
namespace) and a curator promotes/rejects them via curate(), which runs on a
single connection with BEGIN IMMEDIATE.  confidence is nullable and must
never be fabricated.

Default worker permissions (enforced in code, not prompt):
  read    = own task / own agent / shared project / user (read-only)
  write   = own task working-memory only
  propose = agent / project / user candidates only

Legacy memory (13.2): classify_legacy_memory() is a pure report;
migrate_legacy_memory() runs only when explicitly invoked (backup, then
classify-write, then log; originals are preserved).  Never automatic.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from src.project_paths import user_home
from src.profiles.db import connect, meta_db_path

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class MemoryRouterError(ValueError):
    """Invalid memory-router input or state."""


class MemoryPermissionError(MemoryRouterError):
    """Requested operation violates the worker access policy."""


# ---------------------------------------------------------------------------
# Namespace kinds
# ---------------------------------------------------------------------------

NS_USER = "user"
NS_SECRETARY = "secretary"
NS_AGENT = "agent"
NS_PROJECT = "project"
NS_TASK = "task"

#: Kinds this router manages.  "checkpoint" is deliberately absent.
NS_KINDS: tuple[str, ...] = (NS_TASK, NS_AGENT, NS_PROJECT, NS_USER, NS_SECRETARY)

_CANDIDATE_DECISIONS = ("approve", "reject")


def _safe_segment(value: str, label: str) -> str:
    """Reject anything that is not a single safe path segment."""
    v = (value or "").strip()
    if not v or v in (".", "..") or "\0" in v or "/" in v or "\\" in v:
        raise MemoryRouterError(f"{label} is not a safe path segment: {value!r}")
    return v


# ---------------------------------------------------------------------------
# Access policy
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AccessPolicy:
    """Which namespace kinds a worker may read / write / propose into."""

    read: tuple[str, ...] = (NS_TASK, NS_AGENT, NS_PROJECT, NS_USER)
    write: tuple[str, ...] = (NS_TASK,)
    propose: tuple[str, ...] = (NS_AGENT, NS_PROJECT, NS_USER)


# ---------------------------------------------------------------------------
# Result records
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RecallItem:
    namespace: str        # ns kind: task / agent / project / user / secretary
    kind: str             # "index" (MEMORY.md) or "file"
    title: str
    snippet: str
    source: str           # path relative to the user home, posix form


@dataclass(frozen=True)
class RecallResult:
    items: tuple[RecallItem, ...] = ()
    truncated: bool = False
    budget_tokens: int = 0
    used_tokens: int = 0
    sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidateRecord:
    candidate_id: str
    target_namespace: str
    source_task_id: str
    source_agent_id: str
    memory_type: str
    content: str
    source_reference: str
    confidence: Optional[str]
    created_at: str
    status: str = "pending_review"


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

#: module-level lock serializing in-process JSONL mirrors; the authoritative
#: store is SQLite (cross-process safety via BEGIN IMMEDIATE).
_jsonl_lock = threading.Lock()


class MemoryRouter:
    """Namespaced recall / propose / curate for one worker."""

    def __init__(
        self,
        user_home_: Path,
        profile_id: str,
        task_id: str,
        project_id: Optional[str],
        policy: AccessPolicy,
    ) -> None:
        self.user_home = Path(user_home_)
        self.profile_id = _safe_segment(profile_id, "profile_id")
        self.task_id = _safe_segment(task_id, "task_id")
        self.project_id = (
            _safe_segment(project_id, "project_id") if project_id else None
        )
        self.policy = policy

    # -- factory ------------------------------------------------------------

    @classmethod
    def for_worker(
        cls,
        profile_id: str,
        task_id: str,
        project_id: Optional[str],
        access_policy: Optional[AccessPolicy] = None,
    ) -> "MemoryRouter":
        """Build a router bound to the JARVIS_HOME that is set at call time."""
        return cls(
            user_home(), profile_id, task_id, project_id,
            access_policy or AccessPolicy(),
        )

    # -- namespace paths ------------------------------------------------------

    def ns_path(self, kind: str) -> Optional[Path]:
        """Absolute directory of a namespace kind; None when not applicable."""
        if kind not in NS_KINDS:
            raise MemoryRouterError(f"unknown memory namespace kind: {kind!r}")
        home = self.user_home
        if kind == NS_USER:
            return home / "memory" / "user"
        if kind == NS_SECRETARY:
            return home / "memory" / "secretary"
        if kind == NS_AGENT:
            return home / "agents" / self.profile_id / "memory"
        if kind == NS_PROJECT:
            if not self.project_id:
                return None
            return home / "projects" / self.project_id / "memory"
        if kind == NS_TASK:
            return home / "tasks" / self.task_id
        return None  # pragma: no cover

    def _check(self, kinds: tuple[str, ...], allowed: tuple[str, ...], what: str) -> None:
        denied = [k for k in kinds if k not in allowed]
        if denied:
            raise MemoryPermissionError(
                f"{what} denied for namespace(s) {', '.join(denied)} "
                f"(allowed: {', '.join(allowed) or 'none'})"
            )

    def _emit_ops(self, kind: str, **fields: object) -> None:
        """ticket 07: best-effort ops event (never breaks memory flows)."""
        try:
            from src.profiles.observability import ops_event

            fields.setdefault("profile_id", self.profile_id)
            fields.setdefault("task_id", self.task_id)
            ops_event(kind, **fields)
        except Exception:
            pass

    # -- recall ---------------------------------------------------------------

    def recall(
        self,
        query: str = "",
        scopes: Optional[tuple[str, ...]] = None,
        token_budget: int = 500,
    ) -> RecallResult:
        """Index-first recall with a chars/4 token budget.

        With an empty query: MEMORY.md index first, then each remaining file's
        title (first non-empty line, '#' stripped) + first line.  With a
        query: only files/lines containing it (case-insensitive) are returned,
        index lines first.  Sources are recorded on every item.
        """
        if token_budget < 0:
            raise MemoryRouterError("token_budget must be >= 0")
        scopes = tuple(scopes) if scopes is not None else (NS_TASK, NS_AGENT, NS_PROJECT, NS_USER)
        unknown = [s for s in scopes if s not in NS_KINDS]
        if unknown:
            raise MemoryRouterError(f"unknown recall scope(s): {', '.join(unknown)}")
        self._check(scopes, self.policy.read, "recall")

        char_budget = token_budget * 4
        q = (query or "").lower()
        items: list[RecallItem] = []
        used = 0
        truncated = False
        for kind in scopes:
            base = self.ns_path(kind)
            if base is None or not base.is_dir():
                continue
            if kind == NS_TASK:
                md_files = [base / "working-memory.md"]
            else:
                md_files = sorted(base.glob("*.md"))
            index = base / "MEMORY.md"
            if index in md_files:
                md_files = [index] + [f for f in md_files if f != index]
            for f in md_files:
                if truncated:
                    break
                if not f.is_file():
                    continue
                text = f.read_text(encoding="utf-8", errors="replace")
                is_index = f == index
                if q:
                    hits = [ln for ln in text.splitlines() if q in ln.lower()]
                    if not hits:
                        continue
                    lines = hits[:3]
                else:
                    nonempty = [ln for ln in text.splitlines() if ln.strip()]
                    if not nonempty:
                        continue
                    lines = nonempty[:2]
                title = lines[0].lstrip("#").strip() or f.stem
                snippet = " / ".join(ln.strip() for ln in lines)
                rel = f.relative_to(self.user_home).as_posix()
                entry_len = len(title) + len(snippet) + len(rel)
                if used + entry_len > char_budget and items:
                    truncated = True
                    break
                items.append(RecallItem(kind, "index" if is_index else "file",
                                         title, snippet, rel))
                used += entry_len
                if used >= char_budget:
                    truncated = True
        self._emit_ops(
            "memory_recall",
            scopes=len(scopes),
            items_count=len(items),
            truncated=truncated,
        )
        return RecallResult(
            items=tuple(items),
            truncated=truncated,
            budget_tokens=token_budget,
            used_tokens=used // 4,
            sources=tuple(i.source for i in items),
        )

    # -- task memory write ------------------------------------------------------

    def write_task_memory(self, content: str, mode: str = "append") -> Path:
        """Write the worker's own task working-memory (the only direct write)."""
        if mode not in ("append", "replace"):
            raise MemoryRouterError(f"invalid write mode: {mode!r}")
        self._check((NS_TASK,), self.policy.write, "write")
        target = self.ns_path(NS_TASK) / "working-memory.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        if mode == "replace" or not target.exists():
            target.write_text(content, encoding="utf-8")
        else:
            with target.open("a", encoding="utf-8") as fh:
                fh.write(content)
        return target

    # -- propose ------------------------------------------------------------------

    def _resolve_propose_ns(self, namespace: str) -> tuple[str, str]:
        """Normalize a propose target to (kind, canonical namespace string)."""
        raw = (namespace or "").strip().replace("\\", "/")
        if raw.startswith("agents/"):
            inner = raw[len("agents/"):].strip("/")
            if inner != self.profile_id:
                raise MemoryPermissionError(
                    f"may only propose to own agent namespace "
                    f"(agents/{self.profile_id}), got {namespace!r}"
                )
            return NS_AGENT, f"agents/{self.profile_id}"
        if raw.startswith("projects/"):
            inner = raw[len("projects/"):].strip("/")
            if inner != self.project_id:
                raise MemoryPermissionError(
                    f"may only propose to own project namespace "
                    f"(projects/{self.project_id}), got {namespace!r}"
                )
            return NS_PROJECT, f"projects/{self.project_id}"
        kind = raw
        if kind in (NS_USER, NS_SECRETARY):
            return kind, kind
        if kind == NS_AGENT:
            return NS_AGENT, f"agents/{self.profile_id}"
        if kind == NS_PROJECT:
            if not self.project_id:
                raise MemoryRouterError("no project bound to this worker")
            return NS_PROJECT, f"projects/{self.project_id}"
        raise MemoryRouterError(f"unknown propose namespace: {namespace!r}")

    def propose(
        self,
        namespace: str,
        content: str,
        source_task_id: Optional[str] = None,
        memory_type: str = "lesson",
        source_reference: str = "",
        confidence: Optional[str] = None,
    ) -> CandidateRecord:
        """Append an append-only memory candidate (SQLite upsert + JSONL mirror)."""
        if not (content or "").strip():
            raise MemoryRouterError("candidate content must not be empty")
        kind, target_ns = self._resolve_propose_ns(namespace)
        self._check((kind,), self.policy.propose, "propose")
        src_task = source_task_id or self.task_id
        record = CandidateRecord(
            candidate_id=uuid.uuid4().hex,
            target_namespace=target_ns,
            source_task_id=_safe_segment(src_task, "source_task_id"),
            source_agent_id=self.profile_id,
            memory_type=memory_type or "",
            content=content,
            source_reference=source_reference or "",
            confidence=confidence,  # nullable on purpose: never fabricated
            created_at=_utc_now_iso(),
            status="pending_review",
        )
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT INTO memory_candidates
                   (candidate_id, target_namespace, source_task_id, source_agent_id,
                    memory_type, content, source_reference, confidence, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending_review', ?)
                   ON CONFLICT(candidate_id) DO UPDATE SET
                     content = excluded.content,
                     status = 'pending_review',
                     created_at = excluded.created_at""",
                (record.candidate_id, record.target_namespace, record.source_task_id,
                 record.source_agent_id, record.memory_type, record.content,
                 record.source_reference, record.confidence, record.created_at),
            )
            conn.execute("COMMIT")
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()
        self._append_jsonl_mirror(record)
        self._emit_ops(
            "memory_candidate_created",
            candidate_id=record.candidate_id,
            target_namespace=record.target_namespace,
            memory_type=record.memory_type,
        )
        return record

    def _append_jsonl_mirror(self, record: CandidateRecord) -> Path:
        mirror_dir = self.ns_path(NS_TASK) / "memory-candidates"
        mirror_dir.mkdir(parents=True, exist_ok=True)
        target = mirror_dir / "candidates.jsonl"
        line = json.dumps(dataclass_to_jsonl(record), ensure_ascii=False)
        with _jsonl_lock:
            with target.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        return target

    # -- curate ---------------------------------------------------------------------

    def _curate_target_file(self, target_ns: str, memory_type: str) -> Path:
        raw = target_ns.strip().replace("\\", "/")
        if raw.startswith("agents/"):
            base = self.user_home / "agents" / raw[len("agents/"):].strip("/") / "memory"
            return base / ("lessons.md" if memory_type == "lesson" else "MEMORY.md")
        if raw.startswith("projects/"):
            base = self.user_home / "projects" / raw[len("projects/"):].strip("/") / "memory"
            if memory_type == "decision":
                return base / "decisions.md"
            if memory_type == "background":
                return base / "background.md"
            return base / "progress.md"
        if raw == NS_USER:
            base = self.user_home / "memory" / "user"
            return base / ("preferences.md" if memory_type == "preference" else "profile.md")
        if raw == NS_SECRETARY:
            return self.user_home / "memory" / "secretary" / "operating-lessons.md"
        raise MemoryRouterError(f"cannot curate into namespace {target_ns!r}")

    def curate(self, candidate_id: str, decision: str, reviewer: str = "user") -> dict[str, Any]:
        """Approve or reject one candidate under a single BEGIN IMMEDIATE."""
        if decision not in _CANDIDATE_DECISIONS:
            raise MemoryRouterError(f"invalid decision {decision!r}; use one of {_CANDIDATE_DECISIONS}")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT candidate_id, target_namespace, source_task_id,
                           source_agent_id, memory_type, content, status
                   FROM memory_candidates WHERE candidate_id = ?""",
                (candidate_id,),
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                raise MemoryRouterError(f"unknown candidate: {candidate_id!r}")
            now = _utc_now_iso()
            if decision == "reject":
                conn.execute(
                    """UPDATE memory_candidates SET status = 'rejected',
                       reviewed_at = ?, reviewed_by = ? WHERE candidate_id = ?""",
                    (now, reviewer, candidate_id),
                )
                conn.execute("COMMIT")
                self._emit_ops("memory_candidate_rejected", candidate_id=candidate_id)
                return {"status": "rejected", "candidate_id": candidate_id, "reviewer": reviewer}
            # approve: append to the target namespace file, record the entry
            target_file = self._curate_target_file(row[1], row[4] or "")
            target_file.parent.mkdir(parents=True, exist_ok=True)
            entry_line = (
                f"- [{row[4] or 'entry'}] {row[5]}"
                f"  (source: task={row[2] or '-'}, agent={row[3] or '-'}, {now})\n"
            )
            with target_file.open("a", encoding="utf-8") as fh:
                fh.write(entry_line)
            memory_id = uuid.uuid4().hex
            proj_id = None
            if row[1].startswith("projects/"):
                proj_id = row[1][len("projects/"):]
            conn.execute(
                """INSERT INTO memory_entries
                   (memory_id, namespace, memory_type, content, source_task_id,
                    source_agent_id, project_id, status, version, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 1, ?, ?)""",
                (memory_id, row[1], row[4] or "", row[5], row[2], row[3], proj_id, now, now),
            )
            conn.execute(
                """UPDATE memory_candidates SET status = 'approved',
                   reviewed_at = ?, reviewed_by = ? WHERE candidate_id = ?""",
                (now, reviewer, candidate_id),
            )
            conn.execute("COMMIT")
            self._emit_ops(
                "memory_candidate_promoted",
                candidate_id=candidate_id,
                memory_id=memory_id,
            )
            return {
                "status": "approved",
                "candidate_id": candidate_id,
                "memory_id": memory_id,
                "target_file": target_file.relative_to(self.user_home).as_posix(),
                "reviewer": reviewer,
            }
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    # -- db -----------------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Fresh autocommit connection (schema ensured via shared connect())."""
        connect(self.user_home)  # creates dir + migrations, then closes
        conn = sqlite3.connect(str(meta_db_path(self.user_home)), isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn


# ---------------------------------------------------------------------------
# Legacy memory (13.2) - pure report + explicit migration
# ---------------------------------------------------------------------------

_LEGACY_RULES: tuple[tuple[str, str], ...] = (
    ("user-", "user-preference"),
    ("secretary", "secretary-lesson"),
    ("project-", "project-knowledge"),
)


def classify_legacy_memory(mem_dir: Path) -> dict[str, Any]:
    """Classify legacy memory files by name; pure, idempotent, no writes.

    user-* -> user-preference; secretary* -> secretary-lesson;
    project-* -> project-knowledge; anything else -> legacy.
    """
    mem_dir = Path(mem_dir)
    if not mem_dir.is_dir():
        raise MemoryRouterError(f"not a directory: {mem_dir}")
    files: dict[str, str] = {}
    for p in sorted(mem_dir.iterdir()):
        if not p.is_file():
            continue
        name = p.name
        cat = "legacy"
        for prefix, label in _LEGACY_RULES:
            if name.lower().startswith(prefix):
                cat = label
                break
        files[name] = cat
    counts: dict[str, int] = {}
    for cat in files.values():
        counts[cat] = counts.get(cat, 0) + 1
    return {
        "mem_dir": str(mem_dir.resolve()),
        "files": files,
        "counts": counts,
    }


def migrate_legacy_memory(
    report: dict[str, Any],
    target: Path,
    *,
    backup: bool = True,
) -> dict[str, Any]:
    """Explicitly migrate a classify_legacy_memory() report into the new tree.

    Steps (13.2): back up originals, write classified copies, log the
    migration, keep the originals in place.  Idempotent: destinations whose
    content hash already matches are recorded as "unchanged".  This function
    is never called from the normal runtime path.
    """
    if "files" not in report or "mem_dir" not in report:
        raise MemoryRouterError("migrate_legacy_memory expects a classify_legacy_memory report")
    src_dir = Path(report["mem_dir"])
    home = Path(target)
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest_dirs = {
        "user-preference": home / "memory" / "user",
        "secretary-lesson": home / "memory" / "secretary",
        "project-knowledge": home / "memory" / "legacy" / "project-knowledge",
        "legacy": home / "memory" / "legacy",
    }
    backup_root: Optional[Path] = None
    if backup:
        backup_root = home / "memory" / "legacy" / f"_backup-{ts}"
        backup_root.mkdir(parents=True, exist_ok=True)
        for name in report["files"]:
            shutil.copy2(src_dir / name, backup_root / name)
    moved: list[dict[str, str]] = []
    log_lines = [f"# legacy memory migration {ts}", ""]
    for name, cat in report["files"].items():
        src = src_dir / name
        dest = dest_dirs[cat] / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not src.is_file():
            status = "missing"
            digest = ""
        else:
            digest = hashlib.sha256(src.read_bytes()).hexdigest()
            if dest.is_file() and hashlib.sha256(dest.read_bytes()).hexdigest() == digest:
                status = "unchanged"
            else:
                shutil.copy2(src, dest)
                status = "copied"
        moved.append({"file": name, "category": cat, "dest": dest.as_posix(),
                      "sha256": digest, "status": status})
        log_lines.append(f"- {name} -> {cat} -> {dest.as_posix()} [{status}] sha256={digest[:16]}")
    log_file = home / "memory" / "legacy" / f"migration-log-{ts}.md"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    return {"backup": str(backup_root) if backup_root else None,
            "log": str(log_file), "items": moved}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def dataclass_to_jsonl(record: CandidateRecord) -> dict[str, Any]:
    d = {
        "candidate_id": record.candidate_id,
        "source_task_id": record.source_task_id,
        "source_agent_id": record.source_agent_id,
        "target_namespace": record.target_namespace,
        "memory_type": record.memory_type,
        "content": record.content,
        "source_reference": record.source_reference,
        "confidence": record.confidence,
        "created_at": record.created_at,
        "status": record.status,
    }
    return d
