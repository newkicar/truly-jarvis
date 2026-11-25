"""TUI 补全状态机测试。"""
from src.skill_discovery import SkillMeta, fuzzy_filter_skills
from src.tui_completion import (
    apply_suggestion,
    apply_suggestion_on_line,
    line_projection,
    resolve_overlay_state,
    use_query,
)


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


def test_resolve_path_overlay_includes_directories(tmp_path):
    """@ 补全候选应包含目录条目（/ 结尾）。"""
    ws = tmp_path / "ws"
    (ws / "src" / "inner").mkdir(parents=True)
    (ws / "src" / "main.py").write_text("x", encoding="utf-8")
    (ws / "docs").mkdir()
    state = resolve_overlay_state(
        "@",
        1,
        vault_path=None,
        workspace_root=ws,
        memories_root=None,
    )
    assert state.kind == "path"
    inserts = [i.insert for i in state.items]
    # 目录条目存在
    assert "/workspace/src/" in inserts
    assert "/workspace/docs/" in inserts
    # 文件条目也在
    assert "/workspace/src/main.py" in inserts
    # 目录 hint 带 [目录]
    dir_item = next(i for i in state.items if i.insert == "/workspace/src/")
    assert "[目录]" in dir_item.hint


def test_resolve_path_overlay_directory_narrowing(tmp_path):
    """查询 src/ 时应收窄到 src 目录下的条目。"""
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "main.py").write_text("x", encoding="utf-8")
    (ws / "other").mkdir()
    (ws / "other" / "a.txt").write_text("y", encoding="utf-8")

    state = resolve_overlay_state(
        "@src/",
        len("@src/"),
        vault_path=None,
        workspace_root=ws,
        memories_root=None,
    )
    inserts = [i.insert for i in state.items]
    assert "/workspace/src/" in inserts
    assert "/workspace/src/main.py" in inserts
    assert "/workspace/other/" not in inserts
    assert "/workspace/other/a.txt" not in inserts


def test_apply_suggestion_directory_no_trailing_space(tmp_path):
    """目录条目接受后不加尾随空格（用户可继续输入收窄）。"""
    value, cursor = apply_suggestion("读 @", 2, 3, "/workspace/src/")
    assert value == "读 /workspace/src/"
    assert cursor == len("读 /workspace/src/")
    # 尾随空格不在
    assert not value.endswith(" ")


def test_apply_suggestion_file_has_trailing_space(tmp_path):
    """文件条目接受后仍加尾随空格（旧行为不变）。"""
    value, cursor = apply_suggestion("读 @", 2, 3, "/workspace/src/main.py")
    assert value == "读 /workspace/src/main.py "
    assert cursor == len("读 /workspace/src/main.py ")


def test_apply_suggestion_on_line_directory(tmp_path):
    """多行场景下目录建议应用：目录无尾随空格。"""
    text = "第一行\n读 @src"
    new_text, new_cursor = apply_suggestion_on_line(text, (1, 6), 2, "/workspace/src/")
    assert new_text == "第一行\n读 /workspace/src/"
    assert new_cursor == (1, len("读 /workspace/src/"))
    assert not new_text.split("\n")[1].endswith(" ")


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

def test_resolve_slash_overlay_any_position():
    """tui-ux21: "space + /" anywhere opens the command list; at_index = slash pos."""
    st = resolve_overlay_state(
        "hello /co",
        9,
        vault_path=None,
        workspace_root=None,
        memories_root=None,
    )
    assert st.kind == "slash"
    assert st.at_index == 6
    assert any(i.insert.startswith("/compact") for i in st.items)


def test_resolve_slash_overlay_cursor_mid_query():
    st = resolve_overlay_state(
        "hello /his more",
        10,
        vault_path=None,
        workspace_root=None,
        memories_root=None,
    )
    assert st.kind == "slash"
    assert st.at_index == 6
    assert st.active


def test_resolve_slash_overlay_glued_slash_no_trigger():
    for value in ("abc/h", "file:///x"):
        st = resolve_overlay_state(
            value,
            len(value),
            vault_path=None,
            workspace_root=None,
            memories_root=None,
        )
        assert st.kind == "none", value


def test_resolve_slash_overlay_space_closes():
    st = resolve_overlay_state(
        "hello /yolo ",
        12,
        vault_path=None,
        workspace_root=None,
        memories_root=None,
    )
    assert st.kind == "none"


def test_apply_suggestion_slash_any_position():
    """accept replaces from the slash position; trailing space is appended."""
    text = "hello /his"
    st = resolve_overlay_state(
        text,
        len(text),
        vault_path=None,
        workspace_root=None,
        memories_root=None,
    )
    assert st.kind == "slash" and st.at_index == 6
    new_text, new_cursor = apply_suggestion(text, st.at_index, len(text), "/history")
    assert new_text == "hello /history "
    assert new_cursor == 15


def test_apply_suggestion_on_line_slash_second_line():
    """multi-line input: accept rewrites only the cursor line (shared kernel)."""
    text = "第一行\n第二 /comp"
    cursor = (1, len("第二 /comp"))
    line, col = line_projection(text, cursor)
    st = resolve_overlay_state(line, col, vault_path=None, workspace_root=None, memories_root=None)
    assert st.kind == "slash"
    assert st.at_index == 3
    new_text, new_cursor = apply_suggestion_on_line(text, cursor, st.at_index, "/compact [hint]")
    lines = new_text.split("\n")
    assert lines[0] == "第一行"
    assert lines[1] == "第二 /compact [hint] "
    assert new_cursor[0] == 1

# ---------------------------------------------------------------------------
# tui-ux24: /use 任意位置锚定泛化（对齐 slash_query/at_query 规则）
# ---------------------------------------------------------------------------

def _use_resolve(text, cursor, skills):
    return resolve_overlay_state(
        text, cursor, vault_path=None, workspace_root=None, memories_root=None, skills=skills
    )


def test_use_skill_any_position_trigger():
    catalog = [_use_skill("book-meeting"), _use_skill("alpha")]
    # 句中 / 续行：「空格 + /use」任意位置触发（at_index = 真实 query 起点）
    assert use_query("hello /use ", 11) == (11, "")
    assert use_query("abc /use bk", 11) == (9, "bk")
    st = _use_resolve("hello /use ", 11, catalog)
    assert st.kind == "skill"
    assert st.at_index == 11
    assert st.active
    assert [i.insert for i in st.items] == [s.name for s in fuzzy_filter_skills(catalog, "")]
    st2 = _use_resolve("abc /use bk", 11, catalog)
    assert st2.kind == "skill"
    assert st2.at_index == 9
    assert [i.insert for i in st2.items] == [s.name for s in fuzzy_filter_skills(catalog, "bk")]


def test_use_skill_glued_use_no_trigger():
    catalog = [_use_skill("alpha")]
    assert use_query("x/use ", 6) is None  # 前一字符非空白不触发
    assert _use_resolve("x/use ", 6, catalog).kind == "none"


def test_use_skill_description_segment_closes_anywhere():
    catalog = [_use_skill("alpha")]
    assert use_query("hello /use bk more", 18) is None
    assert _use_resolve("hello /use bk more", 18, catalog).kind == "none"


def test_use_skill_bare_and_prefix_stay_slash_anywhere():
    catalog = [_use_skill("alpha")]
    assert use_query("hello /uses", 10) is None  # 无尾随空格 → slash 语义
    assert _use_resolve("hello /uses", 10, catalog).kind == "slash"
    assert use_query("hello /use", 10) is None
    assert _use_resolve("hello /use", 10, catalog).kind == "slash"


def test_apply_suggestion_skill_prefix_preserved():
    text = "hello /use "
    new_text, new_cursor = apply_suggestion(text, 11, 11, "book-meeting")
    assert new_text == "hello /use book-meeting "  # 前缀「hello 」保住
    assert new_cursor == 24


def test_apply_suggestion_on_line_skill_second_line():
    """多行输入：续行句中 /use 接受建议只改光标行（共享内核回归）。"""
    line = "句中 /use "
    text = "第一行\n" + line
    cursor = (1, len(line))
    proj_line, col = line_projection(text, cursor)
    st = _use_resolve(proj_line, col, [_use_skill("book-meeting")])
    assert st.kind == "skill"
    assert st.at_index == 8  # 行内偏移（「句中 」3 字符 + "/use " 5 字符）
    new_text, new_cursor = apply_suggestion_on_line(text, cursor, st.at_index, "book-meeting")
    lines = new_text.split("\n")
    assert lines[0] == "第一行"  # 其它行未动
    assert lines[1] == "句中 /use book-meeting "
    assert new_cursor[0] == 1
