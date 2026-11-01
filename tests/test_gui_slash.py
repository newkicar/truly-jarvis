"""工单 07 — GUI 输入框 slash 路由：/xxx 走本地命令分发，虚拟路径引用仍发模型。

对标 TUI _handle_user_message 的三分法：普通文本 / slash 命令 / 虚拟路径引用。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src import commands
from src.gui.events import UiBridge
from src.gui.main_window import MainWindow
from src.gui.runtime import GuiPresenter
from tests.test_gui_presenter import _fake_runtime


def _win(qapp, monkeypatch, record: list) -> MainWindow:
    rt = _fake_runtime()
    p = GuiPresenter(rt, UiBridge())
    win = MainWindow(p, p.bridge)
    win.active_tid = "t-1"
    monkeypatch.setattr(
        win, "_execute_slash", lambda raw: record.append(("slash", raw))
    )
    monkeypatch.setattr(
        win.presenter,
        "start_turn",
        lambda tid, text, **kw: record.append(("turn", tid, text)) or "started",
    )
    return win


def test_plain_text_goes_to_model(qapp, monkeypatch):
    record: list = []
    win = _win(qapp, monkeypatch, record)
    win._on_input_submit("你好，读一下 README")
    assert ("turn", "t-1", "你好，读一下 README") in record
    assert not [r for r in record if r[0] == "slash"]


def test_slash_command_routes_to_dispatch(qapp, monkeypatch):
    record: list = []
    win = _win(qapp, monkeypatch, record)
    win._on_input_submit("/sessions")
    assert ("slash", "/sessions") in record
    assert not [r for r in record if r[0] == "turn"]


def test_slash_with_args_routes_to_dispatch(qapp, monkeypatch):
    record: list = []
    win = _win(qapp, monkeypatch, record)
    win._on_input_submit("/replay abc123")
    assert ("slash", "/replay abc123") in record


def test_use_command_expands_and_streams(qapp, monkeypatch):
    record: list = []
    win = _win(qapp, monkeypatch, record)
    monkeypatch.setattr(
        commands, "expand_use_command", lambda cfg, text: ("[skill:pdf] 读一下", None)
    )
    pane = win._ensure_pane("t-1")
    bubbles: list = []
    monkeypatch.setattr(
        pane, "append_user", lambda text, images: bubbles.append(text)
    )
    win._on_input_submit("/use pdf 读一下")
    assert ("turn", "t-1", "[skill:pdf] 读一下") in record
    assert "/use pdf 读一下" in bubbles
    assert not [r for r in record if r[0] == "slash"]


def test_use_unknown_skill_shows_error(qapp, monkeypatch):
    record: list = []
    win = _win(qapp, monkeypatch, record)
    monkeypatch.setattr(
        commands, "expand_use_command", lambda cfg, text: (None, "未找到 skill「nope」")
    )
    win._on_input_submit("/use nope")
    assert "未找到 skill「nope」" in win.status_label.text()
    assert not record


def test_doctor_routes_to_dialog(qapp, monkeypatch):
    record: list = []
    win = _win(qapp, monkeypatch, record)
    monkeypatch.setattr(win, "_on_doctor", lambda: record.append(("doctor",)))
    win._on_input_submit("/doctor")
    assert ("doctor",) in record
    assert not [r for r in record if r[0] == "slash"]


def test_doctor_with_args_routes_to_dialog(qapp, monkeypatch):
    record: list = []
    win = _win(qapp, monkeypatch, record)
    monkeypatch.setattr(win, "_on_doctor", lambda: record.append(("doctor",)))
    win._on_input_submit("/doctor 完整检查")
    assert ("doctor",) in record
    assert not [r for r in record if r[0] == "slash"]


def test_notify_flattens_multiline(qapp, monkeypatch):
    record: list = []
    win = _win(qapp, monkeypatch, record)
    win._on_notify("报告\n第二行\r\n第三行")
    assert win.status_label.text() == "报告 第二行 第三行"


def test_doctor_guard_without_presenter(qapp, monkeypatch):
    win = MainWindow.__new__(MainWindow)
    # 空态守卫：_presenter None 时只写状态栏不崩溃
    from PySide6.QtWidgets import QLabel
    win.presenter = None
    win.status_label = QLabel()
    win._on_doctor()
    assert "还没有关联项目" in win.status_label.text()


def test_virtual_path_reference_stays_model(qapp, monkeypatch):
    record: list = []
    win = _win(qapp, monkeypatch, record)
    win._on_input_submit("/workspace/a.txt")
    assert ("turn", "t-1", "/workspace/a.txt") in record
    assert not [r for r in record if r[0] == "slash"]


# ---- /help 与 /exit 特判 + 命令菜单同路由 + 全命令零「未知命令」回归


def _win_live(qapp, monkeypatch, record: list) -> MainWindow:
    """全链路活路由：不 mock _execute_slash；dispatch 同步执行、结果入 record（探针同款接线）。"""
    rt = _fake_runtime()
    p = GuiPresenter(rt, UiBridge())
    win = MainWindow(p, p.bridge)
    win.active_tid = "t-1"

    def sync_run_command(fn, tid):
        try:
            result = fn()
        except Exception as exc:
            result = f"命令失败: {exc}"
        record.append(result or "")

    monkeypatch.setattr(p, "run_command", lambda fn, tid: sync_run_command(fn, tid))
    monkeypatch.setattr(
        p, "start_turn", lambda tid, text, **kw: record.append(text) or "started"
    )
    monkeypatch.setattr(win, "_on_doctor", lambda: record.append("(doctor)"))
    # /init 会确定性生成 JARVIS.md：测试不落真实文件
    monkeypatch.setattr(commands, "init_project", lambda: "INIT_MATCHED")
    return win


def test_help_routes_to_dialog(qapp, monkeypatch):
    record: list = []
    win = _win(qapp, monkeypatch, record)
    shown: list = []
    monkeypatch.setattr(win, "_show_text", lambda title, text: shown.append((title, text)))
    win._on_input_submit("/help")
    assert len(shown) == 1
    title, body = shown[0]
    assert "命令帮助" in title
    assert "/sessions" in body
    assert not [r for r in record if isinstance(r, tuple) and r[0] == "slash"]


def test_exit_closes_window(qapp, monkeypatch):
    record: list = []
    win = _win(qapp, monkeypatch, record)
    closed: list = []
    monkeypatch.setattr(win, "close", lambda: closed.append(1))
    win._on_input_submit("/exit")
    assert closed
    assert "正在退出" in win.status_label.text()
    assert not [r for r in record if isinstance(r, tuple) and r[0] == "slash"]


def test_command_menu_routes_like_input(qapp, monkeypatch):
    """「命令」菜单 /xxx 走同 _route_slash 路由（/help 对话框、/exit 关窗、/doctor 卡片）。"""
    from PySide6.QtWidgets import QMenu

    record: list = []
    win = _win(qapp, monkeypatch, record)
    shown: list = []
    closed: list = []
    monkeypatch.setattr(win, "_show_text", lambda title, text: shown.append((title, text)))
    monkeypatch.setattr(win, "close", lambda: closed.append(1))
    monkeypatch.setattr(win, "_on_doctor", lambda: record.append("(doctor)"))
    menu = QMenu(win)
    win._build_command_menu(menu)
    by_usage = {a.text(): a for a in menu.actions()}

    by_usage["/help"].trigger()
    assert shown and "命令帮助" in shown[0][0]

    by_usage["/exit"].trigger()
    assert closed

    by_usage["/doctor"].trigger()
    assert "(doctor)" in record
    assert not [r for r in record if isinstance(r, tuple) and r[0] == "slash"]

    by_usage["/sessions"].trigger()
    assert ("slash", "/sessions") in record


def test_route_slash_guard_without_presenter(qapp):
    win = MainWindow.__new__(MainWindow)
    from PySide6.QtWidgets import QLabel

    win.presenter = None
    win.status_label = QLabel()
    assert win._route_slash("/sessions") is True
    assert "还没有关联项目" in win.status_label.text()


def test_all_slash_commands_no_unknown(qapp, monkeypatch):
    """回归：SLASH_COMMANDS 全部命令走真实 GUI 路由，零「未知命令」。"""
    from src.slash_completion import SLASH_COMMANDS

    argv = {
        "/yolo": "/yolo on",
        "/replay": "/replay abc123",
        "/fork": "/fork abc123",
        "/rollback": "/rollback abc123",
    }
    record: list = []
    win = _win_live(qapp, monkeypatch, record)
    shown: list = []
    monkeypatch.setattr(win, "_show_text", lambda t, x: shown.append((t, x)))
    bad: list = []
    for c in SLASH_COMMANDS:
        record.clear()
        raw = argv.get(c.name, c.name)
        win._on_input_submit(raw)
        if any("未知命令" in str(item) for item in record):
            bad.append(c.name)
    assert not bad, f"落入未知命令的命令: {bad}"
