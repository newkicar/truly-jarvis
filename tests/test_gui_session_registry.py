"""工单 05 — 会话注册表 + AI 命名（纯逻辑 + offscreen 后台命名）。"""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui.session_registry import (
    SessionRegistry,
    clean_name_reply,
    generate_session_name,
    registry_path,
    session_naming_prompt,
)


def _tmp_dir():
    import uuid

    from tests.gui_fakes import TEST_ROOT

    d = TEST_ROOT / f"reg-{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True)
    return str(d)


def test_registry_path():
    from pathlib import Path

    assert registry_path(Path("/p")) == Path("/p/sessions.json")


def test_registry_roundtrip():
    from pathlib import Path

    d = _tmp_dir()
    r = SessionRegistry(Path(d) / "sessions.json")
    assert r.get("t1") is None
    r.rename("t1", "修复登录 401", ai_generated=True)
    assert r.get("t1") == {"title": "修复登录 401", "ai_generated": True}
    raw = json.loads((Path(d) / "sessions.json").read_text(encoding="utf-8"))
    assert raw["t1"]["ai_generated"] is True
    r.rename("t2", "手改", ai_generated=False)
    assert r.get("t2")["ai_generated"] is False
    r.delete("t1")
    assert r.get("t1") is None and r.get("t2") is not None


def test_registry_corrupt_falls_back_empty():
    from pathlib import Path

    p = Path(_tmp_dir()) / "sessions.json"
    p.write_text("{broken", encoding="utf-8")
    r = SessionRegistry(p)
    assert r.load() == {}
    assert r.get("x") is None


def test_label_priority_short_name_over_summary():
    class _Agent:
        def __init__(self, fallback):
            self._fb = fallback

    # label(agent, tid)：注册表短名优先，无则 commands.session_label（用 fake agent 触发）
    import types

    from pathlib import Path

    r = SessionRegistry(Path("unused"))
    r.rename("t9", "短名")

    class Agent:
        pass

    # monkeypatch commands.session_label 避免真查检查点
    import src.commands as commands

    orig = commands.session_label
    commands.session_label = lambda agent, tid: "回落摘要"
    try:
        assert r.label(Agent(), "t9") == "短名"
        assert r.label(Agent(), "tNo") == "回落摘要"
    finally:
        commands.session_label = orig


def test_clean_name_reply():
    assert clean_name_reply("  修复登录 401  ") == "修复登录 401"
    assert clean_name_reply("「查数据库」\n第二行") == "查数据库"
    assert clean_name_reply("") is None
    assert clean_name_reply("   ") is None
    assert len(clean_name_reply("x" * 50)) <= 16


def test_generate_session_name_uses_model():
    class FakeModel:
        def invoke(self, prompt):
            assert "不超过 12 字的会话短名" in prompt
            return types.SimpleNamespace(content="  排查登录  ")

    import types  # noqa: F401

    name = generate_session_name(FakeModel(), "帮我看下登录为什么失败")
    assert name == "排查登录"


def test_generate_session_name_none_model_or_error():
    assert generate_session_name(None, "x") is None

    class Boom:
        def invoke(self, p):
            raise RuntimeError("llm down")

    assert generate_session_name(Boom(), "x") is None


def test_naming_prompt_truncates_long_input():
    p = session_naming_prompt("字" * 2000)
    assert "字" * 2000 not in p  # 截断到 600
    assert len(p) < 800


# ---- presenter 后台命名（offscreen + fake 模型，不碰真实 LLM）
def test_presenter_maybe_names_first_turn(qapp, monkeypatch):
    from types import SimpleNamespace

    from src.gui.events import UiBridge
    from src.gui.runtime import GuiPresenter
    from tests.gui_fakes import new_home, cleanup_home
    from tests.test_gui_presenter import _fake_runtime, wait_until

    home = new_home()
    try:
        rt = _fake_runtime()
        # 注入 fake 模型（agent._jarvis_model）
        rt.agent = SimpleNamespace(
            _jarvis_model=SimpleNamespace(
                invoke=lambda p: SimpleNamespace(content="  登录排查  ")
            )
        )
        # first_human_text 走真 commands（会查检查点）→ monkeypatch 掉
        import src.gui.runtime as grt

        monkeypatch.setattr(
            grt.commands, "first_human_text", lambda agent, tid, limit=18: "帮我看下登录"
        )
        p = GuiPresenter(rt, UiBridge())
        refreshed = {"n": 0}
        p.bridge.refresh_sessions.connect(lambda: refreshed.__setitem__("n", refreshed["n"] + 1))
        p._maybe_name("t1", True)
        assert wait_until(lambda: refreshed["n"] >= 1, timeout=10.0)
        entry = p.session_registry.get("t1")
        assert entry is not None and entry["title"] == "登录排查" and entry["ai_generated"] is True
        # 已有短名 → 不重复命名
        p._maybe_name("t1", True)
        assert wait_until(lambda: refreshed["n"] >= 1)
    finally:
        cleanup_home(home)


def test_presenter_maybe_name_skips_abandoned_and_named(qapp):
    from src.gui.events import UiBridge
    from src.gui.runtime import GuiPresenter
    from tests.gui_fakes import new_home, cleanup_home
    from tests.test_gui_presenter import _fake_runtime

    home = new_home()
    try:
        rt = _fake_runtime()
        p = GuiPresenter(rt, UiBridge())
        p.session_registry.rename("t1", "已命名")
        before = p.session_registry.get("t1")
        p._maybe_name("t1", True)  # 已有短名 → 不动
        assert p.session_registry.get("t1") == before
        p._maybe_name("t2", False)  # 放弃回合 → 不命名
        assert p.session_registry.get("t2") is None
    finally:
        cleanup_home(home)
