"""project_paths 测试。"""
from pathlib import Path

from src.project_paths import (
    discover_project_root,
    get_project_root,
    install_root,
    migrate_project_dotdir,
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
    import sys

    monkeypatch.setattr(sys, 'argv', ['.build/frozen-root-test/jarvis-gui.exe'])
    root = install_root()
    assert root == Path(__file__).resolve().parent.parent
    # skills/ 在 .gitignore（运行时 seed 产物，全新检出/CI 不一定存在），只断言 src/
    assert (root / 'src').is_dir()


# ---------------------------------------------------------------- .jarvis/ dotdir 迁移（自建目录，不用 tmp_path）


def _fresh_root() -> Path:
    import os
    import tempfile
    import uuid

    root = Path(os.path.join(tempfile.gettempdir(), f"jx_dotdir_{uuid.uuid4().hex[:8]}"))
    os.makedirs(root)
    return root


def _stub_config(root: Path):
    from types import SimpleNamespace

    return SimpleNamespace(project_root=root)


def test_checkpoints_dir_is_dotdir_constant():
    from src.project_paths import CHECKPOINTS_DIR

    assert CHECKPOINTS_DIR == ".jarvis/checkpoints"


def test_migrate_fresh_project_no_notes():
    import shutil

    root = _fresh_root()
    try:
        notes = migrate_project_dotdir(_stub_config(root))
        assert notes == []
        assert not (root / ".jarvis").exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_migrate_moves_legacy_checkpoints_dir():
    import shutil

    root = _fresh_root()
    try:
        cp = root / "checkpoints"
        cp.mkdir()
        (cp / "checkpoints.sqlite").write_bytes(b"db-1")
        (cp / "writes.sqlite").write_bytes(b"w")
        notes = migrate_project_dotdir(_stub_config(root))
        assert not (root / "checkpoints").exists()
        assert (root / ".jarvis" / "checkpoints" / "checkpoints.sqlite").read_bytes() == b"db-1"
        assert (root / ".jarvis" / "checkpoints" / "writes.sqlite").read_bytes() == b"w"
        assert any("checkpoints" in n for n in notes)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_migrate_is_idempotent_second_run():
    import shutil

    root = _fresh_root()
    try:
        cp = root / "checkpoints"
        cp.mkdir()
        (cp / "checkpoints.sqlite").write_bytes(b"db-1")
        (root / "sessions.json").write_text('{"a": 1}', encoding="utf-8")
        migrate_project_dotdir(_stub_config(root))
        notes2 = migrate_project_dotdir(_stub_config(root))
        assert notes2 == []
        assert (root / ".jarvis" / "checkpoints" / "checkpoints.sqlite").is_file()
        assert (root / ".jarvis" / "sessions.json").read_text(encoding="utf-8") == '{"a": 1}'
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_migrate_checkpoints_collision_kept_with_warn():
    import shutil

    root = _fresh_root()
    try:
        old_cp, new_cp = root / "checkpoints", root / ".jarvis" / "checkpoints"
        old_cp.mkdir(parents=True)
        new_cp.mkdir(parents=True)
        (old_cp / "checkpoints.sqlite").write_bytes(b"old")
        (new_cp / "checkpoints.sqlite").write_bytes(b"new")
        notes = migrate_project_dotdir(_stub_config(root))
        assert (old_cp / "checkpoints.sqlite").read_bytes() == b"old", "异构目标绝不覆盖"
        assert (new_cp / "checkpoints.sqlite").read_bytes() == b"new"
        assert any("checkpoints.sqlite" in n for n in notes), "冲突需留痕 note"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_migrate_checkpoints_same_bytes_source_kept():
    import shutil

    root = _fresh_root()
    try:
        old_cp, new_cp = root / "checkpoints", root / ".jarvis" / "checkpoints"
        old_cp.mkdir(parents=True)
        new_cp.mkdir(parents=True)
        (old_cp / "checkpoints.sqlite").write_bytes(b"same")
        (new_cp / "checkpoints.sqlite").write_bytes(b"same")
        migrate_project_dotdir(_stub_config(root))
        # 字节相同 → 跳过、保留源（下版本清理）
        assert (old_cp / "checkpoints.sqlite").is_file()
        assert (new_cp / "checkpoints.sqlite").read_bytes() == b"same"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_migrate_moves_legacy_sessions_json():
    import shutil

    root = _fresh_root()
    try:
        (root / "sessions.json").write_text('{"a": 1}', encoding="utf-8")
        migrate_project_dotdir(_stub_config(root))
        assert not (root / "sessions.json").exists()
        assert (root / ".jarvis" / "sessions.json").read_text(encoding="utf-8") == '{"a": 1}'
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_migrate_sessions_json_identical_removes_source():
    import shutil

    root = _fresh_root()
    try:
        root.joinpath(".jarvis").mkdir()
        (root / "sessions.json").write_text('{"a": 1}', encoding="utf-8")
        (root / ".jarvis" / "sessions.json").write_text('{"a": 1}', encoding="utf-8")
        migrate_project_dotdir(_stub_config(root))
        assert not (root / "sessions.json").exists(), "相同字节 → 删源"
        assert (root / ".jarvis" / "sessions.json").read_text(encoding="utf-8") == '{"a": 1}'
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_migrate_sessions_json_union_merge():
    import shutil

    root = _fresh_root()
    try:
        root.joinpath(".jarvis").mkdir()
        (root / "sessions.json").write_text('{"a": 1, "b": 2}', encoding="utf-8")
        (root / ".jarvis" / "sessions.json").write_text('{"b": 99, "c": 3}', encoding="utf-8")
        migrate_project_dotdir(_stub_config(root))
        assert not (root / "sessions.json").exists(), "可并 → 删源"
        import json

        merged = json.loads((root / ".jarvis" / "sessions.json").read_text(encoding="utf-8"))
        assert merged == {"a": 1, "b": 99, "c": 3}, "冲突键目标胜、源独有键追加"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_migrate_sessions_json_incompatible_kept_with_warn():
    import shutil

    root = _fresh_root()
    try:
        root.joinpath(".jarvis").mkdir()
        (root / "sessions.json").write_text('{"a": 1}', encoding="utf-8")
        (root / ".jarvis" / "sessions.json").write_text('[1, 2]', encoding="utf-8")
        notes = migrate_project_dotdir(_stub_config(root))
        assert (root / "sessions.json").is_file(), "不可并 → 留源"
        assert (root / ".jarvis" / "sessions.json").read_text(encoding="utf-8") == "[1, 2]"
        assert any("sessions.json" in n for n in notes), "冲突需留痕 note"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_migrate_moves_legacy_skills_dir_and_rewrites_json():
    import json
    import shutil

    root = _fresh_root()
    try:
        sk = root / "skills"
        (sk / "alpha").mkdir(parents=True)
        (sk / "alpha" / "SKILL.md").write_text("alpha", encoding="utf-8")
        (sk / "beta").mkdir()
        (sk / "beta" / "SKILL.md").write_text("beta", encoding="utf-8")
        (root / "jarvis.json").write_text('{"skills": ["skills/", "my-skills"]}', encoding="utf-8")
        notes = migrate_project_dotdir(_stub_config(root))
        assert not (root / "skills").exists(), "整目录 move 后源应消失"
        assert (root / ".jarvis" / "skills" / "alpha" / "SKILL.md").read_text(encoding="utf-8") == "alpha"
        assert (root / ".jarvis" / "skills" / "beta" / "SKILL.md").read_text(encoding="utf-8") == "beta"
        data = json.loads((root / "jarvis.json").read_text(encoding="utf-8"))
        assert data["skills"] == [".jarvis/skills", "my-skills"], "skills 前缀条目改写、自定义条目不动"
        assert any("skills/ 已迁移" in n for n in notes)
        assert any("jarvis.json" in n for n in notes)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_migrate_rewrites_json_skills_subpath_only():
    import json
    import shutil

    root = _fresh_root()
    try:
        (root / "jarvis.json").write_text('{"skills": ["skills/plugins/foo", "my-skills"]}', encoding="utf-8")
        notes = migrate_project_dotdir(_stub_config(root))
        data = json.loads((root / "jarvis.json").read_text(encoding="utf-8"))
        assert data["skills"] == [".jarvis/skills/plugins/foo", "my-skills"]
        assert not (root / ".jarvis").exists(), "仅 JSON 改写不创建 .jarvis 目录"
        assert notes == ["jarvis.json skills 条目已改写 → .jarvis/skills（1 条）"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_migrate_custom_skills_entries_untouched():
    import shutil

    root = _fresh_root()
    try:
        text = '{"skills": ["my-skills"]}'
        (root / "jarvis.json").write_text(text, encoding="utf-8")
        notes = migrate_project_dotdir(_stub_config(root))
        assert notes == [], "无遗留 skills/ 目录、无 skills 前缀条目 → 零 note"
        assert (root / "jarvis.json").read_text(encoding="utf-8") == text, "字节不变"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_migrate_skills_collision_target_wins_source_removed():
    import shutil

    root = _fresh_root()
    try:
        old = root / "skills"
        (old / "a").mkdir(parents=True)
        (old / "a" / "SKILL.md").write_text("OLD", encoding="utf-8")
        (old / "b").mkdir()
        (old / "b" / "SKILL.md").write_text("b", encoding="utf-8")
        (old / "f.txt").write_text("f", encoding="utf-8")
        new = root / ".jarvis" / "skills"
        (new / "a").mkdir(parents=True)
        (new / "a" / "SKILL.md").write_text("NEW", encoding="utf-8")
        (new / "c").mkdir()
        (new / "c" / "SKILL.md").write_text("c", encoding="utf-8")
        (new / "f.txt").write_text("f", encoding="utf-8")
        notes = migrate_project_dotdir(_stub_config(root))
        assert not (root / "skills").exists(), "源目录清空后 rmdir"
        assert (new / "a" / "SKILL.md").read_text(encoding="utf-8") == "NEW", "同名冲突目标优先"
        assert (new / "b" / "SKILL.md").read_text(encoding="utf-8") == "b", "源独有 → move 进目标"
        assert (new / "f.txt").read_text(encoding="utf-8") == "f"
        assert (new / "c" / "SKILL.md").read_text(encoding="utf-8") == "c", "目标独有保持"
        assert any("目标优先" in n and "a" in n for n in notes)
        assert any("目标优先" in n and "f.txt" in n for n in notes)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_migrate_skills_idempotent_second_run():
    import json
    import shutil

    root = _fresh_root()
    try:
        sk = root / "skills"
        (sk / "x").mkdir(parents=True)
        (sk / "x" / "SKILL.md").write_text("x", encoding="utf-8")
        (root / "jarvis.json").write_text('{"skills": ["skills/"]}', encoding="utf-8")
        migrate_project_dotdir(_stub_config(root))
        notes2 = migrate_project_dotdir(_stub_config(root))
        assert notes2 == [], "第二跑幂等零 note"
        data = json.loads((root / "jarvis.json").read_text(encoding="utf-8"))
        assert data["skills"] == [".jarvis/skills"]
        assert (root / ".jarvis" / "skills" / "x" / "SKILL.md").is_file()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_migrate_skills_skipped_when_root_is_install_root(monkeypatch):
    import shutil

    import src.project_paths as pp

    root = _fresh_root()
    try:
        sk = root / "skills"
        (sk / "x").mkdir(parents=True)
        (sk / "x" / "SKILL.md").write_text("x", encoding="utf-8")
        (root / "jarvis.json").write_text('{"skills": ["skills/"]}', encoding="utf-8")
        monkeypatch.setattr(pp, "install_root", lambda: root)
        notes = pp.migrate_project_dotdir(_stub_config(root))
        assert notes == [], "项目根 == 安装根（开发模式）跳过 skills 迁移"
        assert sk.is_dir() and (sk / "x" / "SKILL.md").read_text(encoding="utf-8") == "x"
        assert not (root / ".jarvis").exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_migrate_skills_creates_dotdir_parent_when_missing():
    import shutil

    root = _fresh_root()
    try:
        sk = root / "skills"
        (sk / "x").mkdir(parents=True)
        (sk / "x" / "SKILL.md").write_text("x", encoding="utf-8")
        notes = migrate_project_dotdir(_stub_config(root))
        assert not (root / "skills").exists()
        assert (root / ".jarvis" / "skills" / "x" / "SKILL.md").read_text(encoding="utf-8") == "x"
        assert any("skills/ 已迁移" in n for n in notes)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_migrate_skills_target_is_file_keeps_source():
    import shutil

    root = _fresh_root()
    try:
        sk = root / "skills"
        (sk / "x").mkdir(parents=True)
        (sk / "x" / "SKILL.md").write_text("x", encoding="utf-8")
        dot = root / ".jarvis"
        dot.mkdir()
        (dot / "skills").write_text("i am a file", encoding="utf-8")
        notes = migrate_project_dotdir(_stub_config(root))
        assert (sk / "x" / "SKILL.md").read_text(encoding="utf-8") == "x", "源保留"
        assert (dot / "skills").read_text(encoding="utf-8") == "i am a file", "目标文件未动"
        assert any("人工处理" in n for n in notes)
    finally:
        shutil.rmtree(root, ignore_errors=True)

