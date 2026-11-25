"""Tests for src/memory_router.py (ticket 04): six-namespace recall/propose/
curate, worker permission model, legacy classify/migrate, and db v2 columns.

Directory discipline: builds its own home under the system temp dir and
redirects JARVIS_HOME for the duration of each test.  No pytest tmp_path.
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import uuid
from pathlib import Path

import pytest

from src import memory_router as mr
from src.memory_router import (
    AccessPolicy,
    MemoryPermissionError,
    MemoryRouterError,
    classify_legacy_memory,
    migrate_legacy_memory,
)
from src.profiles import db as pdb
from src.project_paths import ENV_JARVIS_HOME

_NUL = chr(0)
_BSLASH = chr(92)


@contextlib.contextmanager
def _home(tag: str = ""):
    base = Path(tempfile.gettempdir()) / (
        f"jarvis_profile_mr_{os.getpid()}_{tag or uuid.uuid4().hex[:6]}"
    )
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    home = (base / "home").resolve()
    home.mkdir(parents=True)
    prev = os.environ.get(ENV_JARVIS_HOME)
    os.environ[ENV_JARVIS_HOME] = str(home)
    try:
        yield home
    finally:
        if prev is None:
            os.environ.pop(ENV_JARVIS_HOME, None)
        else:
            os.environ[ENV_JARVIS_HOME] = prev
        shutil.rmtree(base, ignore_errors=True)


@pytest.fixture()
def home():
    with _home() as h:
        yield h


def _router(home):
    return mr.MemoryRouter.for_worker("alice", "t1", "p1")


class TestConstruction:
    def test_for_worker_reads_env(self, home):
        r = _router(home)
        assert r.user_home == home
        assert r.profile_id == "alice"
        assert r.task_id == "t1"
        assert r.project_id == "p1"

    def test_for_worker_no_project(self, home):
        r = mr.MemoryRouter.for_worker("alice", "t1", None)
        assert r.project_id is None
        assert r.ns_path(mr.NS_PROJECT) is None

    @pytest.mark.parametrize("pid,tid,proj", [
        ("", "t", "p"),
        (".", "t", "p"),
        ("..", "t", "p"),
        ("a" + _NUL + "b", "t", "p"),
        ("a/b", "t", "p"),
        ("a" + _BSLASH + "b", "t", "p"),
        ("ok", "t1", ".."),
    ])
    def test_unsafe_segments_rejected(self, home, pid, tid, proj):
        with pytest.raises(MemoryRouterError):
            mr.MemoryRouter.for_worker(pid, tid, proj)

    def test_empty_profile_direct(self, home):
        with pytest.raises(MemoryRouterError):
            mr.MemoryRouter(home, "", "t", "p", AccessPolicy())


class TestRecall:
    def test_empty_tree(self, home):
        res = _router(home).recall()
        assert res.items == ()
        assert not res.truncated
        assert res.sources == ()

    def test_fallback_file_when_no_index(self, home):
        agent_mem = home / "agents" / "alice" / "memory"
        agent_mem.mkdir(parents=True)
        (agent_mem / "notes.md").write_text("# My Notes\nfirst line here\n", encoding="utf-8")
        res = _router(home).recall(scopes=("agent",))
        assert res.items
        assert res.items[0].kind == "file"
        assert res.items[0].title == "My Notes"

    def test_index_wins_over_lessons_md(self, home):
        agent_mem = home / "agents" / "alice" / "memory"
        agent_mem.mkdir(parents=True)
        (agent_mem / "lessons.md").write_text("# Lessons\nl\n", encoding="utf-8")
        (agent_mem / "MEMORY.md").write_text("# Index\n- entry\n", encoding="utf-8")
        res = _router(home).recall(scopes=("agent",))
        assert res.items[0].kind == "index"
        assert res.items[0].source.endswith("MEMORY.md")

    def test_query_filters_case_insensitive(self, home):
        agent_mem = home / "agents" / "alice" / "memory"
        agent_mem.mkdir(parents=True)
        (agent_mem / "notes.md").write_text("# Notes\nALPHA beta gamma\nnothing\n", encoding="utf-8")
        r = _router(home)
        res = r.recall("alpha", scopes=("agent",))
        assert res.items and res.items[0].snippet == "ALPHA beta gamma"
        assert r.recall("does-not-exist", scopes=("agent",)).items == ()

    def test_budget_truncates(self, home):
        agent_mem = home / "agents" / "alice" / "memory"
        agent_mem.mkdir(parents=True)
        (agent_mem / "a.md").write_text("# A\ncontent a\n", encoding="utf-8")
        (agent_mem / "b.md").write_text("# B\ncontent b\n", encoding="utf-8")
        res = _router(home).recall(token_budget=0, scopes=("agent",))
        assert res.truncated
        assert len(res.items) >= 1

    def test_read_denied(self, home):
        agent_mem = home / "agents" / "alice" / "memory"
        agent_mem.mkdir(parents=True)
        (agent_mem / "n.md").write_text("# N\nx\n", encoding="utf-8")
        r = mr.MemoryRouter(home, "alice", "t1", "p1",
                            AccessPolicy(read=(), write=(), propose=()))
        with pytest.raises(MemoryPermissionError):
            r.recall()

    def test_unknown_scope_rejected(self, home):
        with pytest.raises(MemoryRouterError):
            _router(home).recall(scopes=("bogus",))

    def test_negative_budget_rejected(self, home):
        with pytest.raises(MemoryRouterError):
            _router(home).recall(token_budget=-1)

    def test_task_scope_reads_working_memory_only(self, home):
        task_dir = home / "tasks" / "t1"
        task_dir.mkdir(parents=True)
        (task_dir / "working-memory.md").write_text("# WM\nstep\n", encoding="utf-8")
        (task_dir / "other.md").write_text("# Other\nnope\n", encoding="utf-8")
        res = _router(home).recall(scopes=("task",))
        assert [i.source for i in res.items] == ["tasks/t1/working-memory.md"]


class TestTaskMemory:
    def test_append(self, home):
        r = _router(home)
        p1 = r.write_task_memory("line1\n", mode="replace")
        p2 = r.write_task_memory("line2\n", mode="append")
        assert p1 == p2
        assert p1.read_text(encoding="utf-8") == "line1\nline2\n"

    def test_replace(self, home):
        r = _router(home)
        r.write_task_memory("old\n", mode="append")
        p = r.write_task_memory("new\n", mode="replace")
        assert p.read_text(encoding="utf-8") == "new\n"

    def test_invalid_mode_rejected(self, home):
        with pytest.raises(MemoryRouterError):
            _router(home).write_task_memory("x", mode="bogus")

    def test_write_denied(self, home):
        r = mr.MemoryRouter(home, "alice", "t1", "p1",
                            AccessPolicy(read=(), write=(), propose=()))
        with pytest.raises(MemoryPermissionError):
            r.write_task_memory("x")


class TestPropose:
    def test_agent_candidate_fields(self, home):
        r = _router(home)
        rec = r.propose("agent", "prefer small diffs", memory_type="lesson")
        assert rec.source_task_id == "t1"
        assert rec.source_agent_id == "alice"
        assert rec.target_namespace == "agents/alice"
        assert rec.memory_type == "lesson"
        assert rec.status == "pending_review"
        assert rec.created_at
        conn = sqlite3.connect(str(mr.meta_db_path(home)))
        row = conn.execute(
            "SELECT status FROM memory_candidates WHERE candidate_id=?",
            (rec.candidate_id,)).fetchone()
        conn.close()
        assert row[0] == "pending_review"

    def test_jsonl_mirror(self, home):
        r = _router(home)
        rec = r.propose("agent", "x", confidence="high")
        mirror = home / "tasks" / "t1" / "memory-candidates" / "candidates.jsonl"
        text = mirror.read_text(encoding="utf-8")
        assert text.endswith("\n")
        parsed = json.loads(text.strip().splitlines()[-1])
        assert parsed["candidate_id"] == rec.candidate_id
        assert parsed["confidence"] == "high"

    def test_empty_content_rejected(self, home):
        with pytest.raises(MemoryRouterError):
            _router(home).propose("agent", "   ")

    def test_confidence_nullable(self, home):
        rec = _router(home).propose("agent", "x")
        assert rec.confidence is None

    def test_other_agent_denied(self, home):
        with pytest.raises(MemoryPermissionError):
            _router(home).propose("agents/bob", "x")

    def test_other_project_denied(self, home):
        with pytest.raises(MemoryPermissionError):
            _router(home).propose("projects/p2", "x")

    def test_secretary_denied_default(self, home):
        with pytest.raises(MemoryPermissionError):
            _router(home).propose("secretary", "x")

    def test_unknown_namespace_rejected(self, home):
        with pytest.raises(MemoryRouterError):
            _router(home).propose("bogus", "x")

    def test_project_requires_binding(self, home):
        r = mr.MemoryRouter.for_worker("alice", "t1", None)
        with pytest.raises(MemoryRouterError):
            r.propose("project", "x")

    def test_source_task_unsafe_rejected(self, home):
        with pytest.raises(MemoryRouterError):
            _router(home).propose("user", "x", source_task_id="..")


class TestCurate:
    def test_approve_writes_and_records(self, home):
        r = _router(home)
        rec = r.propose("user", "likes dark", memory_type="preference")
        out = r.curate(rec.candidate_id, "approve", reviewer="ops")
        assert out["status"] == "approved"
        assert out["target_file"] == "memory/user/preferences.md"
        assert (home / "memory" / "user" / "preferences.md").is_file()
        assert "likes dark" in (home / "memory" / "user" / "preferences.md").read_text(encoding="utf-8")
        conn = sqlite3.connect(str(mr.meta_db_path(home)))
        n = conn.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0]
        conn.close()
        assert n == 1

    def test_reject_no_write(self, home):
        r = _router(home)
        rec = r.propose("user", "x")
        out = r.curate(rec.candidate_id, "reject")
        assert out["status"] == "rejected"
        assert not (home / "memory" / "user" / "preferences.md").exists()
        conn = sqlite3.connect(str(mr.meta_db_path(home)))
        row = conn.execute(
            "SELECT status FROM memory_candidates WHERE candidate_id=?",
            (rec.candidate_id,)).fetchone()
        conn.close()
        assert row[0] == "rejected"

    def test_unknown_candidate_rejected(self, home):
        with pytest.raises(MemoryRouterError):
            _router(home).curate("nope", "approve")

    def test_invalid_decision_rejected(self, home):
        r = _router(home)
        rec = r.propose("user", "x")
        with pytest.raises(MemoryRouterError):
            r.curate(rec.candidate_id, "maybe")

    @pytest.mark.parametrize("ns,mem_type,expected", [
        ("agent", "lesson", "agents/alice/memory/lessons.md"),
        ("agent", "note", "agents/alice/memory/MEMORY.md"),
        ("project", "decision", "projects/p1/memory/decisions.md"),
        ("project", "background", "projects/p1/memory/background.md"),
        ("project", "progress", "projects/p1/memory/progress.md"),
        ("user", "preference", "memory/user/preferences.md"),
        ("user", "fact", "memory/user/profile.md"),
    ])
    def test_namespace_file_mapping(self, home, ns, mem_type, expected):
        r = _router(home)
        rec = r.propose(ns, f"c-{ns}-{mem_type}", memory_type=mem_type)
        out = r.curate(rec.candidate_id, "approve")
        assert out["target_file"] == expected
        assert (home / expected).is_file()

    def test_secretary_requires_policy(self, home):
        policy = AccessPolicy(
            read=(mr.NS_TASK, mr.NS_SECRETARY),
            write=(mr.NS_TASK,),
            propose=(mr.NS_AGENT, mr.NS_PROJECT, mr.NS_USER, mr.NS_SECRETARY),
        )
        r = mr.MemoryRouter(home, "alice", "t1", "p1", policy)
        rec = r.propose("secretary", "ops note")
        out = r.curate(rec.candidate_id, "approve")
        assert out["target_file"] == "memory/secretary/operating-lessons.md"
        assert (home / "memory" / "secretary" / "operating-lessons.md").is_file()


class TestConcurrency:
    def test_concurrent_proposes_consistent(self, home):
        n = 20
        errors = []

        def worker(i):
            try:
                mr.MemoryRouter.for_worker("alice", "t1", "p1").propose("agent", f"cand-{i}")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, errors

        conn = sqlite3.connect(str(mr.meta_db_path(home)))
        cnt = conn.execute(
            "SELECT COUNT(*) FROM memory_candidates "
            "WHERE source_agent_id='alice' AND target_namespace='agents/alice'"
        ).fetchone()[0]
        conn.close()
        mirror = home / "tasks" / "t1" / "memory-candidates" / "candidates.jsonl"
        lines = [ln for ln in mirror.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert cnt == n
        assert len(lines) == n
        for ln in lines:
            json.loads(ln)


class TestLegacy:
    def test_classify_empty_dir(self, home):
        d = home / "legacy-empty"
        d.mkdir()
        rep = classify_legacy_memory(d)
        assert rep["files"] == {}
        assert rep["counts"] == {}

    def test_classify_categorizes(self, home):
        d = home / "legacy"
        d.mkdir()
        (d / "user-prefs.md").write_text("a", encoding="utf-8")
        (d / "secretary-notes.md").write_text("b", encoding="utf-8")
        (d / "project-jarvis.md").write_text("c", encoding="utf-8")
        (d / "random.txt").write_text("d", encoding="utf-8")
        rep = classify_legacy_memory(d)
        assert rep["files"] == {
            "user-prefs.md": "user-preference",
            "secretary-notes.md": "secretary-lesson",
            "project-jarvis.md": "project-knowledge",
            "random.txt": "legacy",
        }
        assert rep["counts"] == {
            "user-preference": 1, "secretary-lesson": 1,
            "project-knowledge": 1, "legacy": 1,
        }

    def test_classify_not_dir_rejected(self, home):
        with pytest.raises(MemoryRouterError):
            classify_legacy_memory(home / "nope")

    def test_migrate_copies_preserves_and_idempotent(self, home):
        src = home / "legacy-src"
        src.mkdir()
        (src / "user-x.md").write_text("A", encoding="utf-8")
        (src / "secretary-y.md").write_text("B", encoding="utf-8")
        (src / "project-z.md").write_text("C", encoding="utf-8")
        (src / "misc.txt").write_text("D", encoding="utf-8")
        rep = classify_legacy_memory(src)
        m1 = migrate_legacy_memory(rep, home)
        assert (home / "memory" / "user" / "user-x.md").read_text(encoding="utf-8") == "A"
        assert (home / "memory" / "secretary" / "secretary-y.md").read_text(encoding="utf-8") == "B"
        assert (home / "memory" / "legacy" / "project-knowledge" / "project-z.md").read_text(encoding="utf-8") == "C"
        assert (home / "memory" / "legacy" / "misc.txt").read_text(encoding="utf-8") == "D"
        assert (src / "user-x.md").is_file()
        log = Path(m1["log"]).read_text(encoding="utf-8")
        assert log.endswith("\n")
        assert len(log.splitlines()) >= 5
        m2 = migrate_legacy_memory(classify_legacy_memory(src), home)
        assert all(i["status"] == "unchanged" for i in m2["items"])

    def test_migrate_bad_report_rejected(self, home):
        with pytest.raises(MemoryRouterError):
            migrate_legacy_memory({"nope": 1}, home)


class TestDbV2:
    def test_fresh_home_has_v2_columns(self, home):
        conn = pdb.connect(home)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(memory_candidates)")}
        versions = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
        conn.close()
        assert "memory_type" in cols and "confidence" in cols
        assert versions == {1, 2}

    def test_upgrade_v1_db_gains_columns(self, home):
        home.mkdir(parents=True, exist_ok=True)
        db_path = pdb.meta_db_path(home)
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE schema_migrations "
                     "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        conn.execute("INSERT INTO schema_migrations VALUES (1, '2026-01-01T00:00:00Z')")
        conn.execute("CREATE TABLE memory_candidates ("
                     " candidate_id TEXT PRIMARY KEY, target_namespace TEXT NOT NULL,"
                     " source_task_id TEXT, source_agent_id TEXT, content TEXT NOT NULL,"
                     " source_reference TEXT, status TEXT NOT NULL DEFAULT 'pending_review',"
                     " created_at TEXT NOT NULL, reviewed_at TEXT, reviewed_by TEXT)")
        conn.commit()
        conn.close()
        pdb.connect(home)
        conn2 = sqlite3.connect(str(db_path))
        cols = {r[1] for r in conn2.execute("PRAGMA table_info(memory_candidates)")}
        versions = {r[0] for r in conn2.execute("SELECT version FROM schema_migrations")}
        conn2.close()
        assert "memory_type" in cols and "confidence" in cols
        assert versions == {1, 2}
