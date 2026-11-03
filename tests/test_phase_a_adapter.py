# -*- coding: utf-8 -*-
"""Phase A headless adapter 契约测试（Local Dots 复用 Jarvis 的前置验收）。

覆盖 .scratch/local-dots-v1/issues 中 Phase A 检查单：
1. 无 TUI 导入——headless import src.agent 不拉入 textual；
2. 公开入口——jarvis 包只导出 create_jarvis（懒加载，import jarvis 不拉 core）；
3. 工厂契约——workspace 参数落地（FilesystemBackend 根在 workspace），
   checkpointer 由调用方注入（按 task 独立 thread + 重启恢复核对）；
4. 纪律——src/jarvis 包内无 os.chdir 全局切换；
5. 异步通路——.ainvoke 全链路（中间件 awrap_model_call 正确 await）。

自目录纪律：禁用 tmp_path/tempfile.mkdtemp（本机 WinError 5 中毒），
用 os.makedirs 自建 tests/tmp_phase_a/。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TMP_DIR = REPO_ROOT / "tests" / "tmp_phase_a"

HEADLESS_PROBE = (
    "import sys; import src.agent; "
    "assert 'textual' not in sys.modules, 'headless import pulled in TUI'"
)


def _probe_cwd():
    os.environ["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")
    return REPO_ROOT


def test_headless_import_does_not_pull_textual():
    """TUI/Core 分离：import src.agent（不 import src.gui）不加载 textual。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-c", HEADLESS_PROBE],
        cwd=_probe_cwd(),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr


def test_public_entry_exports_create_jarvis():
    """jarvis 包是唯一公开入口：from jarvis import create_jarvis。"""
    from jarvis import create_jarvis

    assert callable(create_jarvis)


def test_factory_workspace_rooting_and_checkpointer_injection():
    """workspace 参数决定 FilesystemBackend 根；checkpointer 按调用方注入。"""
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.checkpoint.memory import InMemorySaver

    class FakeModel(BaseChatModel):
        def _generate(self, messages, *args, **kwargs):
            return self._gen(messages)

        async def _agenerate(self, messages, *args, **kwargs):
            return self._gen(messages)

        def _gen(self, messages):
            last = messages[-1]
            if isinstance(last, HumanMessage):
                msg = AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "read_file",
                        "args": {"file_path": "/workspace/notes.txt"},
                        "id": "c1",
                        "type": "tool_call",
                    }],
                )
            elif isinstance(last, ToolMessage):
                msg = AIMessage(content="GOT:" + str(last.content)[:120])
            else:
                msg = AIMessage(content="done")
            return ChatResult(generations=[ChatGeneration(message=msg)])

        def bind_tools(self, *args, **kwargs):
            return self

        @property
        def _llm_type(self):
            return "phase-a-fake"

    from jarvis import create_jarvis

    ws = TMP_DIR / "workspace_rooting"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "notes.txt").write_text("phase-a-filesystem-rooted", encoding="utf-8")

    marker = InMemorySaver()
    graph = create_jarvis(
        str(ws),
        marker,
        model=FakeModel(),
        env_overrides={
            "BASE_URL": "http://127.0.0.1:9/v1",
            "API_KEY": "sk-phase-a-test",
            "MODEL_ID": "phase-a-fake",
            "TAVILY_KEY": "phase-a-test",
        },
    )
    assert graph.checkpointer is marker

    import asyncio

    async def run():
        out = await graph.ainvoke(
            {"messages": [HumanMessage(content="read notes please")]},
            config={"configurable": {"thread_id": "phase-a-t1"}},
        )
        return out

    out = asyncio.run(run())
    msgs = out["messages"]
    tool_msgs = [m for m in msgs if isinstance(m, ToolMessage)]
    assert any("phase-a-filesystem-rooted" in str(m.content) for m in tool_msgs), (
        "read_file 未从 workspace 参数根目录读到内容——FilesystemBackend 根未落地"
    )


def test_no_os_chdir_in_src_or_package():
    """纪律：Jarvis 文件后端与 shell 工具显式传 workspace，禁 os.chdir 全局切换。"""
    import re

    offenders = []
    for root in ('src', 'jarvis'):
        for path in (REPO_ROOT / root).rglob('*.py'):
            for lineno, line in enumerate(
                path.read_bytes().decode('utf-8', 'replace').splitlines(), 1
            ):
                stripped = line.strip()
                if 'os.chdir(' in stripped and not stripped.startswith('#'):
                    offenders.append('%s:%d: %s' % (path.relative_to(REPO_ROOT), lineno, stripped))
    assert not offenders, '发现 os.chdir 全局切换:\n' + '\n'.join(offenders)


def test_ainvoke_full_middleware_chain():
    """异步通路：带默认中间件（plan_mode/resilience）的 .ainvoke 全链路不炸。"""
    import asyncio

    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage, HumanMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.checkpoint.memory import InMemorySaver

    class EchoModel(BaseChatModel):
        def _generate(self, messages, *args, **kwargs):
            return ChatResult(generations=[
                ChatGeneration(message=AIMessage(content="echo:" + str(messages[-1].content)))
            ])

        async def _agenerate(self, messages, *args, **kwargs):
            return self._generate(messages, *args, **kwargs)

        def bind_tools(self, *args, **kwargs):
            return self

        @property
        def _llm_type(self):
            return "phase-a-echo"

    from jarvis import create_jarvis

    ws = TMP_DIR / "async_chain_ws"
    ws.mkdir(parents=True, exist_ok=True)
    graph = create_jarvis(
        str(ws),
        InMemorySaver(),
        model=EchoModel(),
        env_overrides={
            "BASE_URL": "http://127.0.0.1:9/v1",
            "API_KEY": "sk-phase-a-test",
            "MODEL_ID": "phase-a-echo",
            "TAVILY_KEY": "phase-a-test",
        },
    )

    async def run():
        return await graph.ainvoke(
            {"messages": [HumanMessage(content="ping")]},
            config={"configurable": {"thread_id": "phase-a-async"}},
        )

    out = asyncio.run(run())
    assert str(out["messages"][-1].content) == "echo:ping"
