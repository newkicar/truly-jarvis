"""工单 01 — GUI 运行时装配（build_runtime / 检查点持久化 / permission_state 共享）。

用 fake home（jarvis.json + .env）+ ScriptedMockModel，不触网、不碰真实模型。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.gui_fakes import cleanup_home, new_home, ScriptedMockModel


def _build(home, model=None, **kw):
    from src.gui.runtime import build_runtime_for_config

    return build_runtime_for_config(home, model=model, **kw)


def test_build_runtime_persists_checkpoints():
    home = new_home()
    try:
        rt = _build(home, model=ScriptedMockModel())
        assert rt.agent is not None
        assert rt.config.checkpoint_db.parent.exists()
        assert rt.permission_state is not None
        assert rt.mcp_tool_count == 0
        # scheduler 默认关（遗留 d）
        assert rt.gate.enabled is False
        assert rt.gate.jobs() == []
        rt.close()
        assert rt.config.checkpoint_db.parent.exists()  # 关连接不删文件
    finally:
        cleanup_home(home)


def test_runtime_closes_connection_cleanly():
    home = new_home()
    try:
        rt = _build(home, model=ScriptedMockModel())
        rt.close()
        # 再次 close 幂等（saver_ctx 已清）
        rt.close()
    finally:
        cleanup_home(home)


def test_scheduler_gate_on_demand():
    home = new_home()
    try:
        rt = _build(home, model=ScriptedMockModel(), enable_scheduled=True)
        assert rt.gate.enabled is True
        rt.close()
    finally:
        cleanup_home(home)


def test_default_ask_rejects_without_card():
    from src.gui.events import UiBridge
    from src.gui.runtime import GuiPresenter

    home = new_home()
    try:
        rt = _build(home, model=ScriptedMockModel())
        p = GuiPresenter(rt, UiBridge())
        inv = type("I", (), {"name": "execute", "args": {"command": "x"}, "path": None})()
        assert p._default_ask(inv, "t1") == {"decision": "reject"}
    finally:
        cleanup_home(home)
