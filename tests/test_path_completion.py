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


def test_apply_completion_replaces_at_segment():
    value, cursor = apply_completion("请读 @Inb", 3, 8, "/vault/Inbox/note.md")
    assert value == "请读 /vault/Inbox/note.md "
    assert cursor == len("请读 /vault/Inbox/note.md ")
