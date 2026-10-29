"""工单 03 — 切项目重建 runtime + 只读取非活动项目会话名 + 启动会话选择。

S2 接缝：用**假 runtime factory**（记录 close）驱动 WorkspaceManager，不碰真模型。
checkpoint 库用最小 sqlite 表造（只需 thread_id 列）以测只读列举。
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from pathlib import Path

from tests.gui_fakes import TEST_ROOT


def _home() -> "tuple":
    d = TEST_ROOT / f"sw-{uuid.uuid4().hex[:10]}"
    d.mkdir(parents=True)
    return d, lambda: shutil.rmtree(d, ignore_errors=True)


def _mk_checkpoint_db(path: Path, tids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE checkpoints (thread_id TEXT, checkpoint_id TEXT)")
    for t in tids:
        con.execute("INSERT INTO checkpoints VALUES (?, '1')", (t,))
    con.commit()
    con.close()


from src.gui.project_registry import ProjectRegistry  # noqa: E402
from src.gui.workspace import WorkspaceManager, list_sessions_readonly, pick_start_session  # noqa: E402


def test_list_sessions_readonly_ids_and_titles():
    d, clean = _home()
    try:
        proj = d / "p"
        proj.mkdir()
        _mk_checkpoint_db(proj / "checkpoints" / "checkpoints.sqlite", ["session-abc", "session-def", "sched-x"])
        (proj / "sessions.json").write_text(
            json.dumps({"session-abc": {"title": "修登录"}, "session-def": {"title": ""}}), encoding="utf-8"
        )
        got = list_sessions_readonly(proj)
        names = dict(got)  # (tid, title) -> tid: title
        assert names["session-abc"] == "修登录"
        assert names["session-def"] == "session-def"  # 空标题回落 tid
        assert "sched-x" not in names  # 过滤 sched-*
    finally:
        clean()


def test_list_sessions_readonly_missing_db_is_empty():
    d, clean = _home()
    try:
        proj = d / "p"
        proj.mkdir()
        assert list_sessions_readonly(proj) == []
    finally:
        clean()


def test_pick_start_session_last_active_then_none():
    d, clean = _home()
    try:
        reg = ProjectRegistry(d / "projects.json")
        proj = d / "p"
        proj.mkdir()
        reg.add(proj, now=1.0)
        assert pick_start_session(reg, proj, ["s1", "s2"]) is None  # 无记录 → 新会话
        reg.set_last_active_thread(proj, "s1")
        assert pick_start_session(reg, proj, ["s1", "s2"]) == "s1"
        reg.set_last_active_thread(proj, "gone")
        assert pick_start_session(reg, proj, ["s1", "s2"]) is None  # 记录已不在 → 新会话
    finally:
        clean()


class _FakeRT:
    def __init__(self, tag):
        self.tag = tag
        self.closed = False

    def close(self):
        self.closed = True


def test_switch_closes_old_builds_new_sets_active():
    d, clean = _home()
    try:
        reg = ProjectRegistry(d / "projects.json")
        a, b = d / "a", d / "b"
        a.mkdir(); b.mkdir()
        reg.add(a, now=1.0)
        factory_calls: list = []

        def factory(root):
            factory_calls.append(str(root))
            return _FakeRT(Path(root).name)

        wm = WorkspaceManager(reg, factory)
        rt1 = wm.switch_to(a)
        assert rt1.tag == "a" and reg.active() == str(a.resolve())
        rt2 = wm.switch_to(b)
        assert rt2.tag == "b" and reg.active() == str(b.resolve())
        assert rt1.closed is True  # 切走时旧的被关
        assert factory_calls == [str(a.resolve()), str(b.resolve())]
    finally:
        clean()


def test_switch_aborted_when_running_and_confirm_declines():
    d, clean = _home()
    try:
        reg = ProjectRegistry(d / "projects.json")
        a, b = d / "a", d / "b"
        a.mkdir(); b.mkdir()
        reg.add(a, now=1.0)
        wm = WorkspaceManager(reg, lambda r: _FakeRT(Path(r).name), is_running=lambda: True)
        rt = wm.switch_to(a)
        assert wm.current is rt and wm.current.tag == "a"
        aborted = wm.switch_to(b, proceed_if_running=lambda: False)  # 有进行中回合且拒绝
        assert aborted is None and wm.current is rt and wm.active_root == a.resolve()
        ok = wm.switch_to(b, proceed_if_running=lambda: True)
        assert ok is not None and ok.tag == "b" and wm.current is ok
        assert rt.closed is True
    finally:
        clean()
