"""TUI 补全状态机测试。"""
from src.skill_discovery import SkillMeta, fuzzy_filter_skills
from src.tui_completion import apply_suggestion, apply_suggestion_on_line, line_projection, resolve_overlay_state, use_query


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


# ---------------------------------------------------------------------------
# tui-ux13: 光标行投影 + 行内建议应用（多行输入框补全）
# ---------------------------------------------------------------------------

def test_line_projection_clamp_out_of_bounds():
    text = "l0\nl1"
    assert line_projection(text, (0, 0)) == ("l0", 0)
    assert line_projection(text, (5, 9)) == ("l1", 2)
    assert line_projection(text, (-1, 3)) == ("l0", 2)


def test_line_projection_mid_line():
    text = "first\nsecond\nthird"
    assert line_projection(text, (1, 2)) == ("second", 2)


def test_apply_suggestion_on_line_only_touches_cursor_line():
    text = "aaa\n@In\nzzz"
    # @ 触发点 at_index=0，光标在行内 col 3；建议替换 [0,3) 区间，
    # 不尾随空格的建议自动补尾随空格（apply_suggestion 契约）
    new_text, new_cursor = apply_suggestion_on_line(text, (1, 3), 0, "/vault/x.md")
    assert new_text == "aaa\n/vault/x.md \nzzz"
    assert new_cursor == (1, 12)
    assert new_text.split("\n")[0] == "aaa" and new_text.split("\n")[2] == "zzz"


def test_apply_suggestion_on_line_equivalent_to_single_line():
    text = "onlyline"
    a = apply_suggestion_on_line(text, (0, 3), 0, "insert")
    b = apply_suggestion(text, 0, 3, "insert")
    assert a[0] == b[0]
    assert a[1] == (0, b[1])
