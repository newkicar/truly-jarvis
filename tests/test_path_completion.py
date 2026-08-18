"""@ 路径补全纯逻辑测试。"""

from pathlib import Path

from src.path_completion import (
    apply_completion,
    at_query,
    collect_completion_paths,
    filter_paths,
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


def test_collect_paths_inbox_first_and_skips_hidden_dirs(tmp_path):
    vault = _make_vault(tmp_path)
    ws = tmp_path / "ws"
    (ws / "memory").mkdir(parents=True)
    (ws / "memory" / "prefs.md").write_text("# prefs", encoding="utf-8")

    paths = collect_completion_paths(vault, ws, include_workspace=True)
    assert "/vault/Inbox/inbox-note.md" in paths
    assert "/vault/topics/other.md" in paths
    assert "/workspace/memory/prefs.md" in paths
    assert not any(".obsidian" in p for p in paths)
    assert paths.index("/vault/Inbox/inbox-note.md") < paths.index("/vault/topics/other.md")


def test_sort_paths_inbox_first():
    paths = [
        "/workspace/a.md",
        "/vault/topics/z.md",
        "/vault/Inbox/a.md",
        "/vault/Inbox/b.md",
    ]
    ordered = sort_paths_inbox_first(paths)
    assert ordered[:2] == ["/vault/Inbox/a.md", "/vault/Inbox/b.md"]
    assert ordered[2] == "/vault/topics/z.md"
    assert ordered[3] == "/workspace/a.md"


def test_at_query_detects_prefix_and_rejects_mid_word():
    assert at_query("hello @Inbox", 12) == (6, "Inbox")
    assert at_query("@", 1) == (0, "")
    assert at_query("foo@bar", 7) is None
    assert at_query("@a b", 4) is None


def test_filter_paths_case_insensitive():
    paths = ["/vault/Inbox/A.md", "/vault/other/B.md"]
    assert filter_paths(paths, "inbox") == ["/vault/Inbox/A.md"]
    assert filter_paths(paths, "") == paths


def test_apply_completion_replaces_at_segment():
    value, cursor = apply_completion("请读 @Inb", 3, 8, "/vault/Inbox/note.md")
    assert value == "请读 /vault/Inbox/note.md "
    assert cursor == len("请读 /vault/Inbox/note.md ")
