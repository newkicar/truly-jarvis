"""主代理组装测试。

Seam: src.agent.build_agent（输入 config → 输出可调用的 deep agent）。
用自定义 fake 模型（支持 bind_tools）模拟模型，不触网、不碰真 vault，
验证组装成功且 invoke 能返回消息。
"""
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from src.agent import build_agent
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


def test_build_agent_assembles(tmp_path):
    cfg = make_fake_config(tmp_path)
    agent = build_agent(cfg)
    assert agent is not None
    assert callable(getattr(agent, "invoke", None))


def test_build_agent_invoke_returns_message(tmp_path):
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


def test_build_agent_with_sqlite_checkpointer_assembles(tmp_path):
    cfg = make_fake_config(tmp_path)
    from langgraph.checkpoint.sqlite import SqliteSaver

    with SqliteSaver.from_conn_string(str(tmp_path / "cp.db")) as checkpointer:
        agent = build_agent(cfg, checkpointer=checkpointer)
        assert agent is not None


def test_build_agent_loads_memory_md_files(tmp_path, monkeypatch):
    """memory/ 下的记忆 md（除 README）应作为 memory= 注入 create_deep_agent。"""
    import src.agent as agent_mod
    from src.agent import create_deep_agent

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


def test_build_knowledge_keeper_shape():
    """knowledge_keeper 子代理应含 name/description/system_prompt，且约束只写 Inbox。"""
    kk = build_knowledge_keeper()
    assert kk["name"] == "knowledge_keeper"
    assert kk["description"]
    assert "/vault/Inbox/" in kk["system_prompt"]
    assert "只新增" in kk["system_prompt"]


def test_stream_events_v3_does_not_throw_and_produces_text(tmp_path):
    """票 11：stream_events(version='v3') 用 fake 模型不抛错，且能产出最终文本。"""
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