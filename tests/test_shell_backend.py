"""InheritedEnvShellBackend 测试：环境继承 + 解码容错 + 基本执行。"""
import sys
from pathlib import Path

import pytest

import src.shell_backend as sb
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


def test_virtual_prefix_guard_matches_without_trailing_slash(tmp_path):
    """dir /workspace（无尾斜杠）也要拦（Spec 审查缺口）。"""
    b = InheritedEnvShellBackend(
        root_dir=str(tmp_path), virtual_mode=True,
        virtual_prefixes=("/workspace/", "/vault/"),
    )
    for cmd in ("dir /workspace", 'cd "/vault"', "type /workspace/notes.txt"):
        res = b.execute(cmd)
        assert res.exit_code == 1, f"{cmd!r} 漏拦"
        assert "虚拟前缀" in res.output
    # 真实路径不受影响
    res = b.execute("echo /workspacefoo is a plain dir name")
    assert res.exit_code == 0


def test_make_backend_default_unrestricted(tmp_path):
    """#10: _make_backend 的 default（workspace backend）必须 virtual_mode=False。"""
    import sys

    sys.path.insert(0, ".")
    from src.agent import _make_backend
    from tests.conftest import make_fake_config

    cfg = make_fake_config(tmp_path)
    backend = _make_backend(cfg)
    assert backend.default.virtual_mode is False


def test_unrestricted_backend_accesses_paths_outside_root(tmp_path):
    """#10: virtual_mode=False 下文件方法可访问项目外绝对路径；相对路径仍落项目根。"""
    ext = tmp_path / "outside"
    ext.mkdir()
    (ext / "note.txt").write_text("outer-content", encoding="utf-8")
    proj = tmp_path / "proj"
    proj.mkdir()

    b = InheritedEnvShellBackend(root_dir=str(proj), virtual_mode=False)

    ls = b.ls(str(ext))
    assert ls.error is None
    assert any("note.txt" in e["path"] for e in ls.entries)

    grep = b.grep("outer", path=str(ext))
    assert grep.matches, "项目外 grep 应有命中"

    write = b.write("inner-rel.txt", "x")
    assert write.error is None
    assert (proj / "inner-rel.txt").exists(), "相对路径应以项目根为基准"


def test_resolve_path_driveless_abs_resolves_under_cwd(tmp_path):
    """Windows 无盘符绝对路径（/foo）必须落到 cwd 下，不能锚定到盘符根。"""
    import sys
    if sys.platform != "win32":
        pytest.skip("Windows-only: Linux 下 /foo 是真绝对路径，行为不同")
    proj = tmp_path / "proj"
    proj.mkdir()
    b = InheritedEnvShellBackend(root_dir=str(proj), virtual_mode=False)

    result = b._resolve_path("/game")
    assert result == proj / "game", f"应落到项目根，实际: {result}"

    b.write("/game/test.txt", "ok")
    assert (proj / "game" / "test.txt").exists()


def test_resolve_path_true_absolute_unchanged(tmp_path):
    """真实盘符绝对路径（D:\\foo）原样放行。"""
    proj = tmp_path / "proj"
    proj.mkdir()
    b = InheritedEnvShellBackend(root_dir=str(proj), virtual_mode=False)

    ext = tmp_path / "ext"
    ext.mkdir()
    result = b._resolve_path(str(ext))
    assert result == ext, f"应原样放行，实际: {result}"


def test_resolve_path_relative_unchanged(tmp_path):
    """相对路径仍以项目根为基准。"""
    proj = tmp_path / "proj"
    proj.mkdir()
    b = InheritedEnvShellBackend(root_dir=str(proj), virtual_mode=False)

    result = b._resolve_path("sub/dir")
    assert result == proj / "sub" / "dir", f"应落到项目根下，实际: {result}"


# ---------------------------------------------------------------- Windows 多行命令拦截（执行韧性四期 L1）


class _FakeCompleted:
    """模拟 subprocess.CompletedProcess（execute 只读 stdout/stderr/returncode）。"""

    def __init__(self, command: str):
        self.returncode = 0
        self.stdout = f"ran: {command!r}\n"
        self.stderr = ""


def test_windows_multiline_command_blocked(monkeypatch):
    """Windows 多行命令执行前拦截：可行动指引，subprocess 根本不被调用。"""
    import src.shell_backend as sb

    b = sb.InheritedEnvShellBackend(root_dir=".", virtual_mode=False)
    monkeypatch.setattr(sb, "_IS_WINDOWS", True)
    called = []

    def fake_run(command, *args, **kwargs):
        called.append(command)
        raise AssertionError("多行命令应被执行前拦截")

    monkeypatch.setattr(sb.subprocess, "run", fake_run)
    res = b.execute('python -c "\nimport sys\nprint(\'hello\')"')
    assert res.exit_code == 1
    assert "多行" in res.output
    assert "落盘" in res.output
    assert "write_file" in res.output
    assert not called, "多行命令必须执行前拦截，subprocess.run 不应被调用"


def test_windows_single_line_command_allowed(monkeypatch):
    """Windows 单行命令不被多行守卫误伤。"""
    import src.shell_backend as sb

    b = sb.InheritedEnvShellBackend(root_dir=".", virtual_mode=False)
    monkeypatch.setattr(sb, "_IS_WINDOWS", True)
    seen = []

    def fake_run(command, *args, **kwargs):
        seen.append(command)
        return _FakeCompleted(command)

    monkeypatch.setattr(sb.subprocess, "run", fake_run)
    res = b.execute("echo hello")
    assert res.exit_code == 0
    assert seen == ["echo hello"]
    assert "ran:" in res.output


def test_posix_multiline_command_allowed(monkeypatch):
    """POSIX shell（sh/bash）支持多行：不拦截，原样放行。"""
    import src.shell_backend as sb

    b = sb.InheritedEnvShellBackend(root_dir=".", virtual_mode=False)
    monkeypatch.setattr(sb, "_IS_WINDOWS", False)
    seen = []

    def fake_run(command, *args, **kwargs):
        seen.append(command)
        return _FakeCompleted(command)

    monkeypatch.setattr(sb.subprocess, "run", fake_run)
    multi = "echo line1\necho line2"
    res = b.execute(multi)
    assert res.exit_code == 0
    assert seen == [multi]


# ---------------------------------------------------------------- POSIX 相对路径重锚定（deepagents 给相对路径补 /）


def _scratch_base():
    """自建 backend 根目录（项目纪律：新测试不用 tmp_path 夹具）。"""
    base = Path(__file__).resolve().parent.parent / ".scratch" / "rvmf-test"
    base.mkdir(parents=True, exist_ok=True)
    return base


def test_rvmf_relative_anchors_to_cwd():
    """相对路径锚定 cwd（平台无关）。"""
    base = _scratch_base()
    fn = sb.resolve_virtual_mode_false_path
    for is_posix in (True, False):
        assert fn("sub/x.txt", base, is_posix=is_posix, target_exists=False) == base / "sub" / "x.txt"


def test_rvmf_posix_fake_relative_reanchored():
    """POSIX + 目标不存在：补 / 的相对写重锚到 cwd（双平台确定性）。"""
    base = _scratch_base()
    fn = sb.resolve_virtual_mode_false_path
    assert fn("/hello.txt", base, is_posix=True, target_exists=False) == base / "hello.txt"


def test_rvmf_existing_absolute_unchanged():
    """目标已存在原样返回：is_posix=True 不偷真实路径；is_posix=False 恒放行绝对路径。"""
    real = Path(__file__).resolve()
    base = _scratch_base()
    fn = sb.resolve_virtual_mode_false_path
    assert fn(str(real), base, is_posix=True, target_exists=True) == real
    assert fn(str(real), base, is_posix=False, target_exists=False) == real


def test_rvmf_missing_absolute_windows_semantics():
    """Windows 语义（is_posix=False）：不存在的盘符绝对路径原样返回（Windows 分支不重锚）。"""
    import sys
    if sys.platform != "win32":
        pytest.skip("Windows-only: POSIX 下 /foo 是真绝对路径，分支语义不同")
    base = _scratch_base()
    missing = base / "definitely-not-exist-xyz"
    assert not missing.exists()
    fn = sb.resolve_virtual_mode_false_path
    assert fn(str(missing), base, is_posix=False, target_exists=False) == missing


def test_backend_resolve_path_posix_branch(monkeypatch):
    """端到端：_resolve_path POSIX 分支——不存在的 /-前缀路径重锚到 backend 根；已存在绝对路径原样。"""
    base = _scratch_base()
    b = sb.InheritedEnvShellBackend(root_dir=str(base), virtual_mode=False)
    monkeypatch.setattr(sb, "_IS_POSIX", True)
    real = Path(__file__).resolve()
    monkeypatch.setattr(sb, "_posix_target_exists", lambda key: key == str(real))

    assert b._resolve_path("/hello.txt") == base / "hello.txt", "不存在的 /-前缀路径应重锚到 backend 根"
    assert b._resolve_path(str(real)) == real, "已存在绝对路径应原样返回"


def test_backend_resolve_path_windows_branch(monkeypatch):
    """端到端：_resolve_path Windows 分支——无盘符/相对路径行为不变。"""
    import sys
    if sys.platform != "win32":
        pytest.skip("Windows-only")
    base = _scratch_base()
    b = sb.InheritedEnvShellBackend(root_dir=str(base), virtual_mode=False)
    monkeypatch.setattr(sb, "_IS_POSIX", False)
    real = Path(__file__).resolve()

    assert b._resolve_path("/game") == base / "game", "无盘符绝对路径落根（原行为）"
    assert b._resolve_path("sub/x") == base / "sub" / "x", "相对路径以根为基准（原行为）"
    assert b._resolve_path(str(real)) == real, '真正绝对路径原样返回'
