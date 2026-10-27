"""工单 09 — 时间旅行与上下文（快照/回放/分支/压缩；逻辑走 commands，GUI 渲染入口）。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

from langchain_core.messages import HumanMessage

from src import commands
from src.gui.events import UiBridge
from src.gui.main_window import MainWindow
from src.gui.runtime import GuiPresenter
from tests.gui_fakes import new_home, cleanup_home
from tests.test_gui_presenter import _fake_runtime, wait_until


def _fake_boundary_states():
    s1 = SimpleNamespace(
        config={"configurable": {"checkpoint_id": "aaaa1111bbbb2222"}},
        metadata={"source": "input", "step": 1},
        values={"messages": [HumanMessage(content="第一轮问题")]},
    )
    s2 = SimpleNamespace(
        config={"configurable": {"checkpoint_id": "cccc3333dddd4444"}},
        metadata={"source": "input", "step": 5},
        values={"messages": [HumanMessage(content="第二轮问题")]},
    )
    return [s1, s2]


def test_time_travel_dialog_lists_boundaries(qtbot, monkeypatch):
    from src.gui.time_travel_dialog import TimeTravelDialog

    home = new_home()
    try:
        rt = _fake_runtime()
        p = GuiPresenter(rt, UiBridge())
        monkeypatch.setattr(commands, "boundary_checkpoints", lambda agent, tid: _fake_boundary_states())
        dlg = TimeTravelDialog(p, "t-tt")
        qtbot.addWidget(dlg)
        assert dlg.checkpoint_list.count() == 2
        # 行内容 = 序号 + source + 人类标签 + 短 id
        assert "第一轮问题" in dlg.checkpoint_list.item(0).text()
        assert "aaaa1111bbbb2" in dlg.checkpoint_list.item(0).text()  # 短 id 前 13 位
        # 选中 → 全 id
        dlg.checkpoint_list.setCurrentRow(1)
        assert dlg._selected_cid() == "cccc3333dddd4444"
    finally:
        cleanup_home(home)


def test_fork_dispatch_switches_session(qtbot, monkeypatch):
    home = new_home()
    try:
        rt = _fake_runtime()
        p = GuiPresenter(rt, UiBridge())
        win = MainWindow(p, p.bridge)
        switched: list[tuple[str, str]] = []
        p.bridge.switch_session.connect(lambda t, n: switched.append((t, n)))
        monkeypatch.setattr(commands, "fork", lambda agent, tid, cid: ("已分叉", "new-branch"))
        p.run_fork("t-tt", "aaaa1111")
        assert wait_until(lambda: switched == [("new-branch", "已分叉")], timeout=10.0)
    finally:
        cleanup_home(home)


def test_fork_failure_notifies(qtbot, monkeypatch):
    home = new_home()
    try:
        rt = _fake_runtime()
        p = GuiPresenter(rt, UiBridge())
        notes: list[str] = []
        p.bridge.notify.connect(notes.append)
        monkeypatch.setattr(commands, "fork", lambda agent, tid, cid: ("分叉失败: 无", None))
        p.run_fork("t-tt", "zzz")
        assert wait_until(lambda: any("分叉失败" in n for n in notes), timeout=10.0)
    finally:
        cleanup_home(home)


def test_snapshot_and_compact_dispatch(qtbot, monkeypatch):
    home = new_home()
    try:
        rt = _fake_runtime()
        p = GuiPresenter(rt, UiBridge())
        win = MainWindow(p, p.bridge)
        calls: dict = {"snap": [], "compact": []}
        monkeypatch.setattr(
            commands, "snapshot", lambda agent, tid: calls["snap"].append(tid) or "已记录文件快照"
        )
        monkeypatch.setattr(
            commands, "compact",
            lambda agent, tid, guide=None: calls["compact"].append(guide) or "已压缩上下文",
        )
        monkeypatch.setattr(commands, "list_snapshots", lambda: "（快照列表）")
        win._switch_to("t-tt")
        win._on_snapshot()
        win._on_time_travel_dialog  # noqa（存在性）
        # 压缩走对话框：直接驱动 presenter 的 compact 分发
        p.run_command(lambda: commands.compact(rt.agent, "t-tt", "保留错误"), "t-tt")
        assert wait_until(lambda: calls["snap"] == ["t-tt"] and calls["compact"] == ["保留错误"], timeout=10.0)
    finally:
        cleanup_home(home)


def test_replay_starts_presenter_replay(qtbot, monkeypatch):
    home = new_home()
    try:
        rt = _fake_runtime()
        p = GuiPresenter(rt, UiBridge())
        win = MainWindow(p, p.bridge)
        replays: list[tuple[str, str]] = []
        monkeypatch.setattr(p, "start_replay", lambda tid, cid: replays.append((tid, cid)))
        monkeypatch.setattr(commands, "boundary_checkpoints", lambda agent, tid: _fake_boundary_states())
        from src.gui.time_travel_dialog import TimeTravelDialog

        dlg = TimeTravelDialog(p, "t-tt")
        qtbot.addWidget(dlg)
        dlg.checkpoint_list.setCurrentRow(0)
        dlg._replay()  # 不 close（offscreen），只验证分发
        assert replays == [("t-tt", "aaaa1111bbbb2222")]
    finally:
        cleanup_home(home)
