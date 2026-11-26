"""Issue #7 — GUI 状态行双层显示：一次性通知最高优先顶出，常驻状态为回落层。

验收条件（#7）：
(a) goal 族等命令回复立即顶出在所属槽状态行；
(b) 一次性通知消失条件 = 下一回合结束 或 下一个常驻状态事件 → 回落常驻层
    （goal 行 / 会话行 / 就绪）；
(c) TUI 已核查，无同类压制（TUI 的 notify 是 Textual 单通道，不存在状态行被
    常驻层覆写的问题），不动 TUI。

Seam：UiBridge.notify Signal(str,str) 按 tid 路由到主/侧槽 + MainWindow 双层
状态行（_slot_persistent 常驻层 / _slot_oneshot 一次性层）+ _on_status 门放宽
到槽 tid + _on_turn_done 成功重申常驻层 / 失败回落 + _command_worker 带 tid
只发一次（空结果零 notify）。offscreen Qt，纯内存 + 自建 goals.json 目录
（本机 pytest 基 temp 目录 WinError 5 中毒纪律：禁用 tmp_path/tempfile，
.scratch 下 os.makedirs 自建）。
"""
import os
import shutil
import uuid
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src import commands, goals
from src.gui.events import UiBridge
from src.gui.main_window import MainWindow
from src.gui.runtime import GuiPresenter
from tests.test_gui_presenter import _fake_runtime

# goals.json 自建落盘点（tmp_path 中毒纪律，.scratch 已 gitignore）
BASE = Path(__file__).resolve().parent.parent / ".scratch" / "gui-issue7-tmp"


@pytest.fixture()
def goal_store(monkeypatch):
    base = str(BASE / uuid.uuid4().hex[:12])
    os.makedirs(base, exist_ok=True)
    target = Path(base) / "goals.json"
    monkeypatch.setattr(goals, "goals_path", lambda: target)
    yield target
    shutil.rmtree(base, ignore_errors=True)


def _win(qapp, monkeypatch, record: list, side: bool = False):
    """双槽 MainWindow + notify/status 全量记录（notify 2-arg 连接 = RED 判据）。"""
    rt = _fake_runtime()
    p = GuiPresenter(rt, UiBridge())
    win = MainWindow(p, p.bridge)
    win.active_tid = "t-1"
    win._main_slot_tid = "t-1"
    if side:
        monkeypatch.setattr(p, "is_side", lambda tid: tid == "side-1")
        win._side_slot_tid = "side-1"
    win.bridge.notify.connect(lambda s, t: record.append(("notify", s, t)))
    win.bridge.status.connect(lambda t, s: record.append(("status", t, s)))
    return win


# ---------- (a) 一次性通知顶出在所属槽状态行 ----------
def test_notify_one_shot_sits_on_top(qapp, monkeypatch):
    record: list = []
    win = _win(qapp, monkeypatch, record)
    win.bridge.status.emit("t-1", "持久文案")
    win.bridge.notify.emit("一次性回复", "t-1")
    assert win._slot_status("main").text() == "一次性回复"


def test_side_slot_symmetry(qapp, monkeypatch):
    record: list = []
    win = _win(qapp, monkeypatch, record, side=True)
    win.bridge.status.emit("t-1", "主线常驻")
    win.bridge.status.emit("side-1", "侧线常驻")
    win.bridge.notify.emit("侧线一次性", "side-1")
    assert win._slot_status("side").text() == "侧线一次性"
    assert win._slot_status("main").text() == "主线常驻"


# ---------- (b) 常驻写入清空一次性层 ----------
def test_persistent_write_clears_one_shot(qapp, monkeypatch):
    record: list = []
    win = _win(qapp, monkeypatch, record)
    win.bridge.notify.emit("一次性", "t-1")
    assert win._slot_status("main").text() == "一次性"
    win.bridge.status.emit("t-1", "持久")
    assert win._slot_status("main").text() == "持久"
    assert win._slot_oneshot["main"] == ""


def test_empty_tid_notify_lands_in_main(qapp, monkeypatch):
    record: list = []
    win = _win(qapp, monkeypatch, record, side=True)
    win.bridge.status.emit("side-1", "侧线常驻")
    win.bridge.notify.emit("主槽文案", "")
    assert win._slot_status("main").text() == "主槽文案"
    assert win._slot_status("side").text() == "侧线常驻"


# ---------- (a) 命令回复一次带 tid（空结果零 notify）----------
def test_command_worker_empty_result_zero_notify(qapp, monkeypatch):
    record: list = []
    win = _win(qapp, monkeypatch, record)
    win.presenter._command_worker(lambda: "", "t-1")
    assert [r for r in record if r[0] == "notify"] == []


def test_command_worker_notifies_once_with_tid(qapp, monkeypatch):
    record: list = []
    win = _win(qapp, monkeypatch, record)
    win.presenter._command_worker(lambda: "文本", "t-1")
    assert [r for r in record if r[0] == "notify"] == [("notify", "文本", "t-1")]


def test_command_worker_failure_notifies_with_tid(qapp, monkeypatch):
    record: list = []
    win = _win(qapp, monkeypatch, record)

    def boom():
        raise RuntimeError("boom")

    win.presenter._command_worker(boom, "t-1")
    assert [r for r in record if r[0] == "notify"] == [("notify", "命令失败: boom", "t-1")]


def test_goal_slash_reply_flows_once_via_worker(qapp, monkeypatch, goal_store):
    record: list = []
    win = _win(qapp, monkeypatch, record)
    p = win.presenter
    monkeypatch.setattr(commands, "dispatch_command", lambda *a, **kw: ("已处理", None, None))
    monkeypatch.setattr(p, "run_command", lambda fn, tid: p._command_worker(fn, tid))
    kicks: list = []
    monkeypatch.setattr(p, "start_turn", lambda tid, kick, **kw: kicks.append((tid, kick)) or "started")
    goals.goal_set(thread_id="t-1", objective="测试目标")

    win._execute_slash("/goal status", "t-1")

    # 命令回复只发一次（旧 bug：_execute_slash 直接 emit + worker 空串 emit = 双发/串槽）
    assert [r for r in record if r[0] == "notify"] == [("notify", "已处理", "t-1")]
    # 常驻层 = 目标行（一次性回复顶出之下）
    expected_goal = commands.goal_text("t-1")
    assert win._slot_persistent["main"] == expected_goal
    assert ("status", "t-1", expected_goal) in record
    # 最终槽文本 = 一次性回复「已处理」（顶在目标行之上）
    assert win._slot_status("main").text() == "已处理"
    # /goal status 无 kick（不重启目标链）
    assert kicks == []


# ---------- (b) 回合结束：有 goal 重申常驻层；无 goal 一次性失效回落 ----------
def test_turn_done_reasserts_goal_persistent(qapp, monkeypatch, goal_store):
    record: list = []
    win = _win(qapp, monkeypatch, record)
    goals.goal_set(thread_id="t-1", objective="测试目标")
    win.bridge.status.emit("t-1", "会话 t-1")
    win.bridge.notify.emit("回合完成（0.5s）", "t-1")
    assert win._slot_status("main").text() == "回合完成（0.5s）"
    win.bridge.turn_done.emit("t-1", True)
    assert win._slot_status("main").text() == commands.goal_text("t-1")


def test_turn_done_without_goal_falls_back_persistent(qapp, monkeypatch, goal_store):
    record: list = []
    win = _win(qapp, monkeypatch, record)
    win.bridge.status.emit("t-1", "持久基线")
    win.bridge.turn_done.emit("t-1", False)
    assert win._slot_oneshot["main"] == ""
    assert win._slot_status("main").text() == "持久基线"
    # 错误路径：错误一次性通知随后顶出并保留可见
    win.bridge.notify.emit("错误文案", "t-1")
    assert win._slot_status("main").text() == "错误文案"
    assert win._slot_persistent["main"] == "持久基线"
