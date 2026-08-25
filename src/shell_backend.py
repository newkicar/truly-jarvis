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
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from typing import Any

from deepagents.backends.local_shell import DEFAULT_EXECUTE_TIMEOUT, LocalShellBackend
from deepagents.backends.protocol import ExecuteResponse


def _console_encoding() -> str | None:
    """Windows 控制台输出用系统 ANSI 码页（中文 Windows=GBK/mbcs），确定性解码。"""
    return "mbcs" if sys.platform == "win32" else None


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
        # (?<![:\w]) 排除 URL 路径段（https://x/workspace/）
        alt = "|".join(re.escape(p) for p in self._virtual_prefixes) or r"(?!)"
        self._virtual_path_re = re.compile(rf"(?<![:\w])/(?:{alt})/", re.IGNORECASE)

    def _virtual_prefix_error(self, command: str) -> ExecuteResponse | None:
        m = self._virtual_path_re.search(command)
        if not m:
            return None
        prefix = m.group(0)
        return ExecuteResponse(
            output=(
                f"Error: shell 命令包含文件工具专用的虚拟前缀 {prefix!r}——shell 不认识虚拟路径，"
                "cmd 会把它当开关参数静默忽略或报语法错误。\n"
                f"shell 的工作目录就是项目根（{self.cwd}）。请改用相对路径"
                "（如 tmp-javis-demo/xxx）或真实磁盘路径；/workspace/ 前缀只用于文件工具"
                "（write_file/ls/read_file 等，会自动创建父目录）。"
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


__all__ = ["InheritedEnvShellBackend"]
