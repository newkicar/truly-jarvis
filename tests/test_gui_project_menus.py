"""工单 05 — 打开/新建 菜单 + 启动最近 + 空状态 + 标题/状态显示项目名（offscreen，假 workspace）。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui.events import UiBridge
from src.gui.main_window import MainWindow
from src.gui.project_registry import ProjectRegistry
from src.gui.runtime import GuiPresenter
from src.gui.workspace_controller import WorkspaceController
from tests.gui_fakes import TEST_ROOT, cleanup_home, new_home
from tests.test_gui_presenter import _fake_runtime


def _menu(win, title):
    for act in win.menuBar().actions():
        m = act.menu()
        if m and m.title() == title:
            return m
    return None


def _win_with_two_projects(qapp, monkeypatch):
    rt = _fake_runtime()
    p = GuiPresenter(rt, UiBridge())
    home = str(rt.config.project_root)
    a, b = f"{home}/A", f"{home}/B"
    ws = _FakeMultiWS(p, projects=[(a, "A", False), (b, "B", True)], active=a, sessions={a: [], b: []})
    monkeypatch.setattr(p, "session_ids", lambda: ["s1"])
    win = MainWindow(p, p.bridge, workspace=ws)
    win.show()
    qapp.processEvents()
    return rt, p, ws, win


class _FakeMultiWS:
    """FakeWorkspace + 多项目 new_dir/open_dir 桩（记录调用，不真切换）。"""

    def __init__(self, presenter, projects, active, sessions):
        from pathlib import Path

        self.presenter = presenter
        self.bridge = presenter.bridge
        self._projects = projects
        self._sessions = {Path(k): v for k, v in sessions.items()}
        self._active = active
        self.calls: list = []

    def projects(self):
        return self._projects

    def sessions_for(self, root):
        from pathlib import Path

        return self._sessions.get(Path(root), [])

    def active_root(self):
        return self._active

    def recent(self):
        return [(r, n) for (r, n, _p) in self._projects]

    def switch_project(self, root, proceed_if_running=None):
        self.calls.append(("switch", root))
        return self.presenter

    def pick_start(self, root):
        return None

    def set_last_active(self, root, tid):
        pass

    def has_running(self):
        return False

    def running_sessions(self, root):
        return []

    def new_dir(self, name, parent):
        from pathlib import Path

        self.calls.append(("new", name, parent))
        return Path(parent) / name

    def open_dir(self, chosen):
        from pathlib import Path

        self.calls.append(("open", chosen))
        return Path(chosen)

    def project_name(self, root):
        from pathlib import Path

        return Path(str(root)).name

    def rename_project(self, root, name):
        pass

    def project_pinned(self, root):
        return False

    def set_project_pinned(self, root, on):
        pass

    def remove_project(self, root):
        pass


def test_open_new_menus_present(qapp, monkeypatch):
    _rt, _p, _ws, win = _win_with_two_projects(qapp, monkeypatch)
    assert _menu(win, "打开项目") is not None
    assert _menu(win, "新建项目") is not None
    # 既有菜单保留（Q7 顺序）
    for t in ("命令", "主题", "时间旅行", "MCP 工具", "定时任务", "高级"):
        assert _menu(win, t) is not None, f"缺菜单 {t}"


def test_open_project_menu_lists_recent(qapp, monkeypatch):
    _rt, _p, _ws, win = _win_with_two_projects(qapp, monkeypatch)
    m = _menu(win, "打开项目")
    texts = [a.text() for a in m.actions() if not a.isSeparator()]
    assert "A" in texts and "B" in texts
    assert "打开文件夹…" in texts


def test_new_project_dialog_calls_new_dir_and_switch(qapp, monkeypatch):
    _rt, _p, ws, win = _win_with_two_projects(qapp, monkeypatch)
    switched: list = []
    monkeypatch.setattr(win, "_do_switch_project", lambda root, focus_tid=None: switched.append(root))
    from PySide6.QtWidgets import QFileDialog, QInputDialog

    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: "D:\\parent"))
    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("新工程", True)))
    win._new_project_dialog()
    assert ("new", "新工程", "D:\\parent") in ws.calls
    assert switched  # 触发切换


def test_open_project_menu_about_show_emit_no_crash(qapp, monkeypatch):
    """Item 15 回归：QMenu.aboutToShow 是无参信号。

    旧代码把 1 参槽 `_populate_open_menu(menu)` 直连信号 → 菜单显示（信号触发）时
    `TypeError: _populate_open_menu() missing 1 required positional argument: 'menu'`，
    启动即崩。修复 = lambda 包一层。模拟信号发射：旧代码抛 TypeError，新代码通过。
    """
    _rt, _p, _ws, win = _win_with_two_projects(qapp, monkeypatch)
    m = _menu(win, "打开项目")
    m.aboutToShow.emit()  # 旧代码在此抛 TypeError；新代码正常重填动作
    texts = [a.text() for a in m.actions() if not a.isSeparator()]
    assert "A" in texts and "B" in texts


def test_title_and_status_show_active_project(qapp, monkeypatch):
    _rt, _p, _ws, win = _win_with_two_projects(qapp, monkeypatch)
    assert win.windowTitle() == "JARVIS — A"
    assert "A" in win.status_label.text()  # 状态行含活动项目名


def test_empty_hint_shown_when_no_projects(qapp, monkeypatch):
    rt = _fake_runtime()
    p = GuiPresenter(rt, UiBridge())
    ws = _FakeMultiWS(p, projects=[], active=None, sessions={})
    monkeypatch.setattr(p, "session_ids", lambda: [])
    win = MainWindow(p, p.bridge, workspace=ws)
    win.show()
    qapp.processEvents()
    assert win._empty_hint.isVisible()


def test_mainwindow_with_real_controller_no_crash(qapp, monkeypatch):
    """真实 WorkspaceController（非 fake）驱动 MainWindow：防 property/方法接口不一致（active_root() 崩溃）。"""
    import shutil
    import uuid
    from types import SimpleNamespace

    d = TEST_ROOT / f"realctrl-{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True)
    proj = d / "proj"
    proj.mkdir()
    try:
        class FR:
            def __init__(self, root):
                from pathlib import Path

                root = Path(root)  # registry 里存的是 str
                # config 必须与 _fake_runtime 同套字段：MainWindow 的 120ms 补全 timer
                # 会泵进下一个测试的 qtbot 事件循环并读 config.memory_dir 等字段，
                # 缺字段 → AttributeError 被 Qt 事件循环捕获 → pytest-qt 归因给下一个测试（flaky 污染）。
                self.config = SimpleNamespace(
                    project_root=root,
                    execution_max_steps=200,
                    model_image_input="auto",
                    mcps={},
                    model_label="fake",
                    vault_path=None,
                    memory_dir=root / "memory",
                    schedules_dir=root / "schedules",
                    api_key="sk-fake",
                    base_url="https://fake.example/v1",
                    model_id="fake-model",
                    rag_ollama_base_url="http://localhost:11434",
                    rag_embed_model="bge-small-zh-v1.5",
                    checkpoint_db=root / "checkpoints.sqlite",
                )
                self.agent = None
                self.permission_state = {}
                self.mcp_tool_count = 0
                self.closed = False

            def close(self):
                self.closed = True

        reg = ProjectRegistry(d / "projects.json")
        reg.add(proj, now=1.0)
        bridge = UiBridge()
        ctrl = WorkspaceController(reg, lambda r: FR(r), bridge)
        pres = ctrl.switch_project(proj)
        assert isinstance(pres, GuiPresenter)
        monkeypatch.setattr(pres, "session_ids", lambda: [])
        win = MainWindow(pres, bridge, workspace=ctrl)
        win.show()
        qapp.processEvents()
        assert "proj" in win.windowTitle()  # 标题含活动项目名（走 controller.active_root()）
        win.close()
    finally:
        shutil.rmtree(d, ignore_errors=True)
