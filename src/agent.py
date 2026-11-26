"""主代理组装。

model + CompositeBackend（default=InheritedEnvShellBackend 无限制；/workspace(虚拟) /vault /memories /skills /shared-skills 路由）
+ subagents + memory + checkpointer(SqliteSaver) + store。见设计文档 §5.2/§6。
"""
import logging
import sys
from datetime import datetime
from pathlib import Path

from deepagents import HarnessProfile, create_deep_agent, register_harness_profile
from deepagents.backends import (
    CompositeBackend,
    FilesystemBackend,
    LocalShellBackend,
)
from langchain.agents.middleware import TodoListMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from pydantic import SecretStr

try:
    from langchain_quickjs import CodeInterpreterMiddleware
except ImportError:  # 便携版剥离 JS 代码解释器（Nuitka 主动排除时 stub 抛 ImportError，非 ModuleNotFoundError）
    CodeInterpreterMiddleware = None

from src.config import Config, load_config
from src.config_agents import build_config_subagents
from src.deprecated_paths import DeprecatedPathMiddleware
from src.inbox_snapshot_middleware import InboxSnapshotMiddleware
from src.media_guard import MediaGuardMiddleware
from src.permissions import (
    GATED_TOOLS,
    SideTaskGuardMiddleware,
    build_permission_deny_middleware,
    build_permission_interrupts,
    build_permission_interrupts_extended,
    build_permission_interrupts_from_state,
    merge_permissions_deny_wins,
)
from src.rag import make_semantic_search_tool
from src.skill_discovery import manual_only_skill_names
from src.skill_paths import skill_backend_routes, skill_virtual_sources
from src.subagents import build_knowledge_keeper, build_researcher
from src.tools import make_deep_search_tool, make_quick_search_tool, make_search_tool
from src.vault_guard import VaultWriteGuardMiddleware
from src.wiki import make_wiki_tools

_WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")

_HARNESS_REGISTERED: set[str] = set()

# deepagents HarnessProfile：对抗性推理约束（对标 opencode beast.txt——
# 逐条打击模型已知弱点，不是语气加强；见 .scratch 教程笔记 0002 课）
JARVIS_HARNESS_SUFFIX = """\
## Harness（执行纪律，逐条强制）
- 先弄清本轮交付物；≥3 步的任务先用 write_todos 分解（每项带可核对的完成标准），执行中随进度更新状态。
- 当你说「接下来我会运行/创建/检查 X」时，必须真的调用工具完成 X，再进入下一句——只说不做等于没做。
- **报错原文里写着根因**：工具失败后，先引用报错原文的关键行，再决定动作。路径被空格劈断、文件不存在、权限拒绝、语法错误，各有不同解法。没读报错就重试 = 瞎撞。
- **同一方案失败 2 次 = 方案错误**。第 3 次必须换**方法类别**（换工具 / 换路径形态 / 换入口 / 换数据源）——只微调参数、引号、斜杠方向不算换方案。
- **路径约定**：文件工具（ls/read/write/edit/glob/grep）接受任意磁盘路径——绝对路径直接用，相对路径以项目根为基准；/workspace/（=项目根）、/vault/、/memories/、/skills/、/shared-skills/（共享 agent skills，只读挂载）等前缀仍是快捷方式（自动映射对应目录）。写操作走审批。execute 的 shell 工作目录就是项目根本身——shell 命令里用真实/相对路径，**禁止**带 /workspace/ 等虚拟前缀（shell 不认识，cmd 会把它当开关静默忽略）。
- 可验证的事实：先工具、后结论。不凭训练记忆硬答，不在能自行获取时先反问用户，不问「是否需要我查询」——直接查。
- **认识论纪律**：凡答案依赖本机/实时状态（时间、位置、版本、文件状态），唯一合法来源是 execute/工具实测。工具成功但结果不可用 → 换查询词/升档/换数据源/换工具类别；「我没拿到」不等于「不存在」。报告失败必须引用实际报错原文；无证据的归因 = 编造。
- **唯一停下条件**：同一目标已用 ≥3 种**不同方法类别**尝试仍失败——向用户报告「已尝试清单 + 报错原文 + 卡点 + 建议」。被 harness 熔断的工具调用不许再发
- 搜索停滞铁律：逐词追加同一查询没有新信息（「换本词之组」）。相似查询 约 3 次后必须换方法类别（换工具 / 换数据源 / 直接用已获取的信息作答 / 向用户报告卡点）；harness 会拦截第 6 次近似调用。
- **无进展铁律**：同一工具的结果连续未带来新信息（空白 / 与前次相同 / 截断空输出）至多 3 次，第 4 次必须换方法类别，或直接用已有信息作答；微调参数 ≠ 换方法；harness 第 3 次连发会提醒、第 5 次拦截。
- **Windows 多行禁令**：本机 shell 是 cmd，只支持单行命令——多行命令会被静默截断（症状「exit 0 但无输出」，成功但没输出其实是失败）；多行脚本先 write_file 落盘（如 tmp_read_docx.py），再单行 execute：python tmp_read_docx.py；python -c 只许单行；多个操作用 && 单行链接。
- 完成声明必须附验证证据（测试/命令输出原文）；无法验证时明确说明未验证，不谎称已完成。
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
        "Do not use CodeInterpreter/eval for environment reads. "
        "On Windows the shell is cmd: single-line commands only — multi-line commands are silently truncated (exit 0 but no output means failure, not success); for multi-line scripts write the .py file first via write_file, then run `python <file>`; `python -c` must stay on one line; chain operations with && on one line."
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
- 文件路径：任意磁盘路径均可（绝对路径直接用；相对路径以项目根为基准）；`/workspace/`（项目）、`/vault/`（Obsidian）、`/memories/`（用户记忆）、`/skills/`（用户全局 skill）、`/shared-skills/`（共享 agent skill，只读挂载）前缀仍可用作快捷方式。
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
    """主系统提示词：会话日期 + 可选环境块 + 正文 + 可选项目指令（AGENTS.md）。"""
    date_line = session_date_line(now=now)
    parts = [f"## 当前会话\n{date_line}"]
    if config is not None:
        parts.append(build_environment_block(config))
    parts.append(MAIN_SYSTEM_PROMPT)
    if config is not None:
        from src.project_paths import load_project_instructions

        instructions = load_project_instructions(config.project_root)
        if instructions:
            parts.append(f"## 项目指令（AGENTS.md，优先级高于你的默认习惯）\n{instructions}")
    return "\n\n".join(parts)


def _harness_suffix_for_model(model_id: str) -> str:
    mid = (model_id or "").lower()
    if "muse" in mid:
        return JARVIS_HARNESS_SUFFIX + MUSE_HARNESS_EXTRA
    return JARVIS_HARNESS_SUFFIX


def _register_jarvis_harness(model_id: str) -> None:
    """为当前模型注册 HarnessProfile（deepagents 标准扩展点，非场景 middleware）。

    deepagents 对预构建模型实例按 `provider:model` 键查表（如 openai:mimo-v2.5），
    对 spec 字符串按原文查表——两个键都要注册，否则 suffix/工具描述覆盖静默失效。
    """
    profile = HarnessProfile(
        system_prompt_suffix=_harness_suffix_for_model(model_id),
        tool_description_overrides=dict(TOOL_DESCRIPTION_OVERRIDES),
    )
    for key in (model_id, f"openai:{model_id}"):
        if key in _HARNESS_REGISTERED:
            continue
        register_harness_profile(key, profile)
        _HARNESS_REGISTERED.add(key)


def harness_profile_loaded(model_id: str) -> bool:
    return model_id in _HARNESS_REGISTERED or f"openai:{model_id}" in _HARNESS_REGISTERED


def _make_model(config: Config, model_id: str | None = None) -> BaseChatModel:
    # dotdir: context_limit > 0 时挂 profile.max_input_tokens，deepagents 压缩中间件
    # 按 0.85/0.10 比例推导压缩时机，不再依赖超模型上限的固定默认值。
    _ctx = int(getattr(config, "context_limit", 0) or 0)
    return ChatOpenAI(
        base_url=config.base_url,
        api_key=SecretStr(config.api_key),
        model=model_id or config.model_id,
        temperature=0,
        # HTTP 层瞬断自愈（流中断后的业务级重试在 src/resilience.py 决策表）。
        max_retries=3,
        timeout=120,
        **({"profile": {"max_input_tokens": _ctx}} if _ctx > 0 else {}),
    )


def _make_backend(config: Config, extra_skill_routes=None) -> CompositeBackend:
    from src.path_policy import apply_unrestricted_paths
    from src.shell_backend import InheritedEnvShellBackend

    # #10: 解锁 deepagents middleware 对 Windows 盘符路径的工具层拦截
    # （backend virtual_mode=False 只解决 root 锚定；跨盘符靠此适配放行）。
    apply_unrestricted_paths()

    routes: dict[str, FilesystemBackend | LocalShellBackend] = {
        "/memories/": FilesystemBackend(root_dir=str(config.memory_dir), virtual_mode=True),
        # .jarvis/ 项目状态目录（checkpoints/conversation_history 外置等，virtual_mode=True 锚定项目根）
        "/.jarvis/": FilesystemBackend(
            root_dir=str(config.project_root / ".jarvis"), virtual_mode=True
        ),
    }
    if config.vault_path is not None:
        routes["/vault/"] = FilesystemBackend(
            root_dir=str(config.vault_path), virtual_mode=True
        )
    for vpath, fs_path in skill_backend_routes(config).items():
        routes[vpath] = FilesystemBackend(root_dir=str(fs_path), virtual_mode=True)
    # ticket 02: profile skill routes (ticket 03 fills spec.skill_routes).
    for vpath, fs_path in (extra_skill_routes or ()):
        routes.setdefault(vpath, FilesystemBackend(root_dir=str(fs_path), virtual_mode=True))
    # #04: 虚拟前缀 → 真实目录映射（shell 守卫报错指路 + @ 引用锚点行/双路径补全）。
    prefix_map: dict[str, str] = {"/memories/": str(config.memory_dir)}
    if config.vault_path is not None:
        prefix_map["/vault/"] = str(config.vault_path)
    for vpath, fs_path in skill_backend_routes(config).items():
        prefix_map.setdefault(vpath, str(fs_path))
    for vpath, fs_path in (extra_skill_routes or ()):
        prefix_map.setdefault(vpath, str(fs_path))
    prefix_map.setdefault("/workspace/", str(config.project_root))
    prefix_map.setdefault("/.jarvis/", str(config.project_root / ".jarvis"))
    # 虚拟前缀守卫：execute 收到这些前缀时执行前拦截（shell 不认识虚拟路径）。
    # virtual_mode=False（#10）：文件工具接受任意磁盘路径——绝对路径按原样解析、
    # 相对路径以项目根为基准；虚拟前缀路由仍优先匹配，降级为快捷方式。
    # 安全边界 = HITL permissions（write/edit/delete 默认 ask）+ vault 写保护，
    # 不靠 backend 锁死路径（deepagents 官方 unrestricted 语义，对标 opencode
    # external_directory 权限模型）。
    workspace = InheritedEnvShellBackend(
        root_dir=str(config.project_root),
        virtual_mode=False,
        virtual_prefixes=("/workspace/", *routes.keys()),
        prefix_map=prefix_map,
    )
    # tui-ux4-hotfix #04: /workspace/ 路由专用虚拟模式 FilesystemBackend——
    # 共享 InheritedEnvShellBackend(virtual_mode=False) 时 ls/glob 上报真实磁盘绝对路径，
    # CompositeBackend 重拼前缀产出 /workspaceD:\... 破坏路径，模型 read_file 失败（@ 引用卡点）。
    # 虚拟模式下条目上报 /<相对路径> 再被干净重拼为 /workspace/...。
    # default 仍是 InheritedEnvShellBackend（#10 路径放开 + execute 守卫不变）。
    routes["/workspace/"] = FilesystemBackend(
        root_dir=str(config.project_root),
        virtual_mode=True,
    )
    # 压缩外置落点：deepagents SummarizationMiddleware 经 artifacts_root 推 .jarvis/conversation_history/
    return CompositeBackend(default=workspace, routes=routes, artifacts_root="/.jarvis/")


def harness_capabilities(config: Config) -> dict[str, bool]:
    """Codex harness 能力探测（/doctor 等只读诊断用）。"""
    from deepagents.middleware.filesystem import supports_execution

    return {
        "execute": supports_execution(_make_backend(config)),
        "write_todos": True,
        "tavily": bool(str(config.tavily_key or "").strip()),
    }


def build_agent(  # noqa: C901
    config: Config,
    model: BaseChatModel | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    store: BaseStore | None = None,
    permission_state: dict | None = None,
    mcp_tools: list | None = None,
    jump_in_registry=None,
    profile_spec=None,
):
    """组装主代理。

    未传 model 时用 config 构造真实模型；checkpointer 默认 InMemorySaver
    （生产用 SqliteSaver，由调用方在 with 块内传入）。
    permission_state 由外部传入（如 main.py）时复用同一引用，保证
    always approve 等运行时修改与 deny middleware / when 谓词联动。
    mcp_tools 为 MCP server 加载出的额外工具（仅主代理），由调用方
    （如 main.py 经 src.mcps.load_mcp_tools）在启动时一次性注入。
    jump_in_registry 为插队消息缓存（src.jump_in_queue.JumpInRegistry）：非 None 时
    主代理挂 MessageQueueJumpInMiddleware（before_model drain 当前 thread 缓存注入），
    子代理不挂（无队列概念）；CLI 传恒空 registry 时零开销安全。
    """
    if profile_spec is not None:
        model = model or _make_model(config, model_id=profile_spec.model_id)
    else:
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
    elif profile_spec is not None:
        # ticket 02: merge profile rules on top of config permissions;
        # setdefault keeps config rules winning for already-configured
        # deny tools (deny-wins refinement lands in ticket 05).
        # ticket 05: profile rules may only tighten config permissions
        # (deny-wins), and profile-scoped tools become gated as well
        # (fail-closed ask).
        base_permissions = merge_permissions_deny_wins(
            config.permissions,
            profile_spec.permission_extra_rules,
            profile_spec.tool_deny,
        )
        _extra = tuple(
            _k for _k in base_permissions if _k not in GATED_TOOLS and _k not in ("*", "heuristics")
        )
        interrupt_on, permission_state = build_permission_interrupts_extended(
            base_permissions,
            extra_tools=_extra,
            hooks=config.hooks,
            project_root=config.project_root,
        )
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
    vault_guard = VaultWriteGuardMiddleware(vault_path=config.vault_path)
    root = config.project_root
    inbox_snapshot = (
        InboxSnapshotMiddleware(root, config.vault_path)
        if config.vault_path is not None
        else None
    )
    _register_jarvis_harness(config.model_id)
    if profile_spec is not None and profile_spec.model_id != config.model_id:
        _register_jarvis_harness(profile_spec.model_id)
    # 媒体守卫：文本-only 模型下 deepagents 把二进制文件的 base64 媒体块塞进
    # ToolMessage，网关回传即 400「Unsupported content part」（整轮死亡）。
    # auto/off 自动降级为占位文本继续运行；model_image_input="on"（真多模态）不挂载。
    media_guard = None if config.model_image_input == "on" else MediaGuardMiddleware()
    researcher = build_researcher(
        search_tools=search_tools, wiki_tools=wiki_tools, rag_tool=rag_tool,
        deny_middleware=deny_middleware, media_guard=media_guard,
    )
    knowledge_keeper = build_knowledge_keeper(
        deny_middleware=deny_middleware,
        project_root=root,
        vault_path=config.vault_path,
        media_guard=media_guard,
    )
    config_subagents = build_config_subagents(
        config.agents,
        default_deny_middleware=deny_middleware,
        media_guard=media_guard,
    )

    memory_files = [
        str(f).replace("\\", "/")
        for f in sorted(config.memory_dir.glob("*.md"))
        if f.name.lower() != "readme.md"
    ]
    # tui-ux15: 梦境知识库（memory/dream/knowledge.md，顶层 glob 非递归）存在时显式补注入
    _dream_knowledge = config.memory_dir / "dream" / "knowledge.md"
    if _dream_knowledge.exists():
        memory_files.append(str(_dream_knowledge).replace("\\", "/"))
    # ticket 02: profile memory directories (global agent memory, task/
    # project namespaces); missing directories are skipped, *.md files
    # stay user-editable under the JARVIS home.
    if profile_spec is not None:
        for _mem_dir in profile_spec.memory_dirs:
            _mem_path = Path(_mem_dir)
            if _mem_path.is_dir():
                memory_files.extend(
                    str(f).replace("\\", "/")
                    for f in sorted(_mem_path.glob("*.md"))
                    if f.name.lower() != "readme.md"
                )
    memory = memory_files

    # #08 Plan/Act 模式闸门（与 deny_middleware 共享同一 permission_state 引用）
    from src.plan_mode import PlanModeMiddleware

    backend = _make_backend(config, extra_skill_routes=profile_spec.skill_routes if profile_spec is not None else None)  # #08: 构造一次，模型 backend 与 skills middleware 共享
    skills = list(
        dict.fromkeys(
            skill_virtual_sources(config)
            + (list(profile_spec.skill_vpaths) if profile_spec is not None else [])
        )
    )
    main_tools: list = [make_quick_search_tool(config.tavily_key)]
    if mcp_tools:
        main_tools.extend(mcp_tools)
    # /goal model-side tools x3 (create_goal/complete_goal/get_goal), same injection site as MCP (one-time at startup, main agent only);
    # thread_id read from the shared permission_state reference at call time (streaming writes it at each turn start)
    from src.goal_tools import build_goal_tools
    main_tools.extend(build_goal_tools(permission_state, default_max_turns=config.goals_max_turns))
    # ticket 02: profile tool allow/deny filter on the main agent's
    # extra tools; an empty allow-list means unrestricted, deny always removes.
    if profile_spec is not None:
        _tool_allow = profile_spec.tool_allow
        _tool_deny = set(profile_spec.tool_deny)
        main_tools = [
            t
            for t in main_tools
            if (not _tool_allow or getattr(t, "name", "") in _tool_allow)
            and getattr(t, "name", "") not in _tool_deny
        ]

    # 执行韧性（对标 codex/opencode harness，见 .scratch/javis-execution-resilience/）
    from src.resilience import (
        DoomLoopMiddleware,
        NoProgressGuardMiddleware,
        StagnationGuardMiddleware,
        StepBudgetMiddleware,
        ToolErrorBoundaryMiddleware,
    )

    # 异常兜底放最外层：任何工具/内层中间件的异常都转成错误数据，不炸穿整轮。
    # 400 自愈：每次模型调用前清洗历史里的畸形工具调用（invalid_tool_calls）及其引用
    # ToolMessage（见 src/sanitize_history.py，拼在 core 中间件之后运行）
    from src.sanitize_history import SanitizeHistoryMiddleware

    middleware: list = [ToolErrorBoundaryMiddleware()]
    middleware.extend(
        [
            SanitizeHistoryMiddleware(),
            *([CodeInterpreterMiddleware(subagents=True)] if CodeInterpreterMiddleware is not None else []),
            TodoListMiddleware(),
            deny_middleware,
            PlanModeMiddleware(permission_state),
            SideTaskGuardMiddleware(permission_state),
            deprecated_guard,
            system_context_enforcer,
            vault_guard,
        ]
    )
    if media_guard is not None:
        middleware.append(media_guard)
    # ticket 05: profile workspace_only confines file tools to the profile workspace
    if profile_spec is not None and profile_spec.workspace_only:
        from src.file_guard import WorkspaceFileGuardMiddleware

        middleware.append(WorkspaceFileGuardMiddleware(Path(profile_spec.workspace), block_read=True))
    # dotdir: 上下文压缩改走 deepagents 自带 summarizer（被裁历史外置 .jarvis/conversation_history/ + ContextOverflowError 自愈）
    # keep-first：压缩时开头 keep_first_messages（默认 0）条消息逐字钉进 summary，
    # 中间段走 LLM 总结（src/context_compaction.py；0 = 纯上游行为）
    _auto_compaction = int(getattr(config, "auto_compaction", 0) or 0)
    _kf_raw = getattr(config, "keep_first_messages", 0)
    try:
        _keep_first = max(0, int(_kf_raw))
    except (TypeError, ValueError):
        _keep_first = 0
    try:
        from src.context_compaction import build_compaction_middleware

        middleware.insert(
            2,
            build_compaction_middleware(
                model,
                backend,
                keep_first=_keep_first,
                auto_compaction=_auto_compaction,
            ),
        )
    except Exception as exc:  # noqa: BLE001 环境不可用时跳过压缩，不影响启动
        logging.warning("上下文压缩中间件不可用，跳过: %s", exc)
    middleware.append(StepBudgetMiddleware(config.execution_max_steps))
    # 停滞防復（近似成功循环：3 次软引导 / 6 次硬熔断），放在 DoomLoop 之外（DoomLoop 仍最内层）；实例有状态，不共享。
    middleware.append(StagnationGuardMiddleware())
    # 无进展守卫（结果级：连续 3 次无新信息 -> 软引导 / 第 5 次硬熔断），实例有状态，不共享。
    middleware.append(NoProgressGuardMiddleware())
    middleware.append(DoomLoopMiddleware())
    # #08: manual-only skill（disable-model-invocation）不进模型上下文；仅主代理挂 skills 中间件
    from src.jarvis_skills import JarvisSkillsMiddleware

    _flagged = manual_only_skill_names(config)
    # ticket 03: profile tier roots (agent/project/task) may ship manual-only
    # skills too; scan their SKILL.md frontmatter and keep them out of the
    # model context as well (legacy user/project roots already covered above).
    if profile_spec is not None and profile_spec.skill_routes:
        from src.profile_skills import scan_manual_only

        _flagged = _flagged | scan_manual_only([fs for _vp, fs in profile_spec.skill_routes])
    middleware.append(
        JarvisSkillsMiddleware(
            backend=backend,
            sources=skills,
            flagged=_flagged,
        )
    )
    if inbox_snapshot is not None:
        middleware.append(inbox_snapshot)
    # tui-ux14 #04: 插队消息缓存——before_model 整批注入当前 thread 的排队消息（仅主代理）
    if jump_in_registry is not None:
        from src.jump_in_queue import MessageQueueJumpInMiddleware

        middleware.append(MessageQueueJumpInMiddleware(jump_in_registry, permission_state))
    # 400 自愈（双 System 硬规则，殿后最内层）：历史里散落的 SystemMessage
    #（side 边界 / compact 摘要）在模型调用时合并进唯一 system 头，不写历史
    from src.system_head import SystemHeadMiddleware

    middleware.append(SystemHeadMiddleware())


    system_prompt = build_main_prompt(config=config)
    if profile_spec is not None:
        from src.profiles.spec import PROFILE_CONFLICT_NOTE

        system_prompt = (
            system_prompt + "\n" + profile_spec.prompt_suffix + "\n" + PROFILE_CONFLICT_NOTE
        )
    compiled = create_deep_agent(
        model=model,
        backend=backend,
        subagents=[researcher, knowledge_keeper, *config_subagents],  # type: ignore[list-item]
        system_prompt=system_prompt,
        tools=main_tools,
        middleware=middleware,  # type: ignore[list-item]
        memory=memory,
        interrupt_on=interrupt_on,  # HITL 审批（javis.json permissions）
        checkpointer=checkpointer,
        store=store,
        name="javis",
    )
    # 步数上限强制交接（streaming.force_handoff）复用同一模型实例；
    # 不进 graph 状态，不污染历史。
    setattr(compiled, "_jarvis_model", model)
    setattr(compiled, "_jarvis_profile_snapshot", profile_spec.snapshot if profile_spec is not None else None)
    setattr(compiled, "_jarvis_middlewares", middleware)
    return compiled

def create_jarvis(
    workspace: str | Path,
    checkpointer: BaseCheckpointSaver | None = None,
    *,
    model: BaseChatModel | None = None,
    store: BaseStore | None = None,
    env_overrides: dict[str, str] | None = None,
    permission_state: dict | None = None,
    mcp_tools: list | None = None,
    profile_id: str | None = None,
    task_id: str | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
):
    """ADR-0012 headless public entry point: build the Jarvis main agent rooted at an explicit workspace.

    Contract (docs/adr/0012-headless-adapter-contract.md):
    - The workspace argument is the only directory parameter: the file backend and shell tool are
      rooted at this directory. The engine never does os.chdir / cwd discovery, so multiple
      concurrent sessions do not interfere with each other.
    - The checkpointer is injected by the caller (embedder, e.g. Local Dots, passes
      SqliteSaver("data/checkpoints.db")); task_id as thread_id; the caller owns the lifecycle
      and there is no module-level singleton checkpointer inside Jarvis.
    - Headless: no TUI (textual) imports; importable from the jarvis package public entry point
      without affecting the interactive path.
    - Required configuration keys (BASE_URL/API_KEY/MODEL_ID/TAVILY_KEY) come from
      env_overrides, or from the workspace's .env / the global ~/.jarvis fallback.
    """
    root = Path(workspace)
    if not root.is_dir():
        raise FileNotFoundError(f"workspace does not exist or is not a directory: {workspace}")
    config = load_config(project_root=root, env_overrides=env_overrides)
    if profile_id is None:
        return build_agent(
            config,
            model=model,
            checkpointer=checkpointer,
            store=store,
            permission_state=permission_state,
            mcp_tools=mcp_tools,
        )
    # ticket 02: profile path. Registry + bake imports stay inside this
    # branch so the default path keeps zero behavior difference.
    # ticket 07: ops observability (the legacy path above emits nothing).
    from src.profiles.observability import ops_event
    from src.profiles.registry import ProfileRegistry
    from src.profiles.schema import ProfileError
    from src.profiles.spec import bake_spec

    registry = ProfileRegistry(workspace=root, jarvis_json_agents=config.agents)
    try:
        loaded = registry.load(profile_id)
    except ProfileError as exc:
        ops_event("profile_validation_failed", profile_id=profile_id, error=str(exc)[:500])
        raise
    spec = bake_spec(
        config,
        loaded.profile,
        str(root),
        task_id=task_id,
        project_id=project_id,
        session_id=session_id,
        agents_md_text=loaded.agents_md_text,
    )
    ops_event(
        "profile_loaded",
        profile_id=spec.profile_id,
        profile_version=spec.profile_version,
        profile_hash=spec.profile_hash,
    )
    ops_event(
        "tools_resolved",
        profile_id=spec.profile_id,
        tool_allow_count=len(spec.tool_allow),
        tool_deny_count=len(spec.tool_deny),
    )
    return build_agent(
        config,
        model=model,
        checkpointer=checkpointer,
        store=store,
        permission_state=permission_state,
        mcp_tools=mcp_tools,
        profile_spec=spec,
    )
