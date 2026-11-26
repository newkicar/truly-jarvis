"""工单 10 — 命令体系与补全（斜杠菜单 · @/use 补全 · 主题 · MCP · 定时任务面板）。"""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QTextCursor

from src import commands
from src.gui.events import UiBridge
from src.gui.main_window import MainWindow
from src.gui.runtime import GuiPresenter
from tests.gui_fakes import cleanup_home, new_home
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
        p.bridge.notify.connect(lambda s, t="": notes.append(s))
        win._switch_to("t-cmd")
        win._execute_slash("/sessions")
        assert wait_until(lambda: calls["raw"] == ["/sessions"], timeout=10.0)
        assert wait_until(lambda: any("/sessions" in n for n in notes), timeout=10.0)
    finally:
        cleanup_home(home)


def test_filter_commands_semantics():
    """命令菜单的「筛选」逻辑 = slash_completion.filter_commands 纯函数（菜单只是枚举展示）。"""
    from src.slash_completion import SLASH_COMMANDS, filter_commands

    assert [c.name for c in filter_commands(SLASH_COMMANDS, "comp")] == ["/compact"]
    assert len(filter_commands(SLASH_COMMANDS, "")) >= 15
    assert filter_commands(SLASH_COMMANDS, "yolo") and filter_commands(SLASH_COMMANDS, "yolo")[0].name == "/yolo"


# ---------------------------------------------------------------- 补全
def test_resolve_slash_and_use_and_at(qapp):
    from src.gui.completion import resolve_for_input
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


# ---------------------------------------------------------------- 弹层形态（2026-10-28 规格）
def test_popup_frameless_tooltip_style(qapp):
    """弹层 = Qt.Popup 无边框浮层（无标题栏/最小化/关闭按钮；点外部自动隐藏）。"""
    from PySide6.QtCore import Qt

    rt = _fake_runtime()
    p = GuiPresenter(rt, UiBridge())
    win = MainWindow(p, p.bridge)
    flags = win.completion_popup.windowFlags()
    assert flags & Qt.WindowType.Popup  # 无边框浮层：无标题栏/最小化/关闭按钮（Qt 自动合并的 hint 位不影响）


def test_popup_positions_above_input_not_covering(qapp):
    """/ 弹层底边贴输入条上沿（不挡输入框）；空间不足时翻到输入条下沿之下。"""
    rt = _fake_runtime()
    p = GuiPresenter(rt, UiBridge())
    win = MainWindow(p, p.bridge)
    win.show()
    qapp.processEvents()
    win.input_bar.edit.setPlainText("/se")
    win.input_bar.edit.moveCursor(QTextCursor.MoveOperation.End)
    win._refresh_completion()
    qapp.processEvents()
    pop = win.completion_popup
    assert pop.isVisible()
    from PySide6.QtCore import QPoint

    y_top = win.input_bar.mapToGlobal(QPoint(0, 0)).y()
    pop_bottom = pop.y() + pop.geometry().height()
    assert pop_bottom <= y_top + 1, f"弹层底边 {pop_bottom} 侵入输入条顶 {y_top}"


def test_popup_no_match_shows_hint_row(qapp, monkeypatch):
    """有查询串但零候选 → 弹层显示「No matching items」行（不隐藏）。"""
    rt = _fake_runtime()
    p = GuiPresenter(rt, UiBridge())
    win = MainWindow(p, p.bridge)
    win.show()
    qapp.processEvents()
    win.input_bar.edit.setPlainText("/definitely-no-such-cmd")
    win.input_bar.edit.moveCursor(QTextCursor.MoveOperation.End)
    win._refresh_completion()
    qapp.processEvents()
    pop = win.completion_popup
    assert pop.isVisible()
    assert pop.count() == 1
    assert pop.item(0).text() == "No matching items"
    # 删除 / 与查询串 → kind=none → 弹层消失
    win.input_bar.edit.setPlainText("")
    win._refresh_completion()
    qapp.processEvents()
    assert not pop.isVisible()


def test_popup_shows_on_slash_and_follows_typing(qapp):
    """/ 出现、随输入过滤（模糊，内核 filter_commands）、删除 / 消失。"""
    rt = _fake_runtime()
    p = GuiPresenter(rt, UiBridge())
    win = MainWindow(p, p.bridge)
    win.show()
    qapp.processEvents()
    pop = win.completion_popup
    win.input_bar.edit.setPlainText("/")
    win.input_bar.edit.moveCursor(QTextCursor.MoveOperation.End)
    win._refresh_completion()
    qapp.processEvents()
    n_all = pop.count()
    assert pop.isVisible() and n_all > 5  # 全量命令清单
    win.input_bar.edit.setPlainText("/ses")
    win.input_bar.edit.moveCursor(QTextCursor.MoveOperation.End)
    win._refresh_completion()
    qapp.processEvents()
    n_filtered = pop.count()
    assert n_filtered < n_all and n_filtered >= 1
    assert any("sessions" in pop.item(i).text() for i in range(pop.count()))


# ---------------------------------------------------------------- 弹层键盘流（2026-10-28 报障：打字被弹层抢走）
def test_popup_does_not_grab_keyboard(qapp):
    """弹层必须是 ToolTip 浮层 + NoFocus（不抢键盘：Qt.ToolTip 语义 = 抓鼠标
    不抓键盘，无标题栏/窗口按钮；旧 Qt.Popup 独占键盘 → 输入框敲一个字就
    「失联」须 Esc 才能继续打字——报障根因）。"""
    from PySide6.QtCore import Qt

    rt = _fake_runtime()
    p = GuiPresenter(rt, UiBridge())
    win = MainWindow(p, p.bridge)
    win.show()
    qapp.processEvents()
    pop = win.completion_popup
    assert pop.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert pop.windowFlags() & Qt.ToolTip  # ToolTip 语义：抓鼠标不抓键盘


def test_typing_continues_while_popup_open(qapp):
    """弹层开着时输入框仍收键：连续敲 /ses → 弹层内容随字过滤，文本持续增长
    （旧 Popup 抢键盘：敲完 /s 后第 2 个字符进不了输入框）。"""

    rt = _fake_runtime()
    p = GuiPresenter(rt, UiBridge())
    win = MainWindow(p, p.bridge)
    win.show()
    qapp.processEvents()
    edit = win.input_bar.edit
    pop = win.completion_popup

    def type_keys(text):
        for ch in text:
            edit.setPlainText(edit.toPlainText() + ch)
            edit.moveCursor(QTextCursor.MoveOperation.End)  # 模拟真实键入（光标在尾部）
            win._refresh_completion_now()
            qapp.processEvents()

    type_keys("/se")
    assert pop.isVisible() and pop.count() >= 1
    type_keys("s")
    assert edit.toPlainText() == "/ses" and pop.isVisible()  # 第 4 个字照样进框
    win.input_bar._refit()


def test_tab_accepts_top_suggestion(qapp):
    """Tab 接受弹层首项（键盘流不离开输入框；弹层未开/无候选时 Tab 走原生）。"""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    rt = _fake_runtime()
    p = GuiPresenter(rt, UiBridge())
    win = MainWindow(p, p.bridge)
    win.show()
    qapp.processEvents()
    edit = win.input_bar.edit
    edit.setPlainText("/se")
    edit.moveCursor(QTextCursor.MoveOperation.End)
    win._refresh_completion_now()
    qapp.processEvents()
    assert win.completion_popup.isVisible()
    ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Tab, Qt.KeyboardModifiers.NoModifier)
    assert win.input_bar.eventFilter(edit, ev)  # 弹层开着：Tab 被消费
    assert edit.toPlainText().startswith("/ses")  # 首项 /sessions 已插入
    assert not win.completion_popup.isVisible()


def test_tab_native_when_no_popup(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    rt = _fake_runtime()
    p = GuiPresenter(rt, UiBridge())
    win = MainWindow(p, p.bridge)
    win.show()
    qapp.processEvents()
    edit = win.input_bar.edit
    edit.setPlainText("普通文字")
    win._refresh_completion_now()
    ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Tab, Qt.KeyboardModifiers.NoModifier)
    assert not win.input_bar.eventFilter(edit, ev)  # 无弹层：Tab 放行原生换焦点


def test_esc_dismisses_popup_keeps_text(qapp):
    """Esc 关弹层（保留已输入文本）——沿用用户 Esc 习惯，但不再是「救命键」。"""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    rt = _fake_runtime()
    p = GuiPresenter(rt, UiBridge())
    win = MainWindow(p, p.bridge)
    win.show()
    qapp.processEvents()
    edit = win.input_bar.edit
    edit.setPlainText("/se")
    edit.moveCursor(QTextCursor.MoveOperation.End)
    win._refresh_completion_now()
    qapp.processEvents()
    assert win.completion_popup.isVisible()
    ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Escape, Qt.KeyboardModifiers.NoModifier)
    assert win.input_bar.eventFilter(edit, ev)
    assert not win.completion_popup.isVisible()
    assert edit.toPlainText() == "/se"


def test_completion_skills_cached_within_ttl(monkeypatch):
    """skills 目录重扫是磁盘 I/O：逐键全量重扫 = 弹层卡顿主因 → TTL 缓存。"""
    rt = _fake_runtime()
    p = GuiPresenter(rt, UiBridge())
    win = MainWindow(p, p.bridge)
    calls = {"n": 0}
    orig = p.skills_catalog

    def counting():
        calls["n"] += 1
        return orig()

    monkeypatch.setattr(p, "skills_catalog", counting)
    win._refresh_completion_now()
    win._refresh_completion_now()
    win._refresh_completion_now()
    assert calls["n"] == 1, "TTL 内应复用 skill 缓存"


def test_popup_reappears_after_dismiss_same_query(qapp):
    """回归（code-review 发现）：Esc 关掉弹层后打回同一查询串，弹层必须重新出现
    （show_items 的「候选未变跳过重建」缓存曾把 hide 态也吞掉 → 打字又失联）。"""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    rt = _fake_runtime()
    p = GuiPresenter(rt, UiBridge())
    win = MainWindow(p, p.bridge)
    win.show()
    qapp.processEvents()
    edit = win.input_bar.edit
    edit.setPlainText("/se")
    edit.moveCursor(QTextCursor.MoveOperation.End)
    win._refresh_completion_now()
    qapp.processEvents()
    assert win.completion_popup.isVisible()
    # Esc 关掉
    ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Escape, Qt.KeyboardModifiers.NoModifier)
    assert win.input_bar.eventFilter(edit, ev)
    assert not win.completion_popup.isVisible()
    # 删到 /se 再打回 /se（或 Tab 接受后退回同串）：同候选必须重显
    edit.setPlainText("/")
    edit.moveCursor(QTextCursor.MoveOperation.End)
    win._refresh_completion_now()
    qapp.processEvents()
    edit.setPlainText("/se")
    edit.moveCursor(QTextCursor.MoveOperation.End)
    win._refresh_completion_now()
    qapp.processEvents()
    assert win.completion_popup.isVisible(), "同一查询被 hide 后未重显（缓存吞掉）"


def test_popup_click_accepts_item(qapp):
    """点击候选 = 接受（mouse 流；ToolTip/NoFocus 下键盘不进气泡，点击是主路）。"""
    from PySide6.QtCore import Qt

    rt = _fake_runtime()
    p = GuiPresenter(rt, UiBridge())
    win = MainWindow(p, p.bridge)
    win.show()
    qapp.processEvents()
    edit = win.input_bar.edit
    edit.setPlainText("/se")
    edit.moveCursor(QTextCursor.MoveOperation.End)
    win._refresh_completion_now()
    qapp.processEvents()
    pop = win.completion_popup
    assert pop.count() >= 1
    first = pop.item(0)
    assert first.flags() & Qt.ItemFlag.ItemIsSelectable
    pop.itemClicked.emit(first)  # 模拟鼠标点击候选行 → _on_item_clicked → accept
    qapp.processEvents()
    assert edit.toPlainText().startswith("/ses")  # 首项已插入
    assert not pop.isVisible()

def test_accept_suggestion_at_multiline_only_touches_cursor_line(qapp):
    """gui-ux22: continuation-line @ opens path completion; accept rewrites
    only the cursor line (shared TUI kernel regression)."""
    from src.gui.completion import accept_suggestion, resolve_for_input

    home = new_home()
    try:
        rt = _fake_runtime()
        p = GuiPresenter(rt, UiBridge())
        win = MainWindow(p, p.bridge)
        edit = win.input_bar.edit
        (rt.config.project_root / "notes.md").write_text("# x", encoding="utf-8")
        edit.setPlainText("第一行\n@no")
        edit.moveCursor(QTextCursor.MoveOperation.End)  # cursor at end of line 2
        st = resolve_for_input(edit, skills=[], config=rt.config)
        assert st.kind == "path"
        sel = next(i.insert for i in st.items if "notes.md" in i.insert)
        assert accept_suggestion(edit, st, sel)
        lines = edit.toPlainText().split("\n")
        assert lines[0] == "第一行"  # line 1 untouched
        assert "notes.md" in lines[1]
    finally:
        cleanup_home(home)


def test_accept_suggestion_slash_any_position_second_line(qapp):
    """tui-ux21 (GUI): "space + /" on any line opens the command list;
    accept rewrites only the cursor line."""
    from src.gui.completion import accept_suggestion, resolve_for_input

    home = new_home()
    try:
        rt = _fake_runtime()
        p = GuiPresenter(rt, UiBridge())
        win = MainWindow(p, p.bridge)
        edit = win.input_bar.edit
        edit.setPlainText("第一行\n第二 /comp")
        edit.moveCursor(QTextCursor.MoveOperation.End)
        st = resolve_for_input(edit, skills=[], config=rt.config)
        assert st.kind == "slash"
        sel = next(i.insert for i in st.items if "compact" in i.insert)
        assert accept_suggestion(edit, st, sel)
        lines = edit.toPlainText().split("\n")
        assert lines[0] == "第一行"
        assert lines[1].startswith("第二 /compact")
    finally:
        cleanup_home(home)


# ---------------------------------------------------------------- gui-ux24: 真实 Windows 光标块失步回归
class _DesyncCursor:
    """模拟真实 Windows 上失步的 QPlainTextEdit textCursor：
    position() 正确（绝对文档位置），blockNumber() 误报 0、
    positionInBlock() 返回绝对位置（gui-ux24 探针实证）。"""

    def __init__(self, text, pos):
        self._text = text
        self._pos = pos

    def position(self):
        return self._pos

    def blockNumber(self):
        return 0  # 误报：永远第一块

    def positionInBlock(self):
        return self._pos  # 误报：绝对位置非块内相对


class _DesyncEdit:
    """伪 QPlainTextEdit：toPlainText() 正确 + 光标失步。
    rowcol_from_cursor 须完全不感知 blockNumber/positionInBlock。"""

    def __init__(self, text, pos):
        self._text = text
        self._cursor = _DesyncCursor(text, pos)

    def toPlainText(self):
        return self._text

    def textCursor(self):
        return self._cursor


def test_rowcol_from_cursor_immune_to_block_desync():
    """gui-ux24: blockNumber 误报 0（真实 Windows Shift+Enter 怪癖）时，
    (row, col) 推导仍以绝对位置为准。"""
    from src.gui.completion import rowcol_from_cursor

    text = "第一行\n@no"  # 7 字符（第一行 3 + \n 1 + @no 3）
    assert rowcol_from_cursor(_DesyncEdit(text, 7)) == (1, 3)  # 第二行行尾
    assert rowcol_from_cursor(_DesyncEdit(text, 4)) == (1, 0)  # 第二行行首（@ 处）
    assert rowcol_from_cursor(_DesyncEdit(text, 1)) == (0, 1)  # 第一行中间
    assert rowcol_from_cursor(_DesyncEdit("no", 0)) == (0, 0)
    assert rowcol_from_cursor(_DesyncEdit("no", 2)) == (0, 2)
    assert rowcol_from_cursor(_DesyncEdit("a\nb\nc", 4)) == (2, 0)


def test_desync_continuation_at_and_slash_resolve():
    """gui-ux24: 用户症状「换行后 @ 和 / 都不好使」回归——光标失步
    （blockNumber 卡 0）时，续行 @ / 与第一行同等触发（GUI 弹层唯一
    数据源 = resolve_for_input）。"""
    from src.gui.completion import resolve_for_input

    home = new_home()
    try:
        rt = _fake_runtime()
        (rt.config.project_root / "notes.md").write_text("# x", encoding="utf-8")
        text = "第一行\n@no"
        st = resolve_for_input(_DesyncEdit(text, len(text)), skills=[], config=rt.config)
        assert st.kind == "path"
        assert any("notes.md" in i.insert for i in st.items)
        text2 = "第一行\n第二 /comp"
        st2 = resolve_for_input(_DesyncEdit(text2, len(text2)), skills=[], config=rt.config)
        assert st2.kind == "slash"
    finally:
        cleanup_home(home)


def test_desync_has_query_no_match():
    """gui-ux24: 失步下「No matching items」判定（用户确实输入了查询串）
    亦不错读。"""
    from src.gui.completion import has_query_no_match, resolve_for_input

    home = new_home()
    try:
        rt = _fake_runtime()
        (rt.config.project_root / "notes.md").write_text("# x", encoding="utf-8")
        text = "第一行\n@zzz"  # 无匹配候选
        st = resolve_for_input(_DesyncEdit(text, len(text)), skills=[], config=rt.config)
        assert st.kind == "path" and not st.items
        assert has_query_no_match(_DesyncEdit(text, len(text)), st)
        text2 = "第一行\n@"  # 空查询 = 全量清单，不算无匹配
        st2 = resolve_for_input(_DesyncEdit(text2, len(text2)), skills=[], config=rt.config)
        assert st2.kind == "path" and st2.items
        assert not has_query_no_match(_DesyncEdit(text2, len(text2)), st2)
    finally:
        cleanup_home(home)


# ---------------------------------------------------------------- gui-ux25: /use 任意位置泛化（对齐 tui-ux24 内核）
def test_use_skill_multiline_any_position(qapp):
    """gui-ux25: 续行/句中「空格 + /use」触发 skill 补全（对齐 tui-ux24 内核）；
    Tab 接受只改光标行（共享内核回归，与 @ / 的 gui-ux22 用例同族）。"""
    from src.gui.completion import accept_suggestion, resolve_for_input
    from src.skill_discovery import SkillMeta

    home = new_home()
    try:
        rt = _fake_runtime()
        p = GuiPresenter(rt, UiBridge())
        win = MainWindow(p, p.bridge)
        edit = win.input_bar.edit
        edit.setPlainText("第一行\n句中 /use ")
        edit.moveCursor(QTextCursor.MoveOperation.End)  # 光标在续行行尾
        skills = [
            SkillMeta(
                name="book-meeting-room",
                description="订会议室",
                virtual_path="/workspace/skills/book-meeting-room/SKILL.md",
                layer="project",
            )
        ]
        st = resolve_for_input(edit, skills=skills, config=rt.config)
        assert st.kind == "skill"
        assert st.at_index == 8  # 行内偏移：「句中 」3 + 「/use 」5
        sel = next(i.insert for i in st.items if "book-meeting-room" in i.insert)
        assert accept_suggestion(edit, st, sel)
        lines = edit.toPlainText().split("\n")
        assert lines[0] == "第一行"  # 其它行未动
        assert lines[1].startswith("句中 /use book-meeting-room")
    finally:
        cleanup_home(home)


def test_skill_single_char_no_match_popup_shows_hint_row(qapp, monkeypatch):
    """gui-ux25 回归（has_query_no_match skill kind off-by-one）：skill 查询
    单字符无匹配时弹层须显示「No matching items」行而非整体消失
    （旧代码 at_index+1 跳过 query 首字符 → 空串误判 → 静默无反馈）。"""
    from src.gui.completion import has_query_no_match, resolve_for_input
    from src.skill_discovery import SkillMeta

    rt = _fake_runtime()
    p = GuiPresenter(rt, UiBridge())
    monkeypatch.setattr(
        p, "skills_catalog",
        lambda: [
            SkillMeta(
                name="alpha",
                description="",
                virtual_path="/workspace/skills/alpha/SKILL.md",
                layer="project",
            )
        ],
    )
    win = MainWindow(p, p.bridge)
    win.show()
    qapp.processEvents()
    edit = win.input_bar.edit
    edit.setPlainText("/use z")  # z 对 alpha 四档模糊全不中 → 候选为空
    edit.moveCursor(QTextCursor.MoveOperation.End)
    win._refresh_completion_now()
    qapp.processEvents()
    pop = win.completion_popup
    st = resolve_for_input(edit, skills=p.skills_catalog(), config=rt.config)
    assert st.kind == "skill" and not st.items
    assert has_query_no_match(edit, st)
    assert pop.isVisible()
    assert pop.count() == 1
    assert pop.item(0).text() == "No matching items"
