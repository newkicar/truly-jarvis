"""主代理组装。

model + CompositeBackend（default=StateBackend；/workspace /vault /memories 路由）
+ subagents + memory + checkpointer(SqliteSaver) + store。见设计文档 §5.2/§6。
"""
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.memory import InMemoryStore
from langgraph.store.base import BaseStore

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend

from src.config import Config
from src.subagents import build_knowledge_keeper, build_researcher
from src.tools import make_tavily_tool

MAIN_SYSTEM_PROMPT = """你是 JARVIS，一个个人 AI 助手，专注扩展用户的心智。

## 能力
- 调研/检索类问题（最新动态、行业资讯、外部事实）→ 委派 researcher 子代理。
- 「我的笔记/知识库」类问题 → 委派 researcher 检索本地 Obsidian（/vault/）。
- 对话中产生了「值得长期保留的新知识」（研究结论、已核实的行业动态、用户要求记住的事实）→ 委派 knowledge_keeper 子代理整理成带 wikilink 的笔记写入 /vault/Inbox/。
- 闲聊、纯知识问答、与本地/时效无关的问题 → 直接回答，不委派。

## 输出
回答用简体中文，简洁、有结构。引用本地知识库时用 /vault/ 路径。
"""


def _make_model(config: Config) -> BaseChatModel:
    return ChatOpenAI(
        base_url=config.base_url,
        api_key=SecretStr(config.api_key),
        model=config.model_id,
        temperature=0,
    )


def _make_backend(config: Config) -> CompositeBackend:
    project_root = config.memory_dir.parent
    return CompositeBackend(
        default=StateBackend(),
        routes={
            "/workspace/": FilesystemBackend(root_dir=str(project_root), virtual_mode=True),
            "/vault/": FilesystemBackend(root_dir=str(config.vault_path), virtual_mode=True),
            "/memories/": FilesystemBackend(root_dir=str(config.memory_dir), virtual_mode=True),
        },
    )


def build_agent(
    config: Config,
    model: BaseChatModel | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    store: BaseStore | None = None,
):
    """组装主代理。

    未传 model 时用 config 构造真实模型；checkpointer 默认 InMemorySaver
    （生产用 SqliteSaver，由调用方在 with 块内传入）。
    """
    model = model or _make_model(config)
    checkpointer = checkpointer or InMemorySaver()
    store = store or InMemoryStore()

    tavily_tool = make_tavily_tool(config.tavily_key)
    researcher = build_researcher(tavily_tool)
    knowledge_keeper = build_knowledge_keeper()

    memory = [
        str(f).replace("\\", "/")
        for f in sorted(config.memory_dir.glob("*.md"))
        if f.name.lower() != "readme.md"
    ]

    skills = [
        str(p).replace("\\", "/")
        for p in config.skills
        if p.exists() and (p / "SKILL.md").exists()
    ]

    return create_deep_agent(
        model=model,
        backend=_make_backend(config),
        subagents=[researcher, knowledge_keeper],  # type: ignore[list-item]
        system_prompt=MAIN_SYSTEM_PROMPT,
        memory=memory,
        skills=skills,
        checkpointer=checkpointer,
        store=store,
        name="javis",
    )