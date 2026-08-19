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

from src.commands import project_root
from src.config import Config
from src.inbox_snapshot_middleware import InboxSnapshotMiddleware
from src.permissions import (
    build_permission_deny_middleware,
    build_permission_interrupts,
    build_permission_interrupts_from_state,
)
from src.rag import make_semantic_search_tool
from src.subagents import build_knowledge_keeper, build_researcher
from src.system_context import make_get_system_context_tool
from src.vault_guard import VaultWriteGuardMiddleware
from src.tools import make_deep_search_tool, make_quick_search_tool, make_search_tool
from src.wiki import make_wiki_tools

MAIN_SYSTEM_PROMPT = """你是 JARVIS，个人 AI 助手，专注扩展用户的心智。

## 目标
准确回答用户**当前这一轮**的问题。需要多步时自行拆解、执行、验证、纠错；满足完成标准后交付，不擅自扩大范围。

## 完成标准
- **事实问答**：有可靠来源再答；无来源则说明不确定，不编造。
- **本机时间/日期/星期**：来自 `get_system_context` 或 system-context skill，不用训练记忆猜测。
- **用户所在地**：JARVIS 无 GPS，地址不写死在 `javis.json` 或 profile。用户问了位置时，说明无法自动定位；仅依据当轮对话中用户的说明作答。
- **检索/调研**：覆盖用户原问题的要点即可，不自动升级成报告或 vault 落盘。
- **写入 vault**：仅当用户明确要求保存、沉淀、整理报告时，才写 `/vault/Inbox/` 或 `/vault/Reports/`。
- **代码/命令类任务**：能验证则验证（运行测试、检查输出）；无法验证时说明建议的检查步骤，不谎称已完成。

## 约束
- 文件路径只用 `/workspace/`（项目）、`/vault/`（Obsidian）、`/memories/`（用户记忆）。
- researcher：联网检索或 `/vault/` 知识库检索；knowledge_keeper：值得长期保留或用户要求沉淀时。
- 委派子代理时传递用户原意，不扩写成「全面调研/行业动态报告」。
- 多角度并行研究可用 CodeInterpreter + `task()` fan-out 多个 researcher，再合并。

## 停止规则
- 已能完整回答用户**本轮**问题时，立即停止，不开启第二个交付物。
- 工具失败时，换合法手段重试或说明原因，不转去做用户未要求的任务。
- 检索证据已够时，停止搜索，避免无限循环。

## 输出
简体中文，简洁有结构。引用本地知识时用 `/vault/` 路径。
"""


def build_main_prompt() -> str:
    """主系统提示词（结果导向；日期/时间/地点细节在 system-context skill）。"""
    return MAIN_SYSTEM_PROMPT


def _skill_sources(config: Config) -> list[str]:
    """deepagents 技能源：backend 虚拟 POSIX 路径（CompositeBackend 下为 /workspace/...）。

    磁盘上的 skills/ 映射到 /workspace/skills/，与 LocalShellBackend 路由一致。
    勿传 Windows 绝对路径——会落到 default StateBackend，导致 skill 找不到。
    """
    root = config.memory_dir.parent
    sources: list[str] = []
    for p in config.skills:
        fs_path = p.resolve() if p.is_absolute() else (root / p).resolve()
        if not fs_path.is_dir():
            continue
        try:
            rel = fs_path.relative_to(root).as_posix().strip("/")
        except ValueError:
            continue
        sources.append(f"/workspace/{rel}/" if rel else "/workspace/")
    return list(dict.fromkeys(sources))


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
    mcp_tools: list | None = None,
):
    """组装主代理。

    未传 model 时用 config 构造真实模型；checkpointer 默认 InMemorySaver
    （生产用 SqliteSaver，由调用方在 with 块内传入）。
    permission_state 由外部传入（如 main.py）时复用同一引用，保证
    always approve 等运行时修改与 deny middleware / when 谓词联动。
    mcp_tools 为 MCP server 加载出的额外工具（仅主代理），由调用方
    （如 main.py 经 src.mcps.load_mcp_tools）在启动时一次性注入。
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
    rag_tool = make_semantic_search_tool(
        config.vault_path,
        config.memory_dir / "rag-index",
        base_url=config.rag_ollama_base_url,
        embed_model=config.rag_embed_model,
    )
    if permission_state is not None:
        interrupt_on = build_permission_interrupts_from_state(permission_state)
    else:
        interrupt_on, permission_state = build_permission_interrupts(config.permissions)
    deny_middleware = build_permission_deny_middleware(permission_state)
    vault_guard = VaultWriteGuardMiddleware()
    root = project_root()
    inbox_snapshot = InboxSnapshotMiddleware(root, config.vault_path)
    researcher = build_researcher(
        search_tools=search_tools, wiki_tools=wiki_tools, rag_tool=rag_tool,
        deny_middleware=deny_middleware,
    )
    knowledge_keeper = build_knowledge_keeper(
        deny_middleware=deny_middleware,
        project_root=root,
        vault_path=config.vault_path,
    )

    memory = [
        str(f).replace("\\", "/")
        for f in sorted(config.memory_dir.glob("*.md"))
        if f.name.lower() != "readme.md"
    ]

    skills = _skill_sources(config)
    main_tools = [make_get_system_context_tool(), *(mcp_tools or [])]

    return create_deep_agent(
        model=model,
        backend=_make_backend(config),
        subagents=[researcher, knowledge_keeper],  # type: ignore[list-item]
        system_prompt=build_main_prompt(),
        tools=main_tools,
        middleware=[
            CodeInterpreterMiddleware(subagents=True),
            deny_middleware,
            vault_guard,
            inbox_snapshot,
        ],  # type: ignore[list-item]
        memory=memory,
        skills=skills,
        interrupt_on=interrupt_on,  # HITL 审批（javis.json permissions）
        checkpointer=checkpointer,
        store=store,
        name="javis",
    )