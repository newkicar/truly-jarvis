"""@ 路径补全纯逻辑测试。"""

from pathlib import Path

from src.path_completion import (
    PathSuggestion,
    apply_completion,
    at_query,
    collect_completion_paths,
    filter_path_suggestions,
    sort_path_suggestions,
    sort_paths_inbox_first,
)


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "Inbox").mkdir(parents=True)
    (vault / "Inbox" / "inbox-note.md").write_text("# inbox", encoding="utf-8")
    (vault / "topics").mkdir()
    (vault / "topics" / "other.md").write_text("# other", encoding="utf-8")
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "hidden.md").write_text("# hidden", encoding="utf-8")
    return vault


def test_collect_paths_workspace_before_vault(tmp_path):
    vault = _make_vault(tmp_path)
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "main.py").write_text("print('hi')", encoding="utf-8")
    mem = ws / "memory"
    mem.mkdir()
    (mem / "prefs.md").write_text("# prefs", encoding="utf-8")

    items = collect_completion_paths(vault, ws, mem)
    paths = [i.path for i in items]
    assert "/workspace/src/main.py" in paths
    assert "/memories/prefs.md" in paths
    assert "/vault/Inbox/inbox-note.md" in paths
    assert paths.index("/workspace/src/main.py") < paths.index("/vault/topics/other.md")
    assert not any(".obsidian" in p for p in paths)


def test_collect_paths_vault_scope_prefix(tmp_path):
    vault = _make_vault(tmp_path)
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "main.py").write_text("x", encoding="utf-8")

    items = collect_completion_paths(vault, ws, query="vault/Inbox")
    paths = [i.path for i in items]
    assert all(p.startswith("/vault/") for p in paths)
    assert "/workspace/src/main.py" not in paths


def test_collect_paths_includes_directories(tmp_path):
    """目录条目（/ 结尾）应出现在候选列表中。"""
    ws = tmp_path / "ws"
    (ws / "src" / "inner").mkdir(parents=True)
    (ws / "src" / "main.py").write_text("x", encoding="utf-8")
    (ws / "docs").mkdir()

    items = collect_completion_paths(None, ws, None)
    paths = [i.path for i in items]
    # 目录应带 / 后缀
    assert "/workspace/src/" in paths
    assert "/workspace/src/inner/" in paths
    assert "/workspace/docs/" in paths
    # 文件也在
    assert "/workspace/src/main.py" in paths
    # is_dir 标记正确
    by_path = {i.path: i for i in items}
    assert by_path["/workspace/src/"].is_dir is True
    assert by_path["/workspace/src/main.py"].is_dir is False
    # 目录 hint 带 [目录]
    assert by_path["/workspace/src/"].hint == "项目 [目录]"
    assert by_path["/workspace/src/main.py"].hint == "项目"


def test_collect_paths_directory_suffix_filter(tmp_path):
    """vault / memories 目录条目不受 .md 后缀过滤影响。"""
    vault = tmp_path / "vault"
    (vault / "Inbox").mkdir(parents=True)
    (vault / "Inbox" / "note.md").write_text("# x", encoding="utf-8")

    items = collect_completion_paths(vault, None, None)
    paths = [i.path for i in items]
    assert "/vault/Inbox/" in paths
    assert "/vault/Inbox/note.md" in paths
    by_path = {i.path: i for i in items}
    assert by_path["/vault/Inbox/"].is_dir is True
    assert by_path["/vault/Inbox/"].hint == "Inbox [目录]"


def test_collect_paths_directory_query_filter(tmp_path):
    """查询以 / 结尾时只匹配该目录下的内容（子串匹配天然收窄）。"""
    ws = tmp_path / "ws"
    (ws / "src" / "inner").mkdir(parents=True)
    (ws / "src" / "main.py").write_text("x", encoding="utf-8")
    (ws / "other").mkdir()
    (ws / "other" / "a.txt").write_text("y", encoding="utf-8")

    items = collect_completion_paths(None, ws, None, query="src/")
    paths = [i.path for i in items]
    # src 目录及其子项匹配
    assert "/workspace/src/" in paths
    assert "/workspace/src/main.py" in paths
    assert "/workspace/src/inner/" in paths
    # other 目录不匹配
    assert "/workspace/other/" not in paths
    assert "/workspace/other/a.txt" not in paths


def test_collect_paths_directory_sort_before_children(tmp_path):
    """同层目录排序在其子文件之前（/ 字符 ASCII 47 小于字母）。"""
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "b.py").write_text("x", encoding="utf-8")
    (ws / "src" / "a.py").write_text("x", encoding="utf-8")

    items = collect_completion_paths(None, ws, None)
    paths = [i.path for i in items]
    idx_dir = paths.index("/workspace/src/")
    idx_a = paths.index("/workspace/src/a.py")
    idx_b = paths.index("/workspace/src/b.py")
    assert idx_dir < idx_a < idx_b


def test_apply_completion_directory_no_trailing_space():
    """目录路径（/ 结尾）接受后不加尾随空格，用户可继续输入收窄。"""
    value, cursor = apply_completion("读 @src", 2, 6, "/workspace/src/")
    assert value == "读 /workspace/src/"
    assert cursor == len("读 /workspace/src/")
    # 尾随空格不在
    assert not value.endswith(" ")


def test_apply_completion_file_still_has_trailing_space():
    """文件路径接受后仍加尾随空格（旧行为不变）。"""
    value, cursor = apply_completion("读 @src", 2, 6, "/workspace/src/main.py")
    assert value == "读 /workspace/src/main.py "
    assert cursor == len("读 /workspace/src/main.py ")


def test_sort_path_suggestions_workspace_first():
    items = [
        PathSuggestion("/vault/topics/z.md", "知识库"),
        PathSuggestion("/workspace/a.py", "项目"),
        PathSuggestion("/vault/Inbox/a.md", "Inbox"),
    ]
    ordered = sort_path_suggestions(items)
    assert ordered[0].path.startswith("/workspace/")
    assert ordered[1].path.startswith("/vault/Inbox/")


def test_sort_paths_inbox_first_compat():
    paths = [
        "/workspace/a.md",
        "/vault/topics/z.md",
        "/vault/Inbox/a.md",
    ]
    ordered = sort_paths_inbox_first(paths)
    assert ordered[0].startswith("/workspace/")


def test_at_query_detects_prefix_and_rejects_mid_word():
    assert at_query("hello @Inbox", 12) == (6, "Inbox")
    assert at_query("@", 1) == (0, "")
    assert at_query("foo@bar", 7) is None
    assert at_query("@a b", 4) is None


def test_filter_path_suggestions_case_insensitive():
    items = [
        PathSuggestion("/workspace/src/Main.py", "项目"),
        PathSuggestion("/vault/other/B.md", "知识库"),
    ]
    assert filter_path_suggestions(items, "main") == [items[0]]


def test_filter_path_suggestions_includes_directories():
    items = [
        PathSuggestion("/workspace/src/", "项目 [目录]", is_dir=True),
        PathSuggestion("/workspace/src/main.py", "项目"),
        PathSuggestion("/workspace/other/", "项目 [目录]", is_dir=True),
    ]
    matched = filter_path_suggestions(items, "src")
    assert len(matched) == 2
    assert "/workspace/src/" in [i.path for i in matched]
    assert "/workspace/src/main.py" in [i.path for i in matched]


def test_apply_completion_replaces_at_segment():
    value, cursor = apply_completion("请读 @Inb", 3, 8, "/vault/Inbox/note.md")
    assert value == "请读 /vault/Inbox/note.md "
    assert cursor == len("请读 /vault/Inbox/note.md ")
