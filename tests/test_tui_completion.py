"""TUI 补全状态机测试。"""
from src.skill_discovery import SkillMeta, fuzzy_filter_skills
from src.tui_completion import resolve_overlay_state, use_query


def test_resolve_slash_overlay(tmp_path):
    state = resolve_overlay_state(
        "/his",
        4,
        vault_path=tmp_path / "v",
        workspace_root=tmp_path / "w",
        memories_root=tmp_path / "m",
    )
    assert state.kind == "slash"
    assert state.active
    assert any("/history" in item.insert for item in state.items)


def test_resolve_path_overlay(tmp_path):
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "app.py").write_text("x", encoding="utf-8")
    state = resolve_overlay_state(
        "改 @src/app",
        len("改 @src/app"),
        vault_path=None,
        workspace_root=ws,
        memories_root=None,
    )
    assert state.kind == "path"
    assert any("app.py" in item.insert for item in state.items)


def _use_skill(name: str, desc: str = "", manual: bool = False) -> SkillMeta:
    """tui-ux9 fixture: 直构 SkillMeta，无文件系统依赖。"""
    return SkillMeta(
        name=name,
        description=desc,
        virtual_path="/skills/x/SKILL.md",
        layer="project",
        manual_only=manual,
    )


def test_use_skill_overlay_trigger():
    catalog = [_use_skill("book-meeting"), _use_skill("alpha")]
    state = resolve_overlay_state(
        "/use bk",
        8,
        vault_path=None,
        workspace_root=None,
        memories_root=None,
        skills=catalog,
    )
    assert state.kind == "skill"
    assert state.at_index == 5
    assert state.active
    assert [i.insert for i in state.items] == [
        s.name for s in fuzzy_filter_skills(catalog, "bk")
    ]
    assert use_query("/use bk", 8) == (5, "bk")


def test_use_bare_command_is_slash():
    state = resolve_overlay_state(
        "/use",
        4,
        vault_path=None,
        workspace_root=None,
        memories_root=None,
        skills=[_use_skill("alpha")],
    )
    assert state.kind == "slash"
    assert any("use" in i.insert for i in state.items)


def test_use_prefix_is_slash():
    state = resolve_overlay_state(
        "/uses",
        5,
        vault_path=None,
        workspace_root=None,
        memories_root=None,
        skills=[_use_skill("alpha")],
    )
    assert state.kind == "slash"


def test_use_description_segment_closes_overlay():
    state = resolve_overlay_state(
        "/use x ",
        7,
        vault_path=None,
        workspace_root=None,
        memories_root=None,
        skills=[_use_skill("alpha")],
    )
    assert state.kind == "none"
    assert not state.active


def test_use_skill_overlay_filters_catalog():
    catalog = [_use_skill("book-meeting")]
    state = resolve_overlay_state(
        "/use book ",
        8,
        vault_path=None,
        workspace_root=None,
        memories_root=None,
        skills=catalog,
    )
    assert state.kind == "skill"
    assert [i.insert for i in state.items] == ["book-meeting"]


def test_use_skill_overlay_without_skills_is_none():
    state = resolve_overlay_state(
        "/use bk",
        8,
        vault_path=None,
        workspace_root=None,
        memories_root=None,
    )
    assert state.kind == "none"
    assert not state.active


def test_use_skill_item_label_and_hint():
    catalog = [_use_skill("long-desc", desc="X" * 45, manual=True)]
    state = resolve_overlay_state(
        "/use ",
        5,
        vault_path=None,
        workspace_root=None,
        memories_root=None,
        skills=catalog,
    )
    assert state.kind == "skill"
    item = state.items[0]
    assert item.insert == "long-desc"
    assert item.label == "long-desc [manual]"
    assert item.hint == "X" * 40 + "…"
