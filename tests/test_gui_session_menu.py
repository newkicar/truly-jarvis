"""会话名称栏规格（2026-10-28）：右键菜单（分享/下载/重命名/置顶/克隆/归档/删除）
+ 双击改名 + 置顶排序/归档过滤 + Markdown 导出。

Presenter 侧用 stub checkpointer 断言 copy_thread/delete_thread 契约；
MainWindow 侧走 _build_session_menu + 动作处理函数（offscreen，不模拟右键像素）。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui.events import UiBridge
from src.gui.main_window import MainWindow
from src.gui.runtime import GuiPresenter
from tests.gui_fakes import cleanup_home, new_home
from tests.test_gui_presenter import _fake_runtime


class _StubSaver:
    """GuiRuntime.checkpointer 替身：记录线程复制/删除调用。"""

    def __init__(self) -> None:
        self.copies: list[tuple[str, str]] = []
        self.deleted: list[str] = []

    def copy_thread(self, source_thread_id: str, target_thread_id: str) -> None:
        self.copies.append((source_thread_id, target_thread_id))

    def delete_thread(self, thread_id: str) -> None:
        self.deleted.append(thread_id)


# ---------------------------------------------------------------- 导出
def test_session_markdown_structure(qapp):
    from pathlib import Path
    import json as _json
    from types import SimpleNamespace

    from src.gui.session_export import session_markdown
    from src.gui.replay import Record, ToolRecord

    class _Agent:
        def get_state(self, config):
            return SimpleNamespace(values={"messages": []})

    # 直接喂记录（绕开 agent）：thread_record 无法 monkey 进函数内 import → 用真记录
    import src.gui.replay as replay_mod

    def _fake_thread_record(agent, tid, max_messages=500):
        return [
            Record("user", "帮我写个文件"),
            Record("ai", "好的。"),
            Record("tool", tool=ToolRecord("write_file", '{"path": "a.txt"}', False, "ok", 0)),
            Record("ai", "已完成。"),
        ]

    import unittest.mock as mock

    with mock.patch.object(replay_mod, "thread_record", _fake_thread_record):
        md = session_markdown(_Agent(), "t-x", "测试会话", now_text="2026-10-28 12:00")
    assert md.startswith("# 测试会话")
    assert "会话 ID：`t-x`" in md and "导出时间：2026-10-28 12:00" in md
    assert "## 你" in md and "## JARVIS" in md
    assert "### 工具：write_file" in md and "```json" in md
    assert md.index("## 你") < md.index("### 工具：write_file") < md.index("已完成。")


def test_session_markdown_empty_session(qapp):
    import src.gui.replay as replay_mod
    import unittest.mock as mock

    from src.gui.session_export import session_markdown

    class _Agent:
        def get_state(self, config):
            return None

    with mock.patch.object(replay_mod, "thread_record", lambda *a, **k: []):
        md = session_markdown(_Agent(), "t-empty", "空会话")
    assert "（空会话，无记录）" in md


# ---------------------------------------------------------------- presenter 操作
def test_presenter_clone_pin_archive_delete(qapp):
    home = new_home()
    try:
        rt = _fake_runtime()
        saver = _StubSaver()
        rt.checkpointer = saver
        p = GuiPresenter(rt, UiBridge())
        refreshed = {"n": 0}
        p.bridge.refresh_sessions.connect(lambda: refreshed.__setitem__("n", refreshed["n"] + 1))

        p.session_registry.rename("t-src", "写周报", ai_generated=False)
        note, new_tid = p.clone_session("t-src")
        assert saver.copies == [("t-src", new_tid)]
        assert "写周报-副本" in note
        assert p.session_registry.get(new_tid)["title"] == "写周报-副本"

        p.pin_session("t-src", True)
        assert p.session_registry.is_pinned("t-src") is True
        p.archive_session("t-src", True)
        assert p.session_registry.is_archived("t-src") is True
        assert refreshed["n"] >= 3  # 每次操作都发 refresh 信号

        assert "已删除" in p.delete_session("t-src")
        assert saver.deleted == ["t-src"]
        assert p.session_registry.get("t-src") is None
    finally:
        cleanup_home(home)


# ---------------------------------------------------------------- 菜单与列表
def _win(qapp, **kw):
    rt = _fake_runtime()
    p = GuiPresenter(rt, UiBridge())
    win = MainWindow(p, p.bridge, **kw)
    win.show()
    qapp.processEvents()
    return rt, p, win


def test_menu_actions_full_cycle(qapp, monkeypatch):
    rt, p, win = _win(qapp)
    rt.checkpointer = _StubSaver()
    tid = p.new_session_id()
    tid2 = p.new_session_id()
    p.session_registry.rename(tid, "原会话", ai_generated=False)
    win._switch_to(tid)
    qapp.processEvents()
    # session_ids 只有检查点线程；测试里两会话都未跑回合 → 直接钉住
    monkeypatch.setattr(p, "session_ids", lambda: [tid, tid2])

    # 置顶 → 列表前缀 ★ + 排最前
    menu = win._build_session_menu(tid)
    texts = [a.text() for a in menu.actions()]
    assert "分享（复制 Markdown 全文）" in texts and "下载 Markdown…" in texts
    assert "重命名" in texts and "置顶" in texts and "克隆会话" in texts
    assert "归档" in texts and "删除会话" in texts
    p.pin_session(tid, True)
    win.refresh_sessions()
    qapp.processEvents()
    items = [win.session_list.item(i).text() for i in range(win.session_list.count())]
    assert any("★" in t and "原会话" in t for t in items)
    assert "★" in items[0]

    # 归档（非活动会话）→ 默认隐藏
    p.session_registry.rename(tid2, "待归档")
    p.archive_session(tid2, True)
    win.refresh_sessions()
    qapp.processEvents()
    labels = [win.session_list.item(i).text() for i in range(win.session_list.count())]
    assert not any("待归档" in t for t in labels)
    # 「显示已归档会话」切回 → 出现且带 📁
    win._show_archived = True
    win.refresh_sessions()
    qapp.processEvents()
    labels = [win.session_list.item(i).text() for i in range(win.session_list.count())]
    assert any("📁" in t and "待归档" in t for t in labels)

    # 克隆 → 新会话出现在列表（-副本；真实流程中副本已在检查点，故钉入 session_ids）
    _note, new_tid = p.clone_session(tid)
    monkeypatch.setattr(p, "session_ids", lambda: [tid, tid2, new_tid])
    win.refresh_sessions()
    qapp.processEvents()
    labels = [win.session_list.item(i).text() for i in range(win.session_list.count())]
    assert any("原会话-副本" in t for t in labels)

    # 删除 → 列表移除
    p.delete_session(tid2)
    monkeypatch.setattr(p, "session_ids", lambda: [tid, new_tid])
    win.refresh_sessions()
    qapp.processEvents()
    labels = [win.session_list.item(i).text() for i in range(win.session_list.count())]
    assert not any("待归档" in t for t in labels)


def test_share_copies_markdown_to_clipboard(qapp, monkeypatch):
    rt, p, win = _win(qapp)
    tid = p.new_session_id()
    p.session_registry.rename(tid, "分享我", ai_generated=False)
    seen = {}
    monkeypatch.setattr(win, "_session_markdown_text", lambda t: "# 分享我\n\n（测试正文）")
    win._share_session_markdown(tid)
    from PySide6.QtWidgets import QApplication

    assert "（测试正文）" in QApplication.clipboard().text()


def test_download_writes_markdown_file(qapp, monkeypatch):
    rt, p, win = _win(qapp)
    tid = p.new_session_id()
    p.session_registry.rename(tid, "下载我", ai_generated=False)
    monkeypatch.setattr(win, "_session_markdown_text", lambda t: "# 下载我\n")
    out = _tmp_file()
    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getSaveFileName",
        staticmethod(lambda *a, **k: (str(out), True)),
    )
    win._download_session_markdown(tid)
    assert out.exists() and "# 下载我" in out.read_text(encoding="utf-8")
    out.unlink(missing_ok=True)


def _tmp_file():
    import uuid
    from pathlib import Path

    from tests.gui_fakes import TEST_ROOT

    return TEST_ROOT / f"dl-{uuid.uuid4().hex[:8]}.md"


def test_delete_active_session_confirms_and_switches(qapp, monkeypatch):
    rt, p, win = _win(qapp)
    saver = _StubSaver()
    rt.checkpointer = saver
    tid = p.new_session_id()
    p.session_registry.rename(tid, "活动会话", ai_generated=False)
    win._switch_to(tid)
    qapp.processEvents()

    from PySide6.QtWidgets import QMessageBox

    answers = []
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: (answers.append("ask") or QMessageBox.StandardButton.Yes)),
    )
    win._delete_session(tid)
    assert answers == ["ask"]
    assert saver.deleted == [tid]
    assert win.active_tid != tid  # 活动会话被删 → 切到新会话


# ---------------------------------------------------------------- code-review 回归
def test_export_uses_full_history_not_truncated(qapp):
    """分享/下载 = 「全部」对话内容：thread_record 必须 max_messages=None（默认 500
    条截断会把长会话截短——spec 明确要求全部）。"""
    import src.gui.replay as replay_mod
    import unittest.mock as mock

    from src.gui.session_export import session_markdown

    class _Agent:
        def get_state(self, config):
            return None

    seen = {}

    def _rec(agent, tid, max_messages=500):
        seen["mm"] = max_messages
        from src.gui.replay import Record
        return [Record("user", "u")]

    with mock.patch.object(replay_mod, "thread_record", _rec):
        session_markdown(_Agent(), "t", "t")
    assert seen["mm"] is None, f"导出被 500 条截断（max_messages={seen['mm']}）"


def test_export_fence_escaping(qapp):
    """工具参数里含 ``` 时用四反引号围栏（不死围栏）。"""
    import src.gui.replay as replay_mod
    import unittest.mock as mock

    from src.gui.replay import Record, ToolRecord
    from src.gui.session_export import session_markdown

    def _rec(agent, tid, max_messages=500):
        return [Record("tool", tool=ToolRecord("execute", "a ``` b", False, "out", 0))]

    class _Agent:
        def get_state(self, config):
            return None

    with mock.patch.object(replay_mod, "thread_record", _rec):
        md = session_markdown(_Agent(), "t", "t")
    assert "````json" in md and md.index("````json") < md.index("a ``` b") < md.rindex("````")  # 四反引号围栏包裹含 ``` 的正文


def test_clone_failure_leaves_no_ghost_session(qapp, monkeypatch):
    """copy_thread 失败 → 不落注册表（无「有名字没记录」的幽灵会话），返回错误文案。"""
    rt = _fake_runtime()
    p = GuiPresenter(rt, UiBridge())
    p.session_registry.rename("t-src", "源", ai_generated=False)

    class _BoomSaver:
        def copy_thread(self, s, d):
            raise OSError("db 忙")

    rt.checkpointer = _BoomSaver()
    note, new_tid = p.clone_session("t-src")
    assert new_tid == ""
    assert "克隆失败" in note
    assert p.session_registry.get("t-src") is not None
    assert all("副本" not in str(v) for v in p.session_registry.load().values())
