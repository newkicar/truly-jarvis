"""工单 10 — 命令体系与补全（斜杠菜单 · @/use 补全 · 主题 · MCP · 定时任务面板）。"""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QTextCursor

from src import commands
from src.gui.events import UiBridge
from src.gui.main_window import MainWindow
from src.gui.runtime import GuiPresenter
from tests.gui_fakes import new_home, cleanup_home
from tests.test_gui_presenter import _fake_runtime, wait_until


# ---------------------------------------------------------------- 斜杠命令执行
def test_execute_slash_dispatches_and_notifies(qapp, monkeypatch):
    home = new_home()
    try:
        rt = _fake_runtime()
        p = GuiPresenter(rt, UiBridge())
        win = MainWindow(p, p.bridge)
        calls = {"raw": []}
        monkeypatch.setattr(
            commands, "dispatch_command",
            lambda agent, tid, raw, sched=None, vault_path=None, **k: (
                calls["raw"].append(raw) or "/sessions 列表", None, None
            ),
        )
        notes: list[str] = []
        p.bridge.notify.connect(notes.append)
        win._switch_to("t-cmd")
        win._execute_slash("/sessions")
        assert wait_until(lambda: calls["raw"] == ["/sessions"], timeout=10.0)
        assert wait_until(lambda: any("/sessions" in n for n in notes), timeout=10.0)
    finally:
        cleanup_home(home)


def test_filter_commands_semantics():
    """命令菜单的「筛选」逻辑 = slash_completion.filter_commands 纯函数（菜单只是枚举展示）。"""
    from src.slash_completion import filter_commands, SLASH_COMMANDS

    assert [c.name for c in filter_commands(SLASH_COMMANDS, "comp")] == ["/compact"]
    assert len(filter_commands(SLASH_COMMANDS, "")) >= 15
    assert filter_commands(SLASH_COMMANDS, "yolo") and filter_commands(SLASH_COMMANDS, "yolo")[0].name == "/yolo"


# ---------------------------------------------------------------- 补全
def test_resolve_slash_and_use_and_at(qapp):
    from src.gui.completion import resolve_for_input
    from src.gui.input_bar import InputBar
    from src.skill_discovery import SkillMeta

    home = new_home()
    try:
        rt = _fake_runtime()
        p = GuiPresenter(rt, UiBridge())
        win = MainWindow(p, p.bridge)
        edit = win.input_bar.edit

        edit.setPlainText("/se")
        edit.moveCursor(QTextCursor.MoveOperation.End)  # 模拟敲完在行尾
        st = resolve_for_input(edit, skills=[], config=rt.config)
        assert st.kind == "slash" and any("sessions" in i.insert for i in st.items)

        skills = [
            SkillMeta(
                name="book-meeting-room",
                description="订会议室",
                virtual_path="/workspace/skills/book-meeting-room/SKILL.md",
                layer="project",
            )
        ]
        edit.setPlainText("/use bkmtg")
        edit.moveCursor(QTextCursor.MoveOperation.End)
        st = resolve_for_input(edit, skills=skills, config=rt.config)
        assert st.kind == "skill"
        assert any("book-meeting-room" in i.insert for i in st.items)

        # @ 路径补全（workspace 优先）——文件建在 runtime 的 project_root
        (rt.config.project_root / "notes.md").write_text("# x", encoding="utf-8")
        edit.setPlainText("@no")
        edit.moveCursor(QTextCursor.MoveOperation.End)
        st = resolve_for_input(edit, skills=[], config=rt.config)
        assert st.kind == "path"
        assert any("notes.md" in i.insert for i in st.items)
    finally:
        cleanup_home(home)


def test_accept_suggestion_only_touches_cursor_line(qapp):
    from src.gui.completion import accept_suggestion, resolve_for_input
    from src.gui.input_bar import InputBar

    home = new_home()
    try:
        rt = _fake_runtime()
        p = GuiPresenter(rt, UiBridge())
        win = MainWindow(p, p.bridge)
        edit = win.input_bar.edit
        edit.setPlainText("第一行\n/com")
        # 光标放第二行行尾（行内补全只看光标行）
        edit.moveCursor(QTextCursor.MoveOperation.End)
        st = resolve_for_input(edit, skills=[], config=rt.config)
        assert st.kind == "slash"
        ok = accept_suggestion(edit, st, st.items[0].insert)
        assert ok
        lines = edit.toPlainText().split("\n")
        assert lines[0] == "第一行"  # 其它行未动
        assert lines[1].startswith("/compact")
    finally:
        cleanup_home(home)


# ---------------------------------------------------------------- 主题
def test_theme_toggle_persists_and_applies(qapp, monkeypatch):
    from src.gui import theme

    home = new_home()
    d = home / "gui"
    d.mkdir()
    monkeypatch.setenv("JARVIS_GUI_HOME", str(d))
    try:
        app = qapp
        assert theme.load_theme(d) == "dark"  # 缺省
        nxt = theme.toggle_theme(d)
        assert nxt == "light"
        assert theme.load_theme(d) == "light"
        theme.apply_theme(app, "light")
        assert "color: #1a1a1a" in app.styleSheet()
        theme.apply_theme(app, "dark")
        assert "color: #e8e8e8" in app.styleSheet()
    finally:
        monkeypatch.delenv("JARVIS_GUI_HOME", raising=False)
        cleanup_home(home)


# ---------------------------------------------------------------- MCP 菜单
def test_mcp_menu_readonly_list(qapp):
    from PySide6.QtWidgets import QMenu

    home = new_home()
    try:
        rt = _fake_runtime()
        p = GuiPresenter(rt, UiBridge())
        # 换成带 mcps 的 config（presenter 建好后再换，避免 registry 读 project_root 缺失）
        rt.config.mcps = {
            "git": {"type": "local", "command": ["git-mcp"], "enabled": True},
            "docs": {"type": "remote", "url": "http://x", "enabled": False},
        }
        win = MainWindow(p, p.bridge)
        menu = QMenu()
        win._build_mcp_menu(menu)
        texts = [a.text() for a in menu.actions() if a.text()]
        assert any("git" in t and "启用" in t for t in texts)
        assert any("docs" in t and "停用" in t for t in texts)
        assert all(not a.isEnabled() for a in menu.actions() if a.text().startswith(("git", "docs")))
    finally:
        cleanup_home(home)


# ---------------------------------------------------------------- 定时任务面板
def test_scheduler_panel_toggle_writes_back(qapp):
    from src.gui.scheduler_panel import SchedulerPanel, load_task_rows, set_task_enabled

    home = new_home()
    sched = home / "schedules"
    sched.mkdir()
    f1 = sched / "daily.json"
    f1.write_text(json.dumps({"id": "daily", "task": "日报", "cron": "0 8 * * *",
                              "save_path": "vault:Inbox/", "enabled": True}), encoding="utf-8")
    (sched / "example.json.example")  # 不存在（skip 逻辑只需无该文件）
    f1b = sched / "off.json"
    f1b.write_text(json.dumps({"id": "off", "task": "停", "cron": "*/5 * * * *",
                               "enabled": False}), encoding="utf-8")

    rows = load_task_rows(sched)
    assert {r["name"] for r in rows} == {"daily", "off"}
    assert [r["enabled"] for r in rows if r["name"] == "daily"] == [True]

    # 面板勾选态映射
    home2 = home
    rt = _fake_runtime()
    rt.config.schedules_dir = sched
    p = GuiPresenter(rt, UiBridge())
    panel = SchedulerPanel(p)
    assert len(panel._rows) == 2

    set_task_enabled(f1, False)
    data = json.loads(f1.read_text(encoding="utf-8"))
    assert data["enabled"] is False and data["task"] == "日报"  # 其余字段保留


def test_scheduler_gate_reload_disabled_gives_hint():
    home = new_home()
    try:
        rt = _fake_runtime()  # gate.enabled = False（未 --scheduled）
        text = rt.gate.reload()
        assert "未启用" in text
        rt.gate.enabled  # property 存在
    finally:
        cleanup_home(home)
