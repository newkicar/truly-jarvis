"""project_paths 测试。"""
from pathlib import Path

from src.project_paths import (
    discover_project_root,
    get_project_root,
    install_root,
    resolve_env_file,
    resolve_jarvis_json,
    set_runtime_project_root,
)


def test_discover_project_root_finds_javis_in_parent(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_PROJECT_ROOT", raising=False)
    project = tmp_path / "my-app"
    nested = project / "sub"
    nested.mkdir(parents=True)
    (project / "jarvis.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(nested)
    assert discover_project_root() == project.resolve()


def test_discover_project_root_uses_cwd_when_no_javis(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_PROJECT_ROOT", raising=False)
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    assert discover_project_root() == empty.resolve()


def test_discover_project_root_env_override(tmp_path, monkeypatch):
    forced = tmp_path / "forced"
    forced.mkdir()
    monkeypatch.setenv("JARVIS_PROJECT_ROOT", str(forced))
    assert discover_project_root() == forced.resolve()


def test_resolve_jarvis_json_prefers_project(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "jarvis.json").write_text("{}", encoding="utf-8")
    assert resolve_jarvis_json(project) == project / "jarvis.json"


def test_runtime_project_root(monkeypatch):
    monkeypatch.delenv("JARVIS_PROJECT_ROOT", raising=False)
    set_runtime_project_root(Path("/tmp/javis-test-root"))
    try:
        assert get_project_root() == Path("/tmp/javis-test-root").resolve()
    finally:
        set_runtime_project_root(install_root())


def test_resolve_env_file_project_before_install(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".env").write_text("BASE_URL:https://x.com\n", encoding="utf-8")
    assert resolve_env_file(project) == project / ".env"


# ---------------------------------------------------------------- AGENTS.md 项目指令层


def test_load_project_instructions_empty_when_missing(tmp_path, monkeypatch):
    from src.project_paths import load_project_instructions

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    assert load_project_instructions(tmp_path) == ""


def test_load_project_instructions_project_level(tmp_path, monkeypatch):
    from src.project_paths import load_project_instructions

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("JARVIS_HOME", str(home))
    (tmp_path / "AGENTS.md").write_text("测试命令是 pytest -q\n", encoding="utf-8")
    text = load_project_instructions(tmp_path)
    assert "pytest -q" in text
    assert "本项目约定" in text
    assert "全局用户约定" not in text


def test_load_project_instructions_global_plus_project(tmp_path, monkeypatch):
    from src.project_paths import load_project_instructions

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("JARVIS_HOME", str(home))
    (home / "AGENTS.md").write_text("全局：回复用中文\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("项目：包管理器用 pnpm\n", encoding="utf-8")
    text = load_project_instructions(tmp_path)
    assert text.index("全局用户约定") < text.index("本项目约定"), "全局在前"
    assert "回复用中文" in text and "pnpm" in text


def test_load_project_instructions_legacy_jarvis_md_fallback(monkeypatch):
    """该级无 AGENTS.md、只有 legacy JARVIS.md 时，全局与项目两级均回落读取（自建目录，不用 tmp_path）。"""
    import os
    import shutil
    import tempfile

    from src.project_paths import load_project_instructions

    home = os.path.join(tempfile.gettempdir(), "jx_pp_legacy_test_home")
    root = os.path.join(tempfile.gettempdir(), "jx_pp_legacy_test_root")
    os.makedirs(home, exist_ok=True)
    os.makedirs(root, exist_ok=True)
    monkeypatch.setenv("JARVIS_HOME", home)
    try:
        with open(os.path.join(home, "JARVIS.md"), "w", encoding="utf-8") as f:
            f.write("全局旧版：回复用中文\n")
        with open(os.path.join(root, "JARVIS.md"), "w", encoding="utf-8") as f:
            f.write("项目旧版：包管理器用 pnpm\n")
        text = load_project_instructions(Path(root))
        assert "回复用中文" in text and "pnpm" in text
        assert "全局用户约定" in text and "本项目约定" in text
        assert "AGENTS.md" not in text
    finally:
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(root, ignore_errors=True)


def test_load_project_instructions_agents_md_wins_over_legacy(monkeypatch):
    """两级 AGENTS.md 与 legacy JARVIS.md 并存时，只读 AGENTS.md（自建目录，不用 tmp_path）。"""
    import os
    import shutil
    import tempfile

    from src.project_paths import load_project_instructions

    home = os.path.join(tempfile.gettempdir(), "jx_pp_agents_test_home")
    root = os.path.join(tempfile.gettempdir(), "jx_pp_agents_test_root")
    os.makedirs(home, exist_ok=True)
    os.makedirs(root, exist_ok=True)
    monkeypatch.setenv("JARVIS_HOME", home)
    try:
        with open(os.path.join(home, "AGENTS.md"), "w", encoding="utf-8") as f:
            f.write("全局：回复用中文\n")
        with open(os.path.join(home, "JARVIS.md"), "w", encoding="utf-8") as f:
            f.write("全局旧版（不应出现）\n")
        with open(os.path.join(root, "AGENTS.md"), "w", encoding="utf-8") as f:
            f.write("项目：包管理器用 pnpm\n")
        with open(os.path.join(root, "JARVIS.md"), "w", encoding="utf-8") as f:
            f.write("项目旧版（不应出现）\n")
        text = load_project_instructions(Path(root))
        assert "回复用中文" in text and "pnpm" in text
        assert "不应出现" not in text
    finally:
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- frozen install_root (Nuitka onedir)

def test_install_root_frozen_uses_exe_dir(monkeypatch):
    """frozen 形态：install_root = exe 所在目录（.build 自建目录，不用 tmp_path）。"""
    import os
    import sys

    exe_dir = os.path.abspath(os.path.join('.build', 'frozen-root-test'))
    os.makedirs(exe_dir, exist_ok=True)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'argv', [exe_dir + '/jarvis-gui.exe'])
    assert install_root() == Path(exe_dir).resolve()


def test_install_root_not_frozen_uses_source_tree(monkeypatch):
    """非 frozen（源码运行）：保持 __file__ 语义，exe 目录约定不生效。"""
    import os
    import sys

    monkeypatch.setattr(sys, 'argv', ['.build/frozen-root-test/jarvis-gui.exe'])
    root = install_root()
    assert root == Path(__file__).resolve().parent.parent
    # skills/ 在 .gitignore（运行时 seed 产物，全新检出/CI 不一定存在），只断言 src/
    assert (root / 'src').is_dir()
