"""tui-ux4-hotfix #04: /workspace/ 路由切换为虚拟模式 FilesystemBackend。

修复前 /workspace/ 共享默认 InheritedEnvShellBackend(virtual_mode=False)：ls/glob
上报真实磁盘绝对路径，经 CompositeBackend 重拼路由前缀产出
/workspaceD:<盘符>... 破形，模型用返回路径 read_file 失败（@ 引用卡点）。
修复后路由专用虚拟模式后端（项目根）：条目上报干净 /workspace/...
路径；default 仍为 InheritedEnvShellBackend（#10 无限制语义 + execute 虚拟前缀
守卫不变）。
"""
from dataclasses import replace

from tests.conftest import make_fake_config


def _backend_for(tmp_path, project=None, **overrides):
    from src.agent import _make_backend

    cfg = make_fake_config(project or tmp_path)
    if overrides:
        cfg = replace(cfg, **overrides)
    return _make_backend(cfg)


def test_ls_workspace_entries_are_clean_paths(tmp_path):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "foo.md").write_text("hello 04", encoding="utf-8")
    (tmp_path / "bar.txt").write_text("bar", encoding="utf-8")

    backend = _backend_for(tmp_path)
    ls = backend.ls("/workspace/")
    assert ls.error is None
    paths = [e["path"] for e in ls.entries or []]
    assert "/workspace/bar.txt" in paths, paths
    assert any(p.endswith("notes/") for p in paths), paths
    # 修复前破形：路由前缀 + 真实磁盘绝对路径（/workspaceD:<盘符>...）；
    # 修复后不得含反斜杠与盘符冒号。
    for p in paths:
        assert p.startswith("/workspace/"), p
        assert "\\" not in p, p
        assert ":" not in p, p


def test_ls_workspace_subdir(tmp_path):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "foo.md").write_text("x", encoding="utf-8")

    backend = _backend_for(tmp_path)
    r = backend.ls("/workspace/notes/")
    assert r.error is None
    assert [e["path"] for e in r.entries or []] == ["/workspace/notes/foo.md"]


def test_read_via_workspace_route(tmp_path):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "foo.md").write_text("hello 04", encoding="utf-8")

    backend = _backend_for(tmp_path)
    res = backend.read("/workspace/notes/foo.md")
    assert res.error is None
    assert res.file_data["content"] == "hello 04"


def test_write_via_workspace_route(tmp_path):
    backend = _backend_for(tmp_path)
    r = backend.write("/workspace/new.md", "written 04")
    assert r.error is None
    assert (tmp_path / "new.md").read_text(encoding="utf-8") == "written 04"


def test_glob_grep_workspace_clean_paths(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("needle-04", encoding="utf-8")

    backend = _backend_for(tmp_path)
    g = backend.glob("/workspace/src/*.py")
    assert g.error is None
    assert [m["path"] for m in g.matches] == ["/workspace/src/app.py"]

    gp = backend.grep("needle-04", path="/workspace/")
    assert gp.error is None
    assert any(m["path"] == "/workspace/src/app.py" for m in gp.matches)


def test_skills_route_longer_prefix_wins(tmp_path, monkeypatch):
    """更长前缀 /workspace/skills/ 仍优先于 /workspace/ 路由。"""
    from src.project_paths import ensure_user_home

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    ensure_user_home()
    project = tmp_path / "proj"
    project_skills = project / "skills"
    (project_skills / "demo").mkdir(parents=True)
    (project_skills / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: d\n---\n", encoding="utf-8"
    )

    backend = _backend_for(tmp_path, project=project, skills=(project_skills,))
    r = backend.ls("/workspace/skills/")
    assert r.error is None
    assert [e["path"] for e in r.entries or []] == ["/workspace/skills/demo/"]


def test_default_route_stays_unrestricted(tmp_path):
    """#10 回归：default 仍为无限制语义（真实磁盘路径经无前缀路由可访）。"""
    from src.shell_backend import InheritedEnvShellBackend

    backend = _backend_for(tmp_path)
    assert isinstance(backend.default, InheritedEnvShellBackend)
    assert backend.default.virtual_mode is False

    ext = tmp_path / "outside"
    ext.mkdir()
    (ext / "note.txt").write_text("outer", encoding="utf-8")
    r = backend.ls(str(ext))
    assert r.error is None
    assert any(e["path"].endswith("note.txt") for e in r.entries or [])


def test_execute_virtual_guard_unchanged(tmp_path):
    backend = _backend_for(tmp_path)
    r = backend.execute("dir /workspace/x")
    assert r.exit_code == 1
    assert "虚拟前缀" in r.output
    assert str(tmp_path) in r.output
