"""工单 05 — WorkspaceController（注册表 + 切项目 + 打开/新建，用假 runtime factory，不碰真模型）。"""
from __future__ import annotations

import shutil
import uuid
from types import SimpleNamespace

from tests.gui_fakes import TEST_ROOT
from src.gui.events import UiBridge
from src.gui.project_registry import ProjectRegistry
from src.gui.workspace_controller import WorkspaceController


def _home() -> "tuple":
    d = TEST_ROOT / f"wctrl-{uuid.uuid4().hex[:10]}"
    d.mkdir(parents=True)
    return d, lambda: shutil.rmtree(d, ignore_errors=True)


class FakeRT:
    def __init__(self, root):
        self.config = SimpleNamespace(project_root=root)
        self.closed = False

    def close(self):
        self.closed = True


def _ctrl(d, root):
    reg = ProjectRegistry(d / "projects.json")
    rt = FakeRT(root)
    made: list = []

    def factory(r):
        f = FakeRT(r)
        made.append(f)
        return f

    reg.add(root, now=1.0)
    ctrl = WorkspaceController(reg, factory, UiBridge())
    return reg, ctrl, made, rt


def test_switch_builds_repoints_and_closes_old():
    d, clean = _home()
    try:
        a, b = d / "a", d / "b"
        a.mkdir(); b.mkdir()
        reg, ctrl, made, _ = _ctrl(d, a)
        p1 = ctrl.switch_project(a)
        assert ctrl.presenter is p1 and ctrl.active_root == a.resolve()
        assert reg.active() == str(a.resolve())
        p2 = ctrl.switch_project(b)
        assert ctrl.presenter is p2 and ctrl.active_root == b.resolve()
        assert len(made) == 2 and made[0].closed is True  # 旧的被关
        assert made[1].closed is False
    finally:
        clean()


def test_open_dir_resolves_inits_registers():
    d, clean = _home()
    try:
        bare = d / "bare"
        bare.mkdir()
        reg, ctrl, _made, _ = _ctrl(d, d / "a")
        (d / "a").mkdir()
        root = ctrl.open_dir(bare, up_to=d)
        assert (bare / "jarvis.json").is_file()  # 缺配置 → 骨架
        assert reg.get(root) is not None
        assert reg.active() == str(root)
    finally:
        clean()


def test_new_dir_creates_scaffolds_registers():
    d, clean = _home()
    try:
        reg, ctrl, _m, _ = _ctrl(d, d / "a")
        (d / "a").mkdir()
        root = ctrl.new_dir("工程X", d)
        assert root == (d / "工程X").resolve()
        assert (root / "jarvis.json").is_file()
        assert reg.get(root)["name"] == "工程X"
    finally:
        clean()


def test_sessions_for_inactive_reads_readonly():
    d, clean = _home()
    try:
        a = d / "a"; a.mkdir()
        reg, ctrl, _m, _ = _ctrl(d, a)
        b = d / "b"; b.mkdir()
        reg.add(b, now=2.0)
        got = ctrl.sessions_for(b)  # b 非活动 → 只读（无 checkpoint 库 → 空）
        assert got == []
    finally:
        clean()


def test_project_node_ops_delegate_to_registry():
    d, clean = _home()
    try:
        a = d / "a"; a.mkdir()
        reg, ctrl, _m, _ = _ctrl(d, a)
        assert ctrl.project_name(a) == "a"
        ctrl.rename_project(a, "甲")
        assert ctrl.project_name(a) == "甲"
        assert ctrl.project_pinned(a) is False
        ctrl.set_project_pinned(a, True)
        assert ctrl.project_pinned(a) is True
        ctrl.remove_project(a)
        assert reg.entries() == []
        assert a.exists()  # 只删登记，不删项目
    finally:
        clean()
