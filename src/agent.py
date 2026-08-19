"""主代理组装。

model + CompositeBackend（default=StateBackend；/workspace /vault /memories 路由）
+ subagents + memory + checkpointer(SqliteSaver) + store。见设计文档 §5.2/§6。
"""
from datetime import datetime

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
from src.deprecated_paths import DeprecatedPathMiddleware
from src.inbox_snapshot_middleware import InboxSnapshotMiddleware
from src.permissions import (
    build_permission_deny_middleware,
    build_permission_interrupts,
    build_permission_interrupts_from_state,
)
from src.config_agents import build_config_subagents
from src.rag import make_semantic_search_tool
from src.skill_paths import skill_backend_routes, skill_virtual_sources
from src.subagents import build_knowledge_keeper, build_researcher
from src.vault_guard import VaultWriteGuardMiddleware
from src.tools import make_deep_search_tool, make_quick_search_tool, make_search_tool
from src.wiki import make_wiki_tools

_WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")

MAIN_SYSTEM_PROMPT = """你是 JARVIS，个人 AI 助手，专注扩展用户的心智。

**身份（用户问「你是谁」时）：**
- 你是 **JARVIS**，用户的个人 AI 助手；**不要**自称 muse-spark、mimo、GPT、DeepSeek 等底层模型名。
- 仅当用户**明确**问底层模型 / API / 技术实现时，才可说明当前 `MODEL_ID` 配置。

## 目标
准确完成用户**本轮**提出的问题或任务，不擅自扩大范围。

## 工作方式
接到提问或任务时，先弄清要交付什么。简单问题直接回答。
多步任务：先计划步骤，再逐步执行，完成后核对结果；某步失败则换合法手段重试或说明原因，不要卡死在一种做法上。
需要信息或执行时，按需使用 skills、MCP 工具、内置工具（含 `execute`）、子代理——不凭训练记忆硬猜事实。

**日期 / 时间 / 位置（不要读 skill，不要写 JS）：**
- 问「今天几号 / 什么日期 / 星期几」→ **直接根据本提示词「当前会话」里的「今天是 …」一行回答**，不要读任何 skill 或文件，不要调工具。
- 问「现在几点 / 精确时刻」→ **只用 `execute` 读本机 shell**，例如 Windows：
  `powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"`。**禁止** CodeInterpreter、eval、JS、Python REPL。
- 问「我在哪 / 什么城市」→ **只用 `execute` 查 IP**，例如：
  `curl -s http://ip-api.com/json/?lang=zh-CN`。**禁止** CodeInterpreter / eval；不要读 `javis.json` 或 `/memories/user-profile.md`。
- 以上问题 **禁止** 委派 researcher；**禁止** 读 `system-context`（已废弃）。

## 完成标准
- **事实**：有可靠来源再答；没有则说明不确定，不编造。
- **调研**：需要联网或检索 vault 时再委派 researcher；覆盖用户原问题即可，不自动升级成报告或写入 vault。
- **落盘**：仅当用户明确要求保存、沉淀或整理报告时，才写 `/vault/Inbox/` 或 `/vault/Reports/`。
- **可验证任务**：能跑则跑（测试、命令输出）；无法验证时说明建议的检查步骤，不谎称已完成。

## 约束
- 文件路径只用 `/workspace/`（项目）、`/vault/`（Obsidian）、`/memories/`（用户记忆）、`/skills/`（用户全局 skill）、`/builtin-skills/`（随安装包 skill）。
- 值得长期保留或用户要求记住 → knowledge_keeper。
- 委派时传递用户原意，不扩写成「全面调研 / 行业动态报告」。
- 多角度并行**研究**可用 CodeInterpreter + `task()` fan-out 多个 researcher，再合并（**不**用于查时间/位置）。

## 输出
简体中文，简洁有结构。引用本地知识时用 `/vault/` 路径。
"""


def session_date_line(*, now: datetime | None = None) -> str:
    """启动时会话日期行（仅日期+星期，不含时分秒）。"""
    current = now or datetime.now()
    return (
        f"今天是 {current.strftime('%Y-%m-%d')} {_WEEKDAYS[current.weekday()]}。"
        "（用户问今天日期/星期几时，直接用本行作答，勿读 skill 或调工具。）"
    )


def build_main_prompt(*, now: datetime | None = None) -> str:
    """主系统提示词：会话日期 + 结果导向正文。"""
    date_line = session_date_line(now=now)
    return f"## 当前会话\n{date_line}\n\n{MAIN_SYSTEM_PROMPT}"


def _make_model(config: Config) -> BaseChatModel:
    return ChatOpenAI(
        base_url=config.base_url,
        api_key=SecretStr(config.api_key),
        model=config.model_id,
        temperature=0,
    )


def _make_backend(config: Config) -> CompositeBackend:
    routes: dict[str, FilesystemBackend | LocalShellBackend] = {
        "/workspace/": LocalShellBackend(root_dir=str(config.project_root), virtual_mode=True),
        "/vault/": FilesystemBackend(root_dir=str(config.vault_path), virtual_mode=True),
        "/memories/": FilesystemBackend(root_dir=str(config.memory_dir), virtual_mode=True),
    }
    for vpath, fs_path in skill_backend_routes(config).items():
        routes[vpath] = FilesystemBackend(root_dir=str(fs_path), virtual_mode=True)
    return CompositeBackend(default=StateBackend(), routes=routes)


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
    deprecated_guard = DeprecatedPathMiddleware()
    vault_guard = VaultWriteGuardMiddleware()
    root = config.project_root
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
    config_subagents = build_config_subagents(
        config.agents,
        default_deny_middleware=deny_middleware,
    )

    memory = [
        str(f).replace("\\", "/")
        for f in sorted(config.memory_dir.glob("*.md"))
        if f.name.lower() != "readme.md"
    ]

    skills = skill_virtual_sources(config)
    main_tools = list(mcp_tools or [])

    return create_deep_agent(
        model=model,
        backend=_make_backend(config),
        subagents=[researcher, knowledge_keeper, *config_subagents],  # type: ignore[list-item]
        system_prompt=build_main_prompt(),
        tools=main_tools,
        middleware=[
            CodeInterpreterMiddleware(subagents=True),
            deny_middleware,
            deprecated_guard,
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
