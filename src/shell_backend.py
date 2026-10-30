"""Windows 就绪的 LocalShellBackend 子类。

deepagents 的 LocalShellBackend 默认 inherit_env=False（子进程环境为空 dict），
导致 Windows 下 cmd 找不到 python/where/powershell 等任何程序；且 execute 硬编码
text=True 无 errors 参数，父进程开 UTF-8 模式时 GBK 控制台输出会 UnicodeDecodeError。

本子类：
1. 强制继承父进程环境（HITL 审批仍是唯一安全边界，环境继承不改变权限面）；
2. 解码容错：locale 编码 + errors="replace"，GBK 中文输出不再炸管道；
3. 虚拟前缀守卫：execute 收到 /workspace/ 等文件工具专用前缀时，执行前拦截并
   返回可行动的错误（cmd 会把 /workspace 当开关静默忽略，模型永远猜不到根因——
   0006 课原则：提示词是建议，代码才是边界）。
4. 多行拦截：Windows 下 shell 为 cmd，不支持多行命令（换行被静默截断，
   症状 = exit 0 但无输出）；execute 执行前预拦截并返回可行动指引
   （执行韧性四期四层防线第 1 层，详见 AGENTS.md）。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from deepagents.backends.local_shell import DEFAULT_EXECUTE_TIMEOUT, LocalShellBackend
from deepagents.backends.protocol import ExecuteResponse


def _console_encoding() -> str | None:
    """Windows 控制台输出用系统 ANSI 码页（中文 Windows=GBK/mbcs），确定性解码。"""
    return "mbcs" if sys.platform == "win32" else None


_IS_WINDOWS = os.name == "nt"
# 测试 monkeypatch 目标：直接改本模块属性（见 tests/test_shell_backend.py）。
# _IS_POSIX：测试 monkeypatch 目标，同 _IS_WINDOWS（见 tests/test_shell_backend.py）。
_IS_POSIX = os.name == "posix"


def _posix_target_exists(key: str) -> bool:
    """POSIX 重锚定目标路径是否已存在（作 monkeypatch 目标，保证跨平台测试确定性）。"""
    return Path(key).exists()


def resolve_virtual_mode_false_path(
    key: str,
    cwd: Path,
    *,
    is_posix: bool,
    target_exists: bool,
) -> Path:
    """纯函数：把 virtual_mode=False 的文件工具 key 解析为真实磁盘路径。

    deepagents FilesystemMiddleware.validate_path 会把相对路径补前缀 / 再调 backend，
    故 POSIX 下模型 write_file('hello.txt') 到达 backend 是 write('/hello.txt')：
    - POSIX 且目标不存在：视为补了 / 的相对写，重锚到 cwd
      （修非 root 用户 PermissionError 与 CI root 真写文件系统根的问题）；
    - POSIX 且目标已存在：原样返回，不偷用户真实绝对路径；
    - Windows：无盘符 /foo 落 cwd（保持原行为）；跨盘符绝对路径原样返回。
    """
    p = Path(key)
    if p.is_absolute():
        if is_posix and not target_exists:
            return (cwd / str(p).lstrip("/\\")).resolve()
        return p
    rel = str(p).lstrip("/\\")
    return (cwd / rel).resolve()


class InheritedEnvShellBackend(LocalShellBackend):
    """继承父进程环境的本地 shell backend（Windows 中文环境安全）。"""

    def __init__(
        self,
        root_dir: str | Any,
        *,
        virtual_mode: bool = True,
        timeout: int = DEFAULT_EXECUTE_TIMEOUT,
        max_output_bytes: int = 100_000,
        env: dict[str, str] | None = None,
        virtual_prefixes: tuple[str, ...] = (),
        prefix_map: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            root_dir=root_dir,
            virtual_mode=virtual_mode,
            timeout=timeout,
            max_output_bytes=max_output_bytes,
            env=env,
            inherit_env=True,
        )
        self._virtual_prefixes = tuple(p.strip("/") for p in virtual_prefixes if p.strip("/"))
        # #04: 虚拟前缀 → 真实目录映射（key 形如 "/workspace/"），守卫报错指路用。
        self._prefix_map = dict(prefix_map or {})
        # (?<![:\w]) 排除 URL 路径段（https://x/workspace/）；
        # (?![\w]) 兼容无尾斜杠形式（dir /workspace、cd "/vault"）。
        alt = "|".join(re.escape(p) for p in self._virtual_prefixes) or r"(?!)"
        self._virtual_path_re = re.compile(rf"(?<![:\w])/(?:{alt})(?![\w])", re.IGNORECASE)

    def _resolve_path(self, key: str) -> Path:
        """覆写 virtual_mode=False 的路径解析（规则见 resolve_virtual_mode_false_path）。

            POSIX：deepagents validate_path 给相对写补的 /，目标不存在时重锚到 cwd；
            已存在的目标绝对路径原样返回。Windows：无盘符/相对路径行为不变；跨盘符绝对路径不受影响。
        """
        target_exists = _posix_target_exists(key) if _IS_POSIX else False
        return resolve_virtual_mode_false_path(
            key, self.cwd, is_posix=_IS_POSIX, target_exists=target_exists
        )

    def _virtual_prefix_error(self, command: str) -> ExecuteResponse | None:
        m = self._virtual_path_re.search(command)
        if not m:
            return None
        prefix = m.group(0)
        hint = ""
        root = self._prefix_map.get(prefix.rstrip("/") + "/")
        if root:
            hint = (
                f"\n虚拟前缀 {prefix}/ 对应真实目录：{root}——"
                "shell 里请改用项目根相对路径或真实路径，"
                f"{prefix}/ 前缀只用于文件工具（write_file/ls/read_file 等）。"
            )
        return ExecuteResponse(
            output=(
                f"Error: shell 命令包含文件工具专用的虚拟前缀 {prefix!r}——shell 不认识虚拟路径，"
                "cmd 会把它当开关参数静默忽略或报语法错误。\n"
                f"shell 的工作目录就是项目根（{self.cwd}）。请改用相对路径"
                "（如 tmp-javis-demo/xxx）或真实磁盘路径；/workspace/ 前缀只用于文件工具"
                f"（write_file/ls/read_file 等，会自动创建父目录）。{hint}"
            ),
            exit_code=1,
            truncated=False,
        )

    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        if not command or not isinstance(command, str):
            return ExecuteResponse(
                output="Error: Command must be a non-empty string.",
                exit_code=1,
                truncated=False,
            )

        guard = self._virtual_prefix_error(command)
        if guard is not None:
            return guard

        if _IS_WINDOWS and "\n" in command:
            return ExecuteResponse(
                output=(
                    "错误：本机 shell 是 Windows cmd，不支持多行命令——命令中的换行被静默截断，"
                    "结果为 exit 0 且无输出（这是失败，不是成功）。请换方法：\n"
                    "1) 多行脚本：先用 write_file 落盘（如 tmp_read_docx.py），再单行执行：python tmp_read_docx.py\n"
                    "2) 多个操作：用 && 或 ; 链接成单行\n"
                    "3) python -c 只允许单行；需要多行请用方法 1"
                ),
                exit_code=1,
                truncated=False,
            )

        effective_timeout = timeout if timeout is not None else self._default_timeout
        if effective_timeout <= 0:
            msg = f"timeout must be positive, got {effective_timeout}"
            raise ValueError(msg)

        try:
            result = subprocess.run(  # noqa: S602
                command,
                check=False,
                shell=True,  # Intentional: LLM-controlled shell execution
                capture_output=True,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding=_console_encoding(),
                errors="replace",  # GBK/UTF-8 混杂输出不炸管道（deepagents 未传此参）
                timeout=effective_timeout,
                env=self._env,
                cwd=str(self.cwd),
            )
        except subprocess.TimeoutExpired:
            if timeout is not None:
                msg = (
                    f"Error: Command timed out after {effective_timeout} seconds "
                    "(custom timeout). The command may be stuck or require more time."
                )
            else:
                msg = (
                    f"Error: Command timed out after {effective_timeout} seconds. "
                    "For long-running commands, re-run using the timeout parameter."
                )
            return ExecuteResponse(output=msg, exit_code=124, truncated=False)
        except Exception as e:  # noqa: BLE001
            return ExecuteResponse(
                output=f"Error executing command ({type(e).__name__}): {e}",
                exit_code=1,
                truncated=False,
            )

        output_parts: list[str] = []
        if result.stdout:
            output_parts.append(result.stdout)
        if result.stderr:
            stderr_lines = result.stderr.strip().split("\n")
            output_parts.extend(f"[stderr] {line}" for line in stderr_lines)

        output = "\n".join(output_parts) if output_parts else "<no output>"

        truncated = False
        if len(output) > self._max_output_bytes:
            output = output[: self._max_output_bytes]
            output += f"\n\n... Output truncated at {self._max_output_bytes} bytes."
            truncated = True

        if result.returncode != 0:
            output = f"{output.rstrip()}\n\nExit code: {result.returncode}"

        return ExecuteResponse(
            output=output,
            exit_code=result.returncode,
            truncated=truncated,
        )


__all__ = ["InheritedEnvShellBackend", "resolve_virtual_mode_false_path"]
