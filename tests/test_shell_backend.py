"""InheritedEnvShellBackend 测试：环境继承 + 解码容错 + 基本执行。"""
import sys

import pytest

from src.shell_backend import InheritedEnvShellBackend


@pytest.fixture()
def backend(tmp_path):
    return InheritedEnvShellBackend(root_dir=str(tmp_path), virtual_mode=True)


def test_env_inherited(backend):
    """子进程环境必须继承父进程 PATH（空 env 是坦克大战事故根因）。"""
    assert backend._env, "环境变量不应为空"
    assert "PATH" in backend._env or "Path" in backend._env


def test_env_override_merges(backend, tmp_path):
    b = InheritedEnvShellBackend(root_dir=str(tmp_path), env={"JAVIS_TEST_VAR": "42"})
    assert b._env.get("JAVIS_TEST_VAR") == "42"
    assert "PATH" in b._env or "Path" in b._env


def test_basic_command_runs(backend):
    """外部程序可被找到并执行（echo 是 shell 内建，PATH 检查用 where/which）。"""
    res = backend.execute("echo ok")
    assert res.exit_code == 0
    assert "ok" in res.output


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PATH 探测")
def test_external_program_found_on_windows(backend):
    """where.exe 是系统外部程序——空 PATH 下必挂（事故复现）。"""
    res = backend.execute("where where")
    assert res.exit_code == 0, f"where 不可达: {res.output!r}"


def test_nonzero_exit_reported(backend):
    res = backend.execute("exit 3")
    assert res.exit_code != 0
    assert "Exit code: 3" in res.output


def test_stderr_prefixed(backend):
    res = backend.execute("echo err_msg 1>&2") if sys.platform != "win32" else backend.execute("echo err_msg 1>&2")
    assert "[stderr]" in res.output
    assert "err_msg" in res.output


def test_timeout_returns_124(tmp_path):
    b = InheritedEnvShellBackend(root_dir=str(tmp_path), timeout=1)
    res = b.execute("ping -n 5 127.0.0.1" if sys.platform == "win32" else "sleep 5", timeout=1)
    assert res.exit_code == 124
    assert "timed out" in res.output


def test_empty_command_rejected(backend):
    res = backend.execute("")
    assert res.exit_code == 1
    assert "non-empty" in res.output


# ---------------------------------------------------------------- 虚拟前缀守卫


def test_virtual_prefix_guard_blocks_and_explains(tmp_path):
    """execute 收到 /workspace/ 等虚拟前缀 → 执行前拦截，给出可行动的错误。"""
    b = InheritedEnvShellBackend(
        root_dir=str(tmp_path), virtual_mode=True,
        virtual_prefixes=("/workspace/", "/vault/"),
    )
    res = b.execute("mkdir /workspace/tmp-javis-demo")
    assert res.exit_code == 1
    assert "虚拟前缀" in res.output
    assert "相对路径" in res.output
    assert "write_file" in res.output  # 指出正确工具


def test_virtual_prefix_guard_allows_real_paths(tmp_path):
    b = InheritedEnvShellBackend(
        root_dir=str(tmp_path), virtual_mode=True,
        virtual_prefixes=("/workspace/",),
    )
    res = b.execute("echo hello")
    assert res.exit_code == 0
    assert "hello" in res.output


def test_virtual_prefix_guard_ignores_urls(tmp_path):
    """/workspace 出现在 URL 路径段不应误伤。"""
    b = InheritedEnvShellBackend(
        root_dir=str(tmp_path), virtual_mode=True,
        virtual_prefixes=("/workspace/",),
    )
    res = b.execute("echo https://example.com/workspace/docs")
    assert res.exit_code == 0, f"URL 误伤: {res.output!r}"
    assert "虚拟前缀" not in res.output


def test_make_backend_wires_prefixes(tmp_path):
    """_make_backend 组装时把全部路由前缀传给 workspace 守卫。"""
    import sys

    sys.path.insert(0, ".")
    from src.agent import _make_backend
    from tests.conftest import make_fake_config

    cfg = make_fake_config(tmp_path)
    backend = _make_backend(cfg)
    ws = backend.default
    prefixes = {p.strip("/") for p in ws._virtual_prefixes}
    assert "workspace" in prefixes
    assert "memories" in prefixes
    assert "vault" in prefixes  # fake config 带 vault_path
