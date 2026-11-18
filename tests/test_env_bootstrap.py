"""tui-ux27: 首启 .env 自动引导（TUI/CLI 侧）单测。

纪律（本机 pytest 基 temp 目录 WinError 5 中毒）：禁用 tmp_path/tempfile.mkdtemp，
自建目录 .scratch/env-bootstrap-tmp/<uuid>/ + finally rmtree；fake 项目根/安装根
monkeypatch 进 src.env_bootstrap 命名空间（顶层 import 面），永不触碰真仓库根
dev .env 与 ~。
"""
import shutil
import types
import uuid
from pathlib import Path

import pytest

from src import env_bootstrap
from src.config import REQUIRED_ENV_KEYS, parse_env_text
from src.env_bootstrap import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL_ID,
    bootstrap_missing_env,
    guidance_text,
    missing_env_report,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRATCH = REPO_ROOT / ".scratch" / "env-bootstrap-tmp"


def _all_values(**overrides) -> dict[str, str]:
    values = {
        "BASE_URL": DEFAULT_BASE_URL,
        "API_KEY": "sk-test",
        "MODEL_ID": DEFAULT_MODEL_ID,
        "TAVILY_KEY": "",
    }
    values.update(overrides)
    return values


def _no_input(*_a, **_k) -> str:
    raise AssertionError("input() 不应被调用")


def _make_getpass(results):
    calls = {"n": 0}

    def fake(prompt):
        calls["n"] += 1
        return results[min(calls["n"] - 1, len(results) - 1)]

    return fake, calls


@pytest.fixture()
def fake_env(monkeypatch):
    """fake 项目根 + 安装根（自建目录，不污染真仓库 / ~）。"""
    uid = uuid.uuid4().hex[:10]
    base = SCRATCH / uid
    project = base / "project"
    install = base / "install"
    project.mkdir(parents=True)
    install.mkdir(parents=True)
    monkeypatch.setattr(env_bootstrap, "discover_project_root", lambda: project)
    monkeypatch.setattr(env_bootstrap, "install_root", lambda: install)
    try:
        yield {"project": project, "install": install}
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_bootstrap_creates_new_file(fake_env):
    """两处都无 .env → 新建项目 .env（与 load_config 单选语义一致）。"""
    out = bootstrap_missing_env(values=_all_values(), interactive=False)
    target = fake_env["project"] / ".env"
    assert out == target
    env = parse_env_text(target.read_text(encoding="utf-8"))
    for key in REQUIRED_ENV_KEYS:
        assert key in env
    assert target.read_text(encoding="utf-8").startswith("# JARVIS 环境变量（首启自动引导生成）")


def test_bootstrap_fills_missing_in_existing(fake_env):
    """既有项目 .env：只补缺键，其余行（含自定义键）原样保留。"""
    target = fake_env["project"] / ".env"
    target.write_text("BASE_URL=old\nMY_CUSTOM: foo\n", encoding="utf-8")
    out = bootstrap_missing_env(values={"API_KEY": "k", "MODEL_ID": "m", "TAVILY_KEY": ""})
    assert out == target
    text = target.read_text(encoding="utf-8")
    assert "BASE_URL=old" in text
    assert "MY_CUSTOM: foo" in text
    env = parse_env_text(text)
    assert env["API_KEY"] == "k" and env["MODEL_ID"] == "m" and env["TAVILY_KEY"] == ""


def test_noop_when_all_keys_present(fake_env):
    """键齐（空值合法）→ 严格 no-op：返回 None，文件一字不动，无 tmp 残留。"""
    target = fake_env["project"] / ".env"
    target.write_text("BASE_URL=u\nAPI_KEY=k\nMODEL_ID=m\nTAVILY_KEY=\n", encoding="utf-8")
    before = target.read_bytes()
    assert bootstrap_missing_env(values={}) is None
    assert target.read_bytes() == before
    assert not target.with_name(target.name + ".tmp").exists()


def test_noninteractive_prints_guidance_no_write(fake_env, capsys):
    """非交互 + 缺键 → stderr 打手动指引，不写文件。"""
    out = bootstrap_missing_env(values={}, interactive=False)
    assert out is None
    err = capsys.readouterr().err
    for key in REQUIRED_ENV_KEYS:
        assert key in err
    assert str(fake_env["project"] / ".env") in err
    assert not (fake_env["project"] / ".env").exists()


def test_values_cover_all_missing_no_prompt(fake_env, monkeypatch):
    """values 覆盖全部缺键 → 直接写入，交互态下也不触发任何提示。"""
    monkeypatch.setattr("builtins.input", _no_input)
    out = bootstrap_missing_env(values=_all_values(), interactive=True)
    assert out == fake_env["project"] / ".env"


def test_interactive_hidden_api_key_with_retry(fake_env, monkeypatch):
    """API_KEY 走 getpass 隐藏输入；空输入重输（两次调用）。"""
    target = fake_env["project"] / ".env"
    target.write_text("BASE_URL=u\nMODEL_ID=m\nTAVILY_KEY=\n", encoding="utf-8")
    fake_getpass, calls = _make_getpass(["", "sekrit"])
    monkeypatch.setattr(env_bootstrap, "getpass", types.SimpleNamespace(getpass=fake_getpass))
    monkeypatch.setattr("builtins.input", _no_input)
    out = bootstrap_missing_env(values={"BASE_URL": "u", "MODEL_ID": "m", "TAVILY_KEY": ""}, interactive=True)
    assert out == target
    assert calls["n"] == 2
    assert parse_env_text(target.read_text(encoding="utf-8"))["API_KEY"] == "sekrit"


def test_interactive_defaults_on_empty_enter(fake_env, monkeypatch):
    """BASE_URL/MODEL_ID 空回车落默认；TAVILY_KEY 可选留空。"""
    fake_getpass, _ = _make_getpass(["k"])
    monkeypatch.setattr(env_bootstrap, "getpass", types.SimpleNamespace(getpass=fake_getpass))
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "")
    out = bootstrap_missing_env(values={"TAVILY_KEY": ""}, interactive=True)
    env = parse_env_text(out.read_text(encoding="utf-8"))
    assert env["BASE_URL"] == DEFAULT_BASE_URL
    assert env["MODEL_ID"] == DEFAULT_MODEL_ID
    assert env["API_KEY"] == "k"
    assert "TAVILY_KEY" in env and env["TAVILY_KEY"] == ""


def test_tavily_ensure_appended_when_absent(fake_env):
    """TAVILY_KEY 缺键 + values 给空串 → 尾插 TAVILY_KEY=（空值合法）。"""
    target = fake_env["project"] / ".env"
    target.write_text("BASE_URL=u\nAPI_KEY=k\nMODEL_ID=m\n", encoding="utf-8")
    out = bootstrap_missing_env(values={"TAVILY_KEY": ""})
    assert out == target
    assert "TAVILY_KEY=" in target.read_text(encoding="utf-8").splitlines()


def test_explicit_target_wins(fake_env, capsys):
    """显式 target 优先于 _pick_env_file 选择（项目 .env 不动；非交互不落盘）。"""
    project_env = fake_env["project"] / ".env"
    install_env = fake_env["install"] / ".env"
    project_env.write_text("BASE_URL=u\nAPI_KEY=k\nMODEL_ID=m\nTAVILY_KEY=\n", encoding="utf-8")
    install_env.write_text("BASE_URL=u2\nMODEL_ID=m2\nTAVILY_KEY=\n", encoding="utf-8")  # 缺 API_KEY
    out = bootstrap_missing_env(values={}, target=install_env, interactive=False)
    assert out is None  # 非交互 → 指引不落盘（显式 target 生效于判定）
    assert "API_KEY" not in install_env.read_text(encoding="utf-8")
    assert str(install_env) in capsys.readouterr().err
    out = bootstrap_missing_env(values={"API_KEY": "new"}, target=install_env)
    assert out == install_env
    assert parse_env_text(install_env.read_text(encoding="utf-8"))["API_KEY"] == "new"
    assert parse_env_text(project_env.read_text(encoding="utf-8"))["API_KEY"] == "k"


def test_colon_style_line_preserved(fake_env):
    """冒号式既有行（KEY:V）不被 values 未覆盖的键重写。"""
    target = fake_env["project"] / ".env"
    target.write_text("api_key : abc\nbase_url : old\n", encoding="utf-8")
    out = bootstrap_missing_env(values={"MODEL_ID": "m", "TAVILY_KEY": ""})
    assert out == target
    text = target.read_text(encoding="utf-8")
    assert "api_key : abc" in text
    assert "base_url : old" in text
    env = parse_env_text(text)
    assert env["API_KEY"] == "abc" and env["BASE_URL"] == "old" and env["MODEL_ID"] == "m"


def test_eof_fallback_no_write(fake_env, capsys, monkeypatch):
    """交互中途 EOF（管道结束/Ctrl+Z）→ 回落指引，不写文件。"""
    def eof(*_a, **_k):
        raise EOFError("EOF")
    fake_getpass, _ = _make_getpass(["k"])
    monkeypatch.setattr(env_bootstrap, "getpass", types.SimpleNamespace(getpass=fake_getpass))
    monkeypatch.setattr("builtins.input", eof)
    out = bootstrap_missing_env(values={}, interactive=True)
    assert out is None
    err = capsys.readouterr().err
    assert "[配置] .env 缺键" in err or ".env 缺键" in err
    assert not (fake_env["project"] / ".env").exists()


def test_pick_env_file_tiers(fake_env):
    """_pick_env_file 三档：双缺→项目新建；仅安装有→安装；双有→项目。"""
    project_env = fake_env["project"] / ".env"
    install_env = fake_env["install"] / ".env"
    assert env_bootstrap._pick_env_file() == project_env
    install_env.write_text("BASE_URL=x\n", encoding="utf-8")
    assert env_bootstrap._pick_env_file() == install_env
    project_env.write_text("BASE_URL=y\n", encoding="utf-8")
    assert env_bootstrap._pick_env_file() == project_env
    assert env_bootstrap._pick_env_file(fake_env["project"]) == project_env


def test_missing_env_report_explicit_target(fake_env):
    """missing_env_report：显式 target + 全缺/全有判定（空值合法）。"""
    install_env = fake_env["install"] / ".env"
    target, missing = missing_env_report(target=install_env)
    assert target == install_env
    assert missing == list(REQUIRED_ENV_KEYS)
    install_env.write_text("BASE_URL=u\nAPI_KEY=k\nMODEL_ID=m\nTAVILY_KEY=\n", encoding="utf-8")
    target, missing = missing_env_report(target=install_env)
    assert missing == []


def test_guidance_text_shape():
    target = Path("/tmp/x/.env")
    text = guidance_text(target, list(REQUIRED_ENV_KEYS))
    assert str(target) in text
    for key in REQUIRED_ENV_KEYS:
        assert key in text
    assert "重启" in text


def test_main_entry_point_wired():
    """回归面：main.py 缺键 except 块引用引导符号（防改名断链，零副作用）。"""
    main_src = (REPO_ROOT / "src" / "main.py").read_text(encoding="utf-8")
    assert "from src.env_bootstrap import" in main_src
    for name in ("bootstrap_missing_env", "guidance_text", "missing_env_report"):
        assert name in main_src

