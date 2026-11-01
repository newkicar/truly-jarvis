"""project_init 测试。"""
from pathlib import Path

from src.project_init import init_project, suggest_init_if_missing


def test_init_project_creates_layout(tmp_path: Path):
    created, skipped, messages = init_project(tmp_path, vault_path="D:/vault")
    assert (tmp_path / "jarvis.json").is_file()
    assert (tmp_path / ".env").is_file()
    assert not (tmp_path / "memory").exists()  # javis-global-memory: memory/ is not created in the project dir (it is global ~/.jarvis/memory/)
    assert (tmp_path / "vault" / "Inbox").is_dir()
    assert (tmp_path / "run-javis.cmd").is_file()
    data = (tmp_path / "jarvis.json").read_text(encoding="utf-8")
    assert "D:/vault" in data
    assert "copy_on_select" in data
    assert "memory_dir" not in data
    assert created
    assert any("API" in m for m in messages)


def test_init_project_skips_existing_javis_json(tmp_path: Path):
    (tmp_path / "jarvis.json").write_text("{}", encoding="utf-8")
    created, skipped, _ = init_project(tmp_path)
    assert str(tmp_path / "jarvis.json") in skipped
    assert (tmp_path / "jarvis.json").read_text(encoding="utf-8") == "{}"


def test_init_project_force_overwrites_javis_json(tmp_path: Path):
    (tmp_path / "jarvis.json").write_text("{}", encoding="utf-8")
    init_project(tmp_path, force=True)
    text = (tmp_path / "jarvis.json").read_text(encoding="utf-8")
    assert '"knowledge_base"' in text
    assert '"obsidian_vault"' not in text


def test_suggest_init_if_missing(tmp_path: Path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    hint = suggest_init_if_missing()
    assert hint is not None
    assert "--init" in hint

    (empty / "jarvis.json").write_text("{}", encoding="utf-8")
    assert suggest_init_if_missing() is None


def test_init_project_instructions_creates_jarvis_md():
    """定瓤性扫描生成 JARVIS.md（自建目录，不用 tmp_path）。"""
    import os
    import tempfile

    from src.project_init import init_project_instructions

    base = os.path.join(tempfile.gettempdir(), "jarvis_init_test_a")
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, "app.py"), "w", encoding="utf-8") as f:
        f.write("print('hi')\n")
    with open(os.path.join(base, "pyproject.toml"), "w", encoding="utf-8") as f:
        f.write("[project]\nname = 'demo'\n")
    try:
        msg = init_project_instructions(Path(base))
        target = Path(base, "JARVIS.md")
        assert target.is_file()
        content = target.read_text(encoding="utf-8")
        assert "Python" in content
        assert "生成" in content
        assert "pyproject.toml" in content
        assert "生成" in msg
        assert "已存在" not in msg
    finally:
        import shutil
        shutil.rmtree(base, ignore_errors=True)


def test_init_project_instructions_does_not_overwrite():
    """已存在 JARVIS.md 时不覆盖，只返回提示。"""
    import os
    import tempfile
    import time

    from src.project_init import init_project_instructions

    base = os.path.join(tempfile.gettempdir(), "jarvis_init_test_b")
    os.makedirs(base, exist_ok=True)
    sentinel = Path(base, "JARVIS.md")
    sentinel.write_text("# 原有指令内容", encoding="utf-8")
    orig = sentinel.read_text(encoding="utf-8")
    mtime_before = sentinel.stat().st_mtime
    time.sleep(0.05)
    try:
        msg = init_project_instructions(Path(base))
        assert sentinel.read_text(encoding="utf-8") == orig
        assert sentinel.stat().st_mtime == mtime_before
        assert "已存在" in msg
        assert "未覆盖" in msg
    finally:
        import shutil
        shutil.rmtree(base, ignore_errors=True)


def test_scan_project_counts_langs_and_manifests():
    import os
    import tempfile

    from src.project_init import scan_project

    base = os.path.join(tempfile.gettempdir(), "jarvis_scan_test")
    os.makedirs(os.path.join(base, "pkg"), exist_ok=True)
    with open(os.path.join(base, "a.py"), "w", encoding="utf-8") as f:
        f.write("x = 1\n")
    with open(os.path.join(base, "pkg", "b.py"), "w", encoding="utf-8") as f:
        f.write("y = 2\n")
    with open(os.path.join(base, "pyproject.toml"), "w", encoding="utf-8") as f:
        f.write("")
    try:
        scan = scan_project(Path(base))
        lang_map = dict(scan["langs"])
        assert lang_map.get("Python") == 2
        assert "pyproject.toml" in scan["manifests"]
        assert isinstance(scan["tree"], list)
    finally:
        import shutil
        shutil.rmtree(base, ignore_errors=True)
