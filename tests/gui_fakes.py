"""GUI 测试共享夹具（自建目录纪律：不用 tmp_path —— 本机 WinError 5 中毒）。

目录统一建在 <repo>/.scratch/gui-test-tmp/<uuid>/（gitignore 覆盖）。
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = REPO_ROOT / ".scratch" / "gui-test-tmp"


def new_home() -> Path:
    """全新项目 home（jarvis.json + .env + checkpoints/ + memory/）。"""
    home = TEST_ROOT / f"home-{uuid.uuid4().hex[:10]}"
    home.mkdir(parents=True)
    (home / "checkpoints").mkdir()
    (home / "memory").mkdir()
    (home / "jarvis.json").write_text(
        json.dumps({
            "permissions": {"execute": {"*": "ask"}, "write_file": {"*": "ask"}},
        }),
        encoding="utf-8",
    )
    (home / ".env").write_text(
        "BASE_URL: https://fake.example/v1\nAPI_KEY: sk-fake\nMODEL_ID: fake-model\n"
        "TAVILY_KEY: tvly-fake\n",
        encoding="utf-8",
    )
    return home


def cleanup_home(home: Path) -> None:
    shutil.rmtree(home, ignore_errors=True)


FINAL_MD = (
    "## 完成\n\n- `execute`：审批 → 执行 ✓\n- 流式 Markdown：代码块渲染\n\n"
    "```python\nprint('gui streaming ok')\n```\n"
)


class ScriptedMockModel(BaseChatModel):
    """确定性 HITL 脚本模型（原型 T-006 提升）：execute 卡 →（拒绝则改道 write_file）→ 最终回答。"""

    def _next_tool_calls(self, messages: list[BaseMessage]):
        idx = max(
            (i for i, m in enumerate(messages) if getattr(m, "type", "") == "human"),
            default=-1,
        )
        scope = messages[idx + 1 :]
        last_ai_tc = None
        last_tool = None
        for m in scope:
            if isinstance(m, AIMessage) and m.tool_calls:
                last_ai_tc = m.tool_calls
            if getattr(m, "type", "") == "tool":
                last_tool = m
        if last_tool is None:
            return [
                {
                    "name": "execute",
                    "args": {"command": 'echo "hello jarvis gui"'},
                    "id": "call-mock-exec",
                    "type": "tool_call",
                }
            ]
        tool_text = last_tool.content or ""
        first_name = last_ai_tc[0]["name"] if last_ai_tc else "?"
        if first_name == "execute" and "拒绝" in tool_text:
            return [
                {
                    "name": "write_file",
                    "args": {
                        "file_path": "hello.txt",
                        "content": "hello from jarvis gui\nsecond line\n",
                    },
                    "id": "call-mock-write",
                    "type": "tool_call",
                }
            ]
        return None

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        tc = self._next_tool_calls(messages)
        if tc:
            lead = "（mock）先跑一条命令验证执行通道。" if tc[0]["name"] == "execute" else "（mock）改道：写文件方案。"
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=lead, tool_calls=tc))])
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=FINAL_MD))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        tc = self._next_tool_calls(messages)
        if tc:
            lead = "（mock）先跑一条命令验证执行通道。" if tc[0]["name"] == "execute" else "（mock）改道：写文件方案。"
            yield ChatGenerationChunk(message=AIMessageChunk(content=lead))
            yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_calls=tc))
            return
        text = FINAL_MD
        for i in range(0, len(text), 8):
            yield ChatGenerationChunk(message=AIMessageChunk(content=text[i : i + 8]))

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self) -> str:
        return "jarvis-gui-scripted-mock"
