"""主代理组装。

model + CompositeBackend（default=LocalShellBackend；/workspace /vault /memories 路由）
+ subagents + memory + checkpointer(SqliteSaver) + store。见设计文档 §5.2/§6。
"""
import sys
from datetime import datetime

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.memory import InMemoryStore
from langgraph.store.base import BaseStore

from deepagents import HarnessProfile, create_deep_agent, register_harness_profile
from deepagents.backends import (
    CompositeBackend,
    FilesystemBackend,
    LocalShellBackend,
)
from langchain.agents.middleware import TodoListMiddleware
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

_HARNESS_REGISTERED: set[str] = set()

# deepagents HarnessProfile：通用推理约束，不写场景菜谱（对标 profile system_prompt_suffix）
JARVIS_HARNESS_SUFFIX = """\
## Harness
- 先弄清本轮交付物；≥3 步的任务先用 write_todos 分解（每项带可核对的完成标准），执行中随进度更新状态。
- **执行循环**（任务类工作）：执行 → 核对输出 → 失败即诊断根因 → 修正 → 再执行，直到完成标准满足。报错不是终点，是待处理的数据。
- 可验证的事实：先工具、后结论；某工具失败则换合法手段，都失败则说明不确定——不凭训练记忆硬答，也不在能自行获取时先反问用户。
- **唯一停下条件**：同一目标已用 ≥3 种不同方案尝试仍失败——向用户报告「已尝试清单 + 卡点 + 建议」，不静默放弃，也不原样重试复读。
- 完成声明必须附验证证据（测试/命令输出）；无法验证时说明建议的检查步骤，不谎称已完成。
- 匹配任务时先读相关 SKILL.md（read_file），再按 skill 步骤选 tool / task(researcher)。
- eval / CodeInterpreter 仅用于代码计算与 fan-out，不用于读取系统环境。"""

MUSE_HARNESS_EXTRA = """\
- 你是 agent：优先 tool call，再文字回答。外部/实时/本机事实 → quick_search 或 execute 或 task(researcher)，不要先问用户能否帮你查。"""

TOOL_DESCRIPTION_OVERRIDES = {
    "quick_search": (
        "Search the public internet for facts not in local files or conversation. "
        "Use when the answer depends on external, location-specific, or time-sensitive information. "
        "Call before answering factual questions you cannot verify from context."
    ),
    "execute": (
        "Run a shell command on the local machine. "
        "Use to inspect environment, run programs, or gather facts (time, paths, command output). "
        "Check the command output before claiming success; on failure diagnose the cause, "
        "fix it and re-run with a changed approach instead of repeating the same call. "
        "Do not use CodeInterpreter/eval for environment reads."
    ),
    "task": (
        "Delegate work to a subagent in an isolated context. "
        "Use subagentType researcher for web + /vault/ research, multi-source synthesis, or deep search; "
        "use knowledge_keeper when the user wants to save vetted knowledge to /vault/Inbox/. "
        "Pass the user's intent verbatim in the description."
    ),
    "write_todos": (
        "Create or update a structured task list for multi-step work in this session. "
        "Use when the user request has 3+ distinct steps or asks for planning; "
        "give each item a verifiable completion criterion; "
        "mark items in_progress before working and completed only after verifying."
    ),
}

MAIN_SYSTEM_PROMPT = """你是 JARVIS，个人 AI 助手，专注扩展用户的心智。

**身份（用户问「你是谁」时）：**
- 你是 **JARVIS**，用户的个人 AI 助手；**不要**自称 muse-spark、mimo、GPT、DeepSeek 等底层模型名。
- 仅当用户**明确**问底层模型 / API / 技术实现时，才可说明当前 `MODEL_ID` 配置。

## 目标
准确完成用户**本轮**提出的问题或任务，不擅自扩大范围。

## 工作方式
接到提问或任务时，先弄清要交付什么，再选工具或子代理执行。
**可直接文字作答的**仅限：今天日期/星期（见「当前会话」）、纯概念解释、用户已在本轮给出的信息。
**其余**（实时事实、本机状态、vault 内容、需运行验证的任务）→ 先 read_file 匹配 skill、或 quick_search / execute / task(researcher)，再总结。
多步任务：先用 write_todos 分解，再逐项执行；每步核对结果，失败先诊断根因再修正重试，不卡死也不跳步。

**环境与可核实事实：**
- 本提示词「当前会话」仅提供今天日期与星期；精确时间/本机信息用 execute。
- 不要读 `javis.json` 或 `/memories/user-profile.md` 推断用户状况。
- Skills：启动时已 discovery 各 SKILL.md 的 name/description；相关时用 read_file 读完整 SKILL.md 再行动。

## 完成标准
- **事实**：有可靠来源再答；没有则说明不确定，不编造。
- **调研**：需要联网或检索 vault 时用 quick_search 或 task(researcher)；覆盖用户原问题即可，不自动升级成报告或写入 vault。
- **落盘**：仅当用户明确要求保存、沉淀或整理报告时，才写 `/vault/Inbox/` 或 `/vault/Reports/`。
- **可验证任务**：能跑则跑（测试、命令输出），声称完成前附上验证输出；无法验证时说明建议的检查步骤，不谎称已完成。

## 约束
- 文件路径只用 `/workspace/`（项目）、`/vault/`（Obsidian）、`/memories/`（用户记忆）、`/skills/`（用户全局 skill）、`/builtin-skills/`（随安装包 skill）。
- 值得长期保留或用户要求记住 → task(knowledge_keeper, …)。
- 委派时传递用户原意，不扩写成「全面调研 / 行业动态报告」。
- 多角度并行**研究**可用 CodeInterpreter + `task()` fan-out 多个 researcher，再合并。

## 输出
简体中文，简洁有结构。引用本地知识时用 `/vault/` 路径。
"""


def session_date_line(*, now: datetime | None = None) -> str:
    """启动时会话日期行（仅日期+星期，不含时分秒）。"""
    current = now or datetime.now()
    return (
        f"今天是 {current.strftime('%Y-%m-%d')} {_WEEKDAYS[current.weekday()]}。"
        "（用户问今天日期/星期几时，可直接用本行作答。）"
    )


def build_environment_block(config: Config) -> str:
    """轻量运行环境（对标 OpenCode environment；不含用户所在地，ADR-0003）。"""
    platform = sys.platform
    mcp_n = len((config.mcps or {}).get("servers") or {}) if isinstance(config.mcps, dict) else 0
    vault_line = (
        f"- 知识库 /vault/: {config.vault_path}"
        if config.vault_path is not None
        else "- 知识库: 未配置（本次会话没有 /vault/，忽略一切知识库检索与沉淀任务）"
    )
    return "\n".join(
        [
            "## 运行环境",
            f"- 平台: {platform}",
            f"- 项目根 /workspace/: {config.project_root}",
            vault_line,
            f"- 记忆 /memories/: {config.memory_dir}",
            "- 主代理工具: quick_search, execute, read/grep/glob/ls, task, write_todos"
            + (f", MCP×{mcp_n}" if mcp_n else ""),
            "- 子代理: researcher（联网+vault）, knowledge_keeper（Inbox 沉淀）",
            "- Skills: deepagents 已 discovery frontmatter；相关任务 read_file 对应 SKILL.md",
        ]
    )


def build_main_prompt(*, config: Config | None = None, now: datetime | None = None) -> str:
    """主系统提示词：会话日期 + 可选环境块 + 正文。"""
    date_line = session_date_line(now=now)
    parts = [f"## 当前会话\n{date_line}"]
    if config is not None:
        parts.append(build_environment_block(config))
    parts.append(MAIN_SYSTEM_PROMPT)
    return "\n\n".join(parts)


def _harness_suffix_for_model(model_id: str) -> str:
    mid = (model_id or "").lower()
    if "muse" in mid:
        return JARVIS_HARNESS_SUFFIX + MUSE_HARNESS_EXTRA
    return JARVIS_HARNESS_SUFFIX


def _register_jarvis_harness(model_id: str) -> None:
    """为当前模型注册 HarnessProfile（deepagents 标准扩展点，非场景 middleware）。"""
    register_harness_profile(
        model_id,
        HarnessProfile(
            system_prompt_suffix=_harness_suffix_for_model(model_id),
            tool_description_overrides=dict(TOOL_DESCRIPTION_OVERRIDES),
        ),
    )
    _HARNESS_REGISTERED.add(model_id)


def harness_profile_loaded(model_id: str) -> bool:
    return model_id in _HARNESS_REGISTERED


def _make_model(config: Config) -> BaseChatModel:
    return ChatOpenAI(
        base_url=config.base_url,
        api_key=SecretStr(config.api_key),
        model=config.model_id,
        temperature=0,
        # HTTP 层瞬断自愈（流中断后的业务级重试在 src/resilience.py 决策表）。
        max_retries=3,
        timeout=120,
    )


def _make_backend(config: Config) -> CompositeBackend:
    workspace = LocalShellBackend(root_dir=str(config.project_root), virtual_mode=True)
    routes: dict[str, FilesystemBackend | LocalShellBackend] = {
        "/workspace/": workspace,
        "/memories/": FilesystemBackend(root_dir=str(config.memory_dir), virtual_mode=True),
    }
    if config.vault_path is not None:
        routes["/vault/"] = FilesystemBackend(
            root_dir=str(config.vault_path), virtual_mode=True
        )
    for vpath, fs_path in skill_backend_routes(config).items():
        routes[vpath] = FilesystemBackend(root_dir=str(fs_path), virtual_mode=True)
    return CompositeBackend(default=workspace, routes=routes)


def harness_capabilities(config: Config) -> dict[str, bool]:
    """Codex harness 能力探测（/doctor 等只读诊断用）。"""
    from deepagents.middleware.filesystem import supports_execution

    return {
        "execute": supports_execution(_make_backend(config)),
        "write_todos": True,
        "tavily": bool(str(config.tavily_key or "").strip()),
    }


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
    wiki_tools = make_wiki_tools(config.vault_path) if config.vault_path is not None else []
    rag_tool = None
    if config.vault_path is not None:
        rag_tool = make_semantic_search_tool(
            config.vault_path,
            config.memory_dir / "rag-index",
            base_url=config.rag_ollama_base_url,
            embed_model=config.rag_embed_model,
        )
    if permission_state is not None:
        interrupt_on = build_permission_interrupts_from_state(permission_state)
    else:
        interrupt_on, permission_state = build_permission_interrupts(
            config.permissions,
            hooks=config.hooks,
            project_root=config.project_root,
        )
    deny_middleware = build_permission_deny_middleware(permission_state)
    deprecated_guard = DeprecatedPathMiddleware()
    from src.system_context_enforcer import SystemContextEnforcerMiddleware

    system_context_enforcer = SystemContextEnforcerMiddleware()
    vault_guard = VaultWriteGuardMiddleware()
    root = config.project_root
    inbox_snapshot = (
        InboxSnapshotMiddleware(root, config.vault_path)
        if config.vault_path is not None
        else None
    )
    _register_jarvis_harness(config.model_id)
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
    main_tools: list = [make_quick_search_tool(config.tavily_key)]
    if mcp_tools:
        main_tools.extend(mcp_tools)

    middleware = [
        CodeInterpreterMiddleware(subagents=True),
        TodoListMiddleware(),
        deny_middleware,
        deprecated_guard,
        system_context_enforcer,
        vault_guard,
    ]
    # 执行韧性（对标 codex/opencode harness，见 .scratch/javis-execution-resilience/）
    from src.resilience import DoomLoopMiddleware, StepBudgetMiddleware

    middleware.append(StepBudgetMiddleware(config.execution_max_steps))
    middleware.append(DoomLoopMiddleware())
    if inbox_snapshot is not None:
        middleware.append(inbox_snapshot)

    return create_deep_agent(
        model=model,
        backend=_make_backend(config),
        subagents=[researcher, knowledge_keeper, *config_subagents],  # type: ignore[list-item]
        system_prompt=build_main_prompt(config=config),
        tools=main_tools,
        middleware=middleware,  # type: ignore[list-item]
        memory=memory,
        skills=skills,
        interrupt_on=interrupt_on,  # HITL 审批（javis.json permissions）
        checkpointer=checkpointer,
        store=store,
        name="javis",
    )
