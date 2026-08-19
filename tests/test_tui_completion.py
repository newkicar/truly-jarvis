"""TUI 补全状态机测试。"""
from src.tui_completion import resolve_overlay_state


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
