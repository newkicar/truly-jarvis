"""工单 04 — 侧栏项目→会话树（offscreen，用假 workspace 隔离切换器，不碰真模型/切换）。

断言落在：树节点集合、点项目名=触发切换、点活动项目叶子=切会话、叶子文本、项目右键菜单。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from src.gui.events import UiBridge
from src.gui.main_window import _PROJ_ROLE, _TID_ROLE, MainWindow
from src.gui.runtime import GuiPresenter
from tests.test_gui_presenter import _fake_runtime


class FakeWorkspace:
    """实现 MainWindow 依赖的工作区接口（单 presenter + 预置多项目数据，不真切换）。"""

    def __init__(self, presenter, projects, sessions_by_root, active):
        self.presenter = presenter
        self.bridge = presenter.bridge
        self._projects = projects            # [(root, name, pinned)]
        self._sessions = sessions_by_root    # {root: [(tid, label)]}
        self._active = active
        self.switch_log: list[str] = []

    def projects(self):
        return self._projects

    def sessions_for(self, root):
        return self._sessions.get(str(Path(root)), [])

    def active_root(self):
        return self._active

    def recent(self):
        return [(r, n) for (r, n, _p) in self._projects]

    def switch_project(self, root, proceed_if_running=None):
        self.switch_log.append(str(Path(root)))
        return self.presenter

    def pick_start(self, root):
        return None

    def set_last_active(self, root, tid):
        pass

    def has_running(self):
        return False

    def project_name(self, root):
        return Path(str(root)).name

    def rename_project(self, root, name):
        pass

    def project_pinned(self, root):
        return False

    def set_project_pinned(self, root, on):
        pass

    def remove_project(self, root):
        pass


def _mk(qapp, monkeypatch):
    rt = _fake_runtime()
    p = GuiPresenter(rt, UiBridge())
    home = str(rt.config.project_root)
    a, b = f"{home}/A", f"{home}/B"
    ws = FakeWorkspace(
        p,
        projects=[(a, "A", False), (b, "B", True)],
        sessions_by_root={str(Path(a)): [], str(Path(b)): [("sB1", "B会话")]},
        active=a,
    )
    # 活动项目 A 的 live 会话（走 presenter.session_ids）
    monkeypatch.setattr(p, "session_ids", lambda: ["sA1", "sA2"])
    win = MainWindow(p, p.bridge, workspace=ws)
    win.show()
    qapp.processEvents()
    return rt, p, ws, win


def test_tree_lists_projects_and_sessions(qapp, monkeypatch):
    _rt, p, ws, win = _mk(qapp, monkeypatch)
    tops = [win.project_tree.topLevelItem(i).text(0) for i in range(win.project_tree.topLevelItemCount())]
    assert "A" in tops and "★ B" in tops  # B 置顶带 ★
    leaves = win.session_leaf_texts()
    # 活动项目 A 的 live 会话作叶子；非活动 B 的只读会话作叶子（叶子文本带 ▸/空格 前缀）
    assert any("sA1" in t for t in leaves)
    assert any("B会话" in t for t in leaves)


def test_click_project_node_triggers_switch(qapp, monkeypatch):
    _rt, _p, ws, win = _mk(qapp, monkeypatch)
    proj_b = None
    for i in range(win.project_tree.topLevelItemCount()):
        it = win.project_tree.topLevelItem(i)
        if "B" in it.text(0) and "A" not in it.text(0):
            proj_b = it
    assert proj_b is not None
    ws.switch_log.clear()
    win._on_tree_item_clicked(proj_b, 0)
    assert ws.switch_log  # 点非活动项目 → 触发切换


def test_click_active_leaf_switches_session(qapp, monkeypatch):
    _rt, p, ws, win = _mk(qapp, monkeypatch)
    ws.switch_log.clear()
    leaf = None
    for i in range(win.project_tree.topLevelItemCount()):
        pi = win.project_tree.topLevelItem(i)
        for j in range(pi.childCount()):
            ch = pi.child(j)
            if ch.data(0, _TID_ROLE) == "sA1":
                leaf = ch
    assert leaf is not None
    win._on_tree_item_clicked(leaf, 0)
    assert win.active_tid == "sA1"
    assert ws.switch_log == []  # 活动项目内切会话 → 不切项目


def test_project_context_menu_items(qapp, monkeypatch):
    _rt, _p, _ws, win = _mk(qapp, monkeypatch)
    menu = win._build_project_menu("some-root")
    texts = [a.text() for a in menu.actions()]
    assert "重命名" in texts
    assert "置顶" in texts
    assert "在资源管理器打开" in texts
    assert any("移除" in t for t in texts)
