"""工单 01 — 项目注册表 `project_registry`（全局 ~/.jarvis/projects.json）。

纯逻辑（无 Qt）：登记/去重/排序/置顶/移除/启动选取。测试只看「读回的文件内容」。
目录纪律：自建于 .scratch/gui-test-tmp（禁 tmp_path）。
"""
from __future__ import annotations

import shutil
import uuid

from tests.gui_fakes import TEST_ROOT


def _tmp() -> "tuple":
    d = TEST_ROOT / f"reg-{uuid.uuid4().hex[:10]}"
    d.mkdir(parents=True)
    return d, lambda: shutil.rmtree(d, ignore_errors=True)


from src.gui.project_registry import ProjectRegistry, default_registry_path  # noqa: E402


def test_default_registry_path_under_user_home(monkeypatch):
    import src.project_paths as pp

    monkeypatch.setattr(pp, "user_home", lambda: _tmp()[0])
    p = default_registry_path()
    assert p.name == "projects.json"


def test_missing_file_is_empty_registry():
    d, clean = _tmp()
    try:
        reg = ProjectRegistry(d / "projects.json")
        assert reg.entries() == []
        assert reg.active() is None
    finally:
        clean()


def test_corrupt_file_falls_back_empty():
    d, clean = _tmp()
    try:
        p = d / "projects.json"
        p.write_text("{not json", encoding="utf-8")
        reg = ProjectRegistry(p)
        assert reg.entries() == []
    finally:
        clean()


def test_add_dedupe_by_resolved_path_and_sets_active():
    d, clean = _tmp()
    try:
        reg = ProjectRegistry(d / "projects.json")
        proj = d / "projA"
        proj.mkdir()
        reg.add(proj, now=1.0)
        reg.add(proj, now=2.0)  # 同目录重复开 = 只刷最近，不新增
        assert len(reg.entries()) == 1
        e = reg.entries()[0]
        assert e["last_opened"] == 2.0
        assert e["name"] == "projA"  # 显示名默认 = 文件夹名
        assert reg.active() == str(proj.resolve())
    finally:
        clean()


def test_ordered_pinned_first_then_recent():
    d, clean = _tmp()
    try:
        reg = ProjectRegistry(d / "projects.json")
        a, b, c = d / "a", d / "b", d / "c"
        for p in (a, b, c):
            p.mkdir()
        reg.add(a, now=1.0)
        reg.add(b, now=2.0)
        reg.add(c, now=3.0)
        reg.set_pinned(a, True)
        names = [x["name"] for x in reg.ordered()]
        assert names == ["a", "c", "b"]  # 置顶 a 优先；其余按最近 c>b
    finally:
        clean()


def test_remove_only_registry_never_touches_project_files():
    d, clean = _tmp()
    try:
        reg = ProjectRegistry(d / "projects.json")
        a = d / "a"
        a.mkdir()
        (a / "jarvis.json").write_text("{}", encoding="utf-8")
        reg.add(a, now=1.0)
        reg.remove(a)
        assert reg.entries() == []
        assert (a / "jarvis.json").is_file()  # 项目文件仍在
    finally:
        clean()


def test_rename_and_pin_and_last_active_thread():
    d, clean = _tmp()
    try:
        reg = ProjectRegistry(d / "projects.json")
        a = d / "a"
        a.mkdir()
        reg.add(a, now=1.0)
        reg.rename(a, "我的项目")
        reg.set_pinned(a, True)
        reg.set_last_active_thread(a, "session-abc")
        e = reg.get(a)
        assert e["name"] == "我的项目"
        assert e["pinned"] is True
        assert reg.last_active_thread(a) == "session-abc"
    finally:
        clean()


def test_pick_launch_most_recent_existing_skips_missing():
    d, clean = _tmp()
    try:
        reg = ProjectRegistry(d / "projects.json")
        a, b = d / "gone", d / "here"
        a.mkdir()
        b.mkdir()
        reg.add(a, now=5.0)
        reg.add(b, now=4.0)
        reg.set_pinned(b, True)
        shutil.rmtree(a)  # 最近的 a（gone）目录被删
        picked = reg.pick_launch()
        assert picked is not None and picked["name"] == "here"  # 跳过已消失的 a，取下一个存在的 b
    finally:
        clean()


def test_pick_launch_none_when_registry_empty_or_all_missing():
    d, clean = _tmp()
    try:
        reg = ProjectRegistry(d / "projects.json")
        assert reg.pick_launch() is None
        a = d / "x"
        a.mkdir()
        reg.add(a, now=1.0)
        shutil.rmtree(a)
        assert reg.pick_launch() is None
    finally:
        clean()
