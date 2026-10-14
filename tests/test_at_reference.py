"""#04 @ 引用路径前缀映射（锚点行 / shell 守卫指路 / 补全双路径）。"""
from pathlib import Path

from src import commands
from src.shell_backend import InheritedEnvShellBackend
from src.tui_completion import resolve_overlay_state

from tests.conftest import make_fake_config


def test_virtual_path_mappings(tmp_path):
    config = make_fake_config(tmp_path)
    mapping = commands.virtual_path_mappings(config)
    assert mapping["/workspace/"] == str(tmp_path)
    assert mapping["/vault/"] == str(tmp_path / "vault")
    assert mapping["/memories/"] == str(tmp_path / "memory")


def test_virtual_path_mappings_none_config():
    assert commands.virtual_path_mappings(None) == {}


def test_path_anchor_lines_hit(tmp_path):
    config = make_fake_config(tmp_path)
    mapping = commands.virtual_path_mappings(config)
    lines = commands.path_anchor_lines("看 /workspace/src/app.py", mapping)
    assert len(lines) == 1
    assert lines[0].startswith("[dim]路径锚点: /workspace/src/app.py → ")
    assert str(tmp_path / "src/app.py") in lines[0]
    assert lines[0].endswith("[/dim]")


def test_path_anchor_lines_no_match():
    mapping = {"/workspace/": "D:/x"}
    assert commands.path_anchor_lines("hello world", mapping) == []
    assert commands.path_anchor_lines("/workspace/a", {}) == []


def test_path_anchor_lines_dedup_and_cap():
    mapping = {"/workspace/": "D:/x"}
    text = (
        " /workspace/a /workspace/a /workspace/b /workspace/c "
        " /workspace/d /workspace/e /workspace/f "
    )
    lines = commands.path_anchor_lines(text, mapping)
    assert len(lines) == 5
    assert len(set(lines)) == 5
    assert "→ " + str(Path("D:/x") / "a") in lines[0]


def test_path_anchor_lines_longer_prefix_first():
    mapping = {"/workspace/": "D:/x", "/memories/": "D:/m"}
    lines = commands.path_anchor_lines("读 /memories/note.md 和 /workspace/a.py", mapping)
    assert any("→ " + str(Path("D:/m") / "note.md") in l for l in lines)
    assert any("→ " + str(Path("D:/x") / "a.py") in l for l in lines)


def test_shell_guard_error_includes_real_dir(tmp_path):
    backend = InheritedEnvShellBackend(
        root_dir=str(tmp_path),
        virtual_prefixes=("/workspace/",),
        prefix_map={"/workspace/": str(tmp_path)},
    )
    resp = backend.execute("dir /workspace/x")
    assert resp.exit_code == 1
    assert str(tmp_path) in resp.output
    assert "虚拟前缀 /workspace/ 对应真实目录" in resp.output


def test_shell_guard_error_without_prefix_map(tmp_path):
    backend = InheritedEnvShellBackend(
        root_dir=str(tmp_path),
        virtual_prefixes=("/workspace/",),
    )
    resp = backend.execute("dir /workspace/x")
    assert resp.exit_code == 1
    assert "对应真实目录" not in resp.output


def _make_ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "app.py").write_text("x", encoding="utf-8")
    return ws


def test_completion_default_virtual_unchanged(tmp_path):
    ws = _make_ws(tmp_path)
    value = "@src/app"
    state = resolve_overlay_state(
        value,
        len(value),
        vault_path=None,
        workspace_root=ws,
        memories_root=None,
        path_mapping={"/workspace/": str(ws)},
    )
    assert state.kind == "path"
    item = next(i for i in state.items if i.insert == "/workspace/src/app.py")
    assert item.label == "/workspace/src/app.py"
    assert item.hint == "项目"


def test_completion_dual_style(tmp_path):
    ws = _make_ws(tmp_path)
    value = "@src/app"
    state = resolve_overlay_state(
        value,
        len(value),
        vault_path=None,
        workspace_root=ws,
        memories_root=None,
        path_mapping={"/workspace/": str(ws)},
        at_reference_style="dual",
    )
    item = next(i for i in state.items if "app.py" in i.insert)
    assert item.insert == "/workspace/src/app.py"
    assert item.label == "/workspace/src/app.py"
    assert f"· {str(ws / 'src/app.py')}" in item.hint


def test_completion_real_style(tmp_path):
    ws = _make_ws(tmp_path)
    value = "@src/app"
    state = resolve_overlay_state(
        value,
        len(value),
        vault_path=None,
        workspace_root=ws,
        memories_root=None,
        path_mapping={"/workspace/": str(ws)},
        at_reference_style="real",
    )
    item = next(i for i in state.items if "app.py" in i.insert)
    assert item.insert == str(ws / "src/app.py")
    assert item.label == str(ws / "src/app.py")
    assert "/workspace/src/app.py" in item.hint


def test_completion_real_style_without_mapping_falls_back(tmp_path):
    ws = _make_ws(tmp_path)
    value = "@src/app"
    state = resolve_overlay_state(
        value,
        len(value),
        vault_path=None,
        workspace_root=ws,
        memories_root=None,
        path_mapping=None,
        at_reference_style="real",
    )
    item = next(i for i in state.items if "app.py" in i.insert)
    assert item.insert == "/workspace/src/app.py"
