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
from deepagents.backends import (
    CompositeBackend,
    FilesystemBackend,
    LocalShellBackend,
    StateBackend,
)
from langchain_quickjs import CodeInterpreterMiddleware

from src.config import Config
from src.permissions import (
    build_permission_deny_middleware,
    build_permission_interrupts,
    build_permission_interrupts_from_state,
)
from src.rag import make_semantic_search_tool
from src.subagents import build_knowledge_keeper, build_researcher
from src.tools import make_deep_search_tool, make_quick_search_tool, make_search_tool
from src.wiki import make_wiki_tools

MAIN_SYSTEM_PROMPT = """你是 JARVIS，一个个人 AI 助手，专注扩展用户的心智。

## 能力
- 调研/检索类问题（最新动态、行业资讯、外部事实）→ 委派 researcher 子代理。
- 「我的笔记/知识库」类问题 → 委派 researcher 检索本地 Obsidian（/vault/）。
- 对话中产生了「值得长期保留的新知识」（研究结论、已核实的行业动态、用户要求记住的事实）→ 委派 knowledge_keeper 子代理整理成带 wikilink 的笔记写入 /vault/Inbox/。
- 复杂/多角度研究（需并行覆盖多个独立维度）→ 写 JS 脚本用 task() + Promise.all fan-out 多个 researcher 子代理，再合并结果。
- 闲聊、纯知识问答、与本地/时效无关的问题 → 直接回答，不委派。

## 委派 researcher 的规则（重要）
- 委派时把**用户的原始问题**作为 task 内容传给 researcher，不要自行扩写成「完整时间表/全面调研/详细报告」等更复杂的任务——researcher 会根据问题复杂度自动选档（快/中/深）。
- 需要联网的简单事实问题（如「今天天气」「哪天出伏」）也正常委派，researcher 会用轻量搜索快速返回，几秒即可。
- 涉及时效的问题（年份、节假日、最新事件）先看「今天日期」再决定查哪年，不要凭记忆猜年份。

## 输出
回答用简体中文，简洁、有结构。引用本地知识库时用 /vault/ 路径。
"""


def build_main_prompt() -> str:
    """注入今天日期的主系统提示词。"""
    from datetime import date

    today = date.today().isoformat()
    return (
        "今天是 " + today + "。\n\n" + MAIN_SYSTEM_PROMPT
    )


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
            "/workspace/": LocalShellBackend(root_dir=str(project_root), virtual_mode=True),
            "/vault/": FilesystemBackend(root_dir=str(config.vault_path), virtual_mode=True),
            "/memories/": FilesystemBackend(root_dir=str(config.memory_dir), virtual_mode=True),
        },
    )


def build_agent(
    config: Config,
    model: BaseChatModel | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    store: BaseStore | None = None,
    permission_state: dict | None = None,
):
    """组装主代理。

    未传 model 时用 config 构造真实模型；checkpointer 默认 InMemorySaver
    （生产用 SqliteSaver，由调用方在 with 块内传入）。
    permission_state 由外部传入（如 main.py）时复用同一引用，保证
    always approve 等运行时修改与 deny middleware / when 谓词联动。
    """
    model = model or _make_model(config)
    checkpointer = checkpointer or InMemorySaver()
    store = store or InMemoryStore()

    search_tools = [
        make_quick_search_tool(config.tavily_key),
        make_search_tool(config.tavily_key),
        make_deep_search_tool(config.tavily_key),
    ]
    wiki_tools = make_wiki_tools(config.vault_path)
    rag_tool = make_semantic_search_tool(config.vault_path, config.memory_dir / "rag-index")
    if permission_state is not None:
        interrupt_on = build_permission_interrupts_from_state(permission_state)
    else:
        interrupt_on, permission_state = build_permission_interrupts(config.permissions)
    deny_middleware = build_permission_deny_middleware(permission_state)
    researcher = build_researcher(
        search_tools=search_tools, wiki_tools=wiki_tools, rag_tool=rag_tool,
        deny_middleware=deny_middleware,
    )
    knowledge_keeper = build_knowledge_keeper(deny_middleware=deny_middleware)

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
        system_prompt=build_main_prompt(),
        middleware=[CodeInterpreterMiddleware(subagents=True), deny_middleware],  # type: ignore[list-item]  # 动态子代理 fan-out + deny 拦截
        memory=memory,
        skills=skills,
        interrupt_on=interrupt_on,  # HITL 审批（javis.json permissions）
        checkpointer=checkpointer,
        store=store,
        name="javis",
    )