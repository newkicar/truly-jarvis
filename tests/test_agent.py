"""主代理组装测试。

Seam: src.agent.build_agent（输入 config → 输出可调用的 deep agent）。
用自定义 fake 模型（支持 bind_tools）模拟模型，不触网、不碰真 vault，
验证组装成功且 invoke 能返回消息。
"""
from datetime import datetime

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from src.agent import build_agent, build_main_prompt, JARVIS_HARNESS_SUFFIX
from src.skill_paths import USER_SKILLS_VPATH
from src.subagents import build_knowledge_keeper
from conftest import make_fake_config


class ToolCapableFake(BaseChatModel):
    """支持 bind_tools 的假模型，始终返回固定回复。"""

    reply: str = "我是 JAVIS，你好！"
    bind_tools_calls: int = 0

    def bind_tools(self, tools, **kwargs):
        self.bind_tools_calls += 1
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=self.reply))]
        )

    @property
    def _llm_type(self) -> str:
        return "tool-capable-fake"


def test_build_agent_assembles(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    cfg = make_fake_config(tmp_path)
    agent = build_agent(cfg)
    assert agent is not None
    assert callable(getattr(agent, "invoke", None))


def test_build_main_prompt_injects_session_date():
    """会话日期写入 system prompt；问几号应直接用首行。"""
    prompt = build_main_prompt(now=datetime(2026, 8, 20, 12, 0, 0))
    assert "今天是 2026-08-20 星期四。" in prompt
    assert "可直接用本行作答" in prompt
    assert "12:00" not in prompt
    assert "目标" in prompt
    assert "工作方式" in prompt
    assert "完成标准" in prompt
    assert "停止规则" not in prompt
    assert "Skills" in prompt or "skills" in prompt
    assert "execute" in prompt
    assert "quick_search" in prompt
    assert "JARVIS" in prompt
    assert "muse-spark" not in prompt.lower() or "不要" in prompt
    assert "Harness" in JARVIS_HARNESS_SUFFIX
    assert "简单问题直接回答" not in prompt
    assert "天气" not in prompt
    assert "Reports" in prompt


def test_build_agent_uses_build_main_prompt(tmp_path, monkeypatch):
    """create_deep_agent 收到的 system_prompt 应为 build_main_prompt() 输出。"""
    import src.agent as agent_mod
    from src.agent import create_deep_agent

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    cfg = make_fake_config(tmp_path)
    captured = {}

    def spy(**kwargs):
        captured.update(kwargs)
        return create_deep_agent(**kwargs)

    monkeypatch.setattr(agent_mod, "create_deep_agent", spy)
    model = ToolCapableFake(reply="ok")
    build_agent(cfg, model=model)

    assert captured.get("system_prompt") == build_main_prompt(config=cfg)
    assert "工作方式" in captured.get("system_prompt", "")
    tool_names = [t.name for t in captured.get("tools", [])]
    assert "quick_search" in tool_names


def test_build_agent_invoke_returns_message(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    cfg = make_fake_config(tmp_path)
    model = ToolCapableFake(reply="我是 JARVIS，你好！")
    agent = build_agent(cfg, model=model)
    result = agent.invoke(
        {"messages": [HumanMessage(content="你好")]},
        config={"configurable": {"thread_id": "t1"}},
    )
    messages = result["messages"]
    assert isinstance(messages[-1], AIMessage)
    assert "JARVIS" in messages[-1].content


def test_build_agent_with_sqlite_checkpointer_assembles(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    cfg = make_fake_config(tmp_path)
    from langgraph.checkpoint.sqlite import SqliteSaver

    with SqliteSaver.from_conn_string(str(tmp_path / "cp.db")) as checkpointer:
        agent = build_agent(cfg, checkpointer=checkpointer)
        assert agent is not None


def test_build_agent_injects_mcp_tools(tmp_path, monkeypatch):
    """mcp_tools 应作为 tools= 注入 create_deep_agent（仅主代理）。"""
    import src.agent as agent_mod
    from langchain_core.tools import StructuredTool
    from src.agent import create_deep_agent

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    cfg = make_fake_config(tmp_path)
    captured = {}

    def spy(**kwargs):
        captured.update(kwargs)
        return create_deep_agent(**kwargs)

    monkeypatch.setattr(agent_mod, "create_deep_agent", spy)
    model = ToolCapableFake(reply="ok")
    from pydantic import BaseModel

    class _Args(BaseModel):
        query: str

    fake_tools = [
        StructuredTool(
            name="git_status",
            description="git status",
            args_schema=_Args,
            func=lambda query: "ok",
        )
    ]
    build_agent(cfg, model=model, mcp_tools=fake_tools)

    tool_names = [t.name for t in captured.get("tools", [])]
    assert tool_names == ["quick_search", "git_status"]


def test_build_agent_no_mcp_tools_still_has_quick_search(tmp_path, monkeypatch):
    """未传 mcp_tools 时仍应注入 quick_search。"""
    import src.agent as agent_mod
    from src.agent import create_deep_agent

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    cfg = make_fake_config(tmp_path)
    captured = {}

    def spy(**kwargs):
        captured.update(kwargs)
        return create_deep_agent(**kwargs)

    monkeypatch.setattr(agent_mod, "create_deep_agent", spy)
    model = ToolCapableFake(reply="ok")
    build_agent(cfg, model=model)

    tool_names = [t.name for t in captured.get("tools", [])]
    assert tool_names == ["quick_search"]


def test_build_agent_registers_skill_sources(tmp_path, monkeypatch):
    """skills= 应含用户全局层。"""
    import src.agent as agent_mod
    from dataclasses import replace
    from src.agent import create_deep_agent

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    from src.project_paths import ensure_user_home

    ensure_user_home()
    project = tmp_path / "proj"
    skills_root = project / "skills"
    skills_root.mkdir(parents=True)
    cfg = replace(make_fake_config(project), skills=(skills_root,))
    captured = {}

    def spy(**kwargs):
        captured.update(kwargs)
        return create_deep_agent(**kwargs)

    monkeypatch.setattr(agent_mod, "create_deep_agent", spy)
    build_agent(cfg, model=ToolCapableFake(reply="ok"))
    assert USER_SKILLS_VPATH in captured.get("skills", [])
    assert "/workspace/skills/" in captured.get("skills", [])


def test_build_agent_loads_memory_md_files(tmp_path, monkeypatch):
    """memory/ 下的记忆 md（除 README）应作为 memory= 注入 create_deep_agent。"""
    import src.agent as agent_mod
    from src.agent import create_deep_agent

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    cfg = make_fake_config(tmp_path)
    (cfg.memory_dir).mkdir(parents=True, exist_ok=True)
    (cfg.memory_dir / "README.md").write_text("# 说明\n", encoding="utf-8")
    (cfg.memory_dir / "user-profile.md").write_text("# 用户资料\n- 偏好：表格\n", encoding="utf-8")

    captured = {}

    def spy(**kwargs):
        captured.update(kwargs)
        return create_deep_agent(**kwargs)

    monkeypatch.setattr(agent_mod, "create_deep_agent", spy)
    model = ToolCapableFake(reply="ok")
    build_agent(cfg, model=model)

    memory = captured.get("memory", [])
    assert any(p.endswith("user-profile.md") for p in memory)
    assert not any(p.endswith("README.md") for p in memory)


def test_build_agent_registers_researcher_and_knowledge_keeper(tmp_path, monkeypatch):
    """create_deep_agent 的 subagents 应同时含 researcher 与 knowledge_keeper。"""
    import src.agent as agent_mod
    from src.agent import create_deep_agent

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    cfg = make_fake_config(tmp_path)
    captured = {}

    def spy(**kwargs):
        captured.update(kwargs)
        return create_deep_agent(**kwargs)

    monkeypatch.setattr(agent_mod, "create_deep_agent", spy)
    model = ToolCapableFake(reply="ok")
    build_agent(cfg, model=model)

    subagents = captured.get("subagents", [])
    names = {s.get("name") for s in subagents}
    assert {"researcher", "knowledge_keeper"} <= names


def test_build_agent_wires_deny_middleware_and_shared_state(tmp_path, monkeypatch):
    """deny middleware 应注入主代理与子代理，且与外部传入的 permission_state 共享引用。"""
    import src.agent as agent_mod
    from src.agent import create_deep_agent
    from src.permissions import (
        PermissionDenyMiddleware,
        build_permission_interrupts,
    )

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    cfg = make_fake_config(tmp_path)
    captured = {}

    def spy(**kwargs):
        captured.update(kwargs)
        return create_deep_agent(**kwargs)

    monkeypatch.setattr(agent_mod, "create_deep_agent", spy)
    model = ToolCapableFake(reply="ok")

    _interrupt_on, permission_state = build_permission_interrupts({"execute": "deny"})
    build_agent(cfg, model=model, permission_state=permission_state)

    mws = captured.get("middleware", [])
    deny_mws = [m for m in mws if isinstance(m, PermissionDenyMiddleware)]
    assert deny_mws, "主代理应挂 PermissionDenyMiddleware"
    assert deny_mws[0].state is permission_state, "deny middleware 应共享外部 state"

    for sub in captured.get("subagents", []):
        sub_mws = sub.get("middleware", [])
        assert any(isinstance(m, PermissionDenyMiddleware) for m in sub_mws), (
            f"子代理 {sub.get('name')} 应挂 deny middleware"
        )


def test_build_knowledge_keeper_shape():
    """knowledge_keeper 子代理应含 name/description/system_prompt，且约束只写 Inbox。"""
    kk = build_knowledge_keeper()
    assert kk["name"] == "knowledge_keeper"
    assert kk["description"]
    assert "/vault/Inbox/" in kk["system_prompt"]  # type: ignore[operator]
    assert "只新增" in kk["system_prompt"]  # type: ignore[operator]


def test_make_backend_supports_execute(tmp_path, monkeypatch):
    """default backend 应为 LocalShellBackend，使 execute 进入工具 schema。"""
    from deepagents.middleware.filesystem import supports_execution

    from src.agent import _make_backend

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    cfg = make_fake_config(tmp_path)
    backend = _make_backend(cfg)
    assert supports_execution(backend)


def test_build_agent_includes_todo_list_middleware(tmp_path, monkeypatch):
    """TodoListMiddleware 应注入主代理以启用 write_todos。"""
    import src.agent as agent_mod
    from langchain.agents.middleware import TodoListMiddleware
    from src.agent import create_deep_agent

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    cfg = make_fake_config(tmp_path)
    captured = {}

    def spy(**kwargs):
        captured.update(kwargs)
        return create_deep_agent(**kwargs)

    monkeypatch.setattr(agent_mod, "create_deep_agent", spy)
    build_agent(cfg, model=ToolCapableFake(reply="ok"))

    mws = captured.get("middleware", [])
    assert any(isinstance(m, TodoListMiddleware) for m in mws)


def test_build_agent_registers_harness_profile(tmp_path, monkeypatch):
    """应为 model_id 注册 HarnessProfile（deepagents 标准扩展点）。"""
    import src.agent as agent_mod
    from deepagents import HarnessProfile

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    cfg = make_fake_config(tmp_path)
    captured = {}

    def spy(model_id, profile):
        captured["model_id"] = model_id
        captured["profile"] = profile

    monkeypatch.setattr(agent_mod, "register_harness_profile", spy)
    build_agent(cfg, model=ToolCapableFake(reply="ok"))

    assert captured["model_id"] == cfg.model_id
    assert isinstance(captured["profile"], HarnessProfile)
    assert "先工具" in (captured["profile"].system_prompt_suffix or "")


def test_stream_events_v3_does_not_throw_and_produces_text(tmp_path, monkeypatch):
    """票 11：stream_events(version='v3') 用 fake 模型不抛错，且能产出最终文本。"""
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    cfg = make_fake_config(tmp_path)
    model = ToolCapableFake(reply="流式回答")
    agent = build_agent(cfg, model=model)

    stream = agent.stream_events(
        {"messages": [{"role": "user", "content": "你好"}]},
        version="v3",
        config={"configurable": {"thread_id": "stream-test"}, "recursion_limit": 40},
    )

    text_chunks = []
    for kind, item in stream.interleave("messages", "tool_calls", "subagents"):
        if kind == "messages":
            text_chunks.extend(item.text)

    assert "流式回答" in "".join(text_chunks)
