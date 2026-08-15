# 02 — deepagents 语法核对发现

`Type: research` `Status: done`

> 依据：docs-langchain MCP（`/oss/python/deepagents/*` 官方文档）+ PyPI 元数据（deepagents 0.7.6）+ reference-langchain API 索引。日期：2026-08-15。

## 版本确认

- **PyPI 最新版：`deepagents 0.7.6`**（设计文档 §2.1 写的是 v0.7.5，需更新）。
- 当前环境已装：**deepagents 0.6.11**（旧），`langchain 1.3.10`、`langchain-core 1.4.8`、`langchain-quickjs 0.3.0`。
- **结论：现有依赖不满足 0.7.6，升级清单见 §6。**

---

## 1. `create_deep_agent` 完整签名（0.7.6）

来源：`/oss/python/deepagents/customization.mdx`「Full function signature」。设计文档 §2.1 列出的参数**全部存在**，另有新增参数：

```python
from deepagents import create_deep_agent

agent = create_deep_agent(
    model: str | BaseChatModel | None = None,          # 可传模型字符串或 ChatOpenAI 实例
    tools: Sequence[BaseTool | Callable | dict] | None = None,
    *,
    system_prompt: str | SystemMessage | None = None,
    middleware: Sequence[AgentMiddleware] = (),
    subagents: Sequence[SubAgent | CompiledSubAgent | AsyncSubAgent] | None = None,
    skills: list[str] | None = None,                   # 渐进式披露，按需加载
    memory: list[str] | None = None,                   # AGENTS.md 风格文件，启动即注入
    permissions: list[FilesystemPermission] | None = None,
    backend: BackendProtocol | None = None,            # 默认 StateBackend()
    interrupt_on: dict[str, bool | InterruptOnConfig] | None = None,
    response_format: ResponseFormat | type | dict | None = None,   # 新增
    state_schema: type[DeepAgentState] | None = None,              # 新增
    context_schema: type[ContextT] | None = None,                 # 新增（每轮运行时上下文）
    checkpointer: Checkpointer | None = None,          # 短期记忆 + HITL 必需
    store: BaseStore | None = None,                    # StoreBackend 必需
    debug: bool = False,
    name: str | None = None,
    cache: BaseCache | None = None,
) -> CompiledStateGraph
```

关键点：
- `model` 支持 `BaseChatModel` 实例 → 本项目可用 `ChatOpenAI(base_url=..., api_key=..., model=...)` 直接传入（OpenAI 兼容端点可行）。
- `interrupt_on` 需要 `checkpointer`（HITL 前置条件）。
- 内置中间件栈：`SkillsMiddleware`(仅 skills) → `FilesystemMiddleware` → `SubAgentMiddleware` → `SummarizationMiddleware` → `PatchToolCallsMiddleware` → `AsyncSubAgentMiddleware`(仅 async) → 用户 middleware → 提示缓存 → `MemoryMiddleware`(仅 memory)。
- 设计文档 §2.1 提到的「中间件 retry / tool_error / model_fallback / call_limit / summarization / human-in-the-loop」来自 **langchain 预置中间件**（`langchain.agents.middleware`），非 deepagents 内置，需显式传入 `middleware=[...]`。

---

## 2. 后端构造（0.7.6）

来源：`/oss/python/deepagents/backends.mdx`。全部命名与设计文档一致。

### FilesystemBackend

```python
from deepagents.backends import FilesystemBackend

agent = create_deep_agent(
    model="...",
    backend=FilesystemBackend(root_dir=".", virtual_mode=True),
)
```
- `root_dir` **必须是绝对路径**。
- `virtual_mode=True` 启用路径沙箱（拦截 `..`、`~`、root 外的绝对路径）；`virtual_mode=False`（默认）即使设了 root_dir 也**无任何路径限制**。
- 官方建议：单独用 FilesystemBackend 时，agent 内部数据（`/large_tool_results/`、`/conversation_history/`）会写进真实磁盘 → **推荐外包一层 CompositeBackend**。

### CompositeBackend（路由）

```python
from deepagents.backends import CompositeBackend, StateBackend, FilesystemBackend, StoreBackend
from langgraph.store.memory import InMemoryStore

agent = create_deep_agent(
    backend=CompositeBackend(
        default=StateBackend(),                          # 内部数据走临时 state，不落盘
        routes={
            "/workspace/": FilesystemBackend(root_dir="/abs/project", virtual_mode=True),
            "/memories/": StoreBackend(namespace=lambda _rt: ("memories",)),
        },
    ),
    store=InMemoryStore(),   # store 传给 create_deep_agent，不传给 backend
)
```
- 路由按**最长前缀优先**；`ls/glob/grep` 聚合结果并保留原始路径前缀。
- `/memories/` 路由到 StoreBackend = 长期记忆跨线程持久化（设计文档 §6 目标一致）。

### LocalShellBackend

```python
from deepagents.backends import LocalShellBackend

agent = create_deep_agent(
    model="...",
    backend=LocalShellBackend(root_dir=".", virtual_mode=True, env={"PATH": "/usr/bin:/bin"}),
)
```
- 扩展 FilesystemBackend，多出 `execute` 工具（`subprocess.run(shell=True)` 跑在本机，无沙箱）。
- 参数：`timeout`（默认 120s）、`max_output_bytes`（默认 100,000）、`env`、`inherit_env`。
- **注意**：`virtual_mode=True` 在启用 shell 时**不提供安全**（命令可访问任意路径）。三期 executor 用它时务必配 HITL。

### 其他
- `StateBackend()`：默认，线程级，文件存 langgraph state，跨 turn（经 checkpointer）保留、不跨线程。
- `StoreBackend(namespace=...)`：跨线程持久，需配 `store=`（本地用 `InMemoryStore()`；平台部署可省略）。
- `ContextHubBackend("my-agent")`：持久化在 LangSmith Hub repo。

---

## 3. SqliteSaver 接入

来源：`/oss/python/langgraph/checkpointers.mdx` + reference-langchain。

- 包：**`langgraph-checkpoint-sqlite`**（独立安装，最新 **3.1.1**；项目当前未装）。
- 导入路径：`from langgraph.checkpoint.sqlite import SqliteSaver`（异步：`from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver`）。
- 两种构造方式均存在：
```python
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver

# 方式 A：直接连
checkpointer = SqliteSaver(sqlite3.connect("checkpoints.sqlite"))

# 方式 B：连接字符串（官方推荐）
checkpointer = SqliteSaver.from_conn_string("checkpoints.sqlite")

agent = create_deep_agent(model="...", checkpointer=checkpointer)
```
- 同步运行用 SqliteSaver；`.ainvoke/.astream` 请用 AsyncSqliteSaver。
- `from_conn_string` 是 `langgraph.checkpoint.sqlite.SqliteSaver` 上的类方法，已确认存在。

---

## 4. 子代理定义与 task() 委派（0.7.6）

来源：`/oss/python/deepagents/subagents.mdx`。

### 4.1 三种形态（与设计文档一致）
- **`SubAgent`（dict）**：`name`/`description`/`system_prompt` 必填；`tools`/`model`/`middleware`/`interrupt_on`/`skills`/`response_format`/`permissions` 可选。`tools` 默认继承主代理，指定则整体覆盖；`system_prompt` 不继承主代理。
- **`CompiledSubAgent`**：`name` + `description` + `runnable`（必须是已 `.compile()` 的 LangGraph 图）。可用 `langchain.agents.create_agent(...)` 建图。
- **`AsyncSubAgent`**：指向 Agent Protocol 服务器；`AsyncSubAgentMiddleware` 给主管 5 个工具。

```python
from deepagents import create_deep_agent

research_subagent = {
    "name": "research-agent",
    "description": "Used to research more in depth questions",
    "system_prompt": "You are a great researcher.",
    "tools": [internet_search],          # 可选
    "model": "openai:gpt-5.5",           # 可选，覆盖主代理模型
}

agent = create_deep_agent(model="...", subagents=[research_subagent])
```

```python
from deepagents import CompiledSubAgent, create_deep_agent
from langchain.agents import create_agent

custom_graph = create_agent(model="...", tools=[...], system_prompt="...")
custom_subagent = CompiledSubAgent(
    name="data-analyzer",
    description="Specialized agent for complex data analysis",
    runnable=custom_graph,
)
```

### 4.2 默认 general-purpose 子代理
- 未提供名为 `general-purpose` 的同步子代理时，deepagents **自动添加**一个（默认带文件工具）。
- 改名/改提示：`general_purpose_subagent=GeneralPurposeSubAgentProfile(...)`（harness profile 层面）；禁用：`GeneralPurposeSubAgentProfile(enabled=False)`。
- 禁用后必须也不传任何同步 subagents，否则 `task` 工具仍存在。
- 只有存在同步子代理时才挂 `SubAgentMiddleware`（`task` 工具）。

### 4.3 task() 委派
- 主代理通过 **`task` 工具**委派；工具参数为 **`subagent_type`**（文档示例原文：`call the task() tool with subagent_type set to research-agent`）。
- 结构化工装：子代理配 `response_format=` 后，父代理收到 JSON 化的 `ToolMessage` 内容。
- **注意**：Python 侧 `CompiledSubAgent` 字段只有 `name/description/runnable`，**没有 `checkpointer=True` 这类参数**（见 §7 不符处）。

---

## 5. 动态子代理 + CodeInterpreterMiddleware（0.7.6，beta）

来源：`/oss/python/deepagents/dynamic-subagents.mdx` + `interpreters.mdx`。

### 5.1 前置条件
- `langchain-quickjs>=0.2.0`（文档页）；但 **deepagents 0.7.6 的 `quickjs` extra 实际钉 `langchain-quickjs>=0.3.3`**（PyPI 元数据），最新 0.3.5。**本机 0.3.0 不满足，需升级。**
- Python `>=3.11`（deepagents 0.7.6 整体要求 `<4.0,>=3.11`；conda env `thomas` 为 3.12.9 ✓）。
- **beta**：文档明确标注「interpreter runtime 处于 beta，API 与生命周期行为可能变化」。
- 需要 `subagents=[...]` 才有 `task()` 全局；`CodeInterpreterMiddleware(subagents=False)` 可关闭。

### 5.2 接线

```python
from deepagents import create_deep_agent
from langchain_quickjs import CodeInterpreterMiddleware

agent = create_deep_agent(
    model="...",
    subagents=[{
        "name": "reviewer",
        "description": "Reviews code for security issues...",
        "system_prompt": "You are a security-focused code reviewer...",
    }],
    middleware=[CodeInterpreterMiddleware()],
)
```

### 5.3 解释器内置 `task()` 签名（JS）

```js
const review = await task({
  description: "Review src/auth/login.ts for auth issues.",
  subagentType: "reviewer",                    // 已配置子代理名
  responseSchema: { type: "object", properties: {...} },  // 可选
});
// 传了 responseSchema 时，返回已是类型化 JS 对象，无需 JSON.parse
```
- 与设计文档 §8.3 完全一致。
- **触发词 "workflow"**：解释器系统提示把「workflow」当信号 → 走代码内 `task()` 动态编排。单个直接委派请用自然语言直接表达（走原生 task 工具）。
- 三种官方模式：classify-and-act / fan-out-and-synthesize / adversarial verification ✓（§8.4 一致）。
- RLM（递归语言模型）工作流支持 ✓（§8.5 一致）。
- 多轮持久：默认 `mode="thread"`，解释器变量跨 turn 保留；`mode="turn"` 仅单轮；`mode="call"` 每次 eval 全新 REPL。

### 5.4 PTC（Programmatic Tool Calling）
- 默认**关闭**；启用需 `ptc` 白名单：
```python
middleware=[CodeInterpreterMiddleware(ptc=["web_search"])]
```
- 白名单可放工具名或 `BaseTool` 实例；解释器内以 **`tools.*`（camelCase，如 `tools.webSearch(...)`）** 异步调用，需 `await`。
- `max_ptc_calls` 默认 256（限制每次 eval 的 `tools.*` 调用数）。

### 5.5 其他配置项
`memory_limit`(默认 64MB) / `timeout`(默认 5.0s，每次 eval) / `tool_name`("eval") / `capture_console`(True) / `max_result_chars`(4000) / `subagents`(True) / `mode`("thread") / `max_snapshot_bytes`(None)。

### 5.6 安全
- 代码跑在**同进程嵌入式 QuickJS**（`quickjs-rs`），不是独立进程/VM → 是「能力受限执行层」，不是内存隔离边界。不信任代码要放 worker/容器 + 收紧 PTC 白名单。设计文档 §8.7 风险点吻合。

---

## 6. 兼容版本矩阵（PyPI 元数据）

| 包 | 0.7.6 要求 | 最新版 | 本机已装 | 需动作 |
|---|---|---|---|---|
| python | `<4.0,>=3.11` | — | 3.12.9 ✓ | — |
| langchain | `>=1.3.14,<2.0.0` | 1.3.15 | **1.3.10 ✗** | 升级 |
| langchain-core | `>=1.5.0,<2.0.0` | 1.5.5 | **1.4.8 ✗** | 升级 |
| langchain-openai | 非 deepagents 依赖（可选集成）| 1.5.1 | 1.3.2 ✓ | 建议升到 1.5.x |
| langchain-anthropic | `>=1.5.4,<2.0.0`（硬依赖）| — | — | 由 deepagents 自动装 |
| langchain-google-genai | `>=4.3.1,<5.0.0`（硬依赖）| — | — | 由 deepagents 自动装 |
| langsmith | `>=0.10.9` | — | — | 自动装 |
| langgraph-checkpoint-sqlite | 独立安装 | 3.1.1 | **未装** | 新增 |
| langchain-quickjs（quickjs extra）| `>=0.3.3` | 0.3.5 | **0.3.0 ✗** | 升级 |
| tavily-python | 独立安装 | — | — | 新增 |

- `langchain-openai 1.5.1` 自身要求 `langchain-core>=1.5.4` → 与 deepagents 0.7.6（core>=1.5.0）兼容，升级 core 到最新（1.5.5）即可两者同时满足。
- 结论：升级 `deepagents→0.7.6` + `langchain→1.3.15` + `langchain-core→1.5.5` + `langchain-openai→1.5.1` + 新增 `langgraph-checkpoint-sqlite` + `langchain-quickjs>=0.3.3`。注意 langchain 1.3.x 是 major 换代（1.x），升级后需回归验证 `create_agent` 等 API。

---

## 7. 与设计文档（`docs/specs/2026-08-15-javis-design.md`）的不符/需修正处

| # | 位置 | 设计文档 | 实际（0.7.6）| 建议 |
|---|---|---|---|---|
| 1 | §2.1 标题 | 关键调研结论（**v0.7.5**） | PyPI 最新 **0.7.6** | 改版本号 |
| 2 | §2 表格「动态子代理」| `langchain-quickjs`（未给版本） | quickjs extra 钉 `>=0.3.3`；文档页写 `>=0.2.0` | 明确写 `langchain-quickjs>=0.3.3` |
| 3 | §5.2 `backend = CompositeBackend(default=FilesystemBackend(root_dir=project_dir, ...))` | 项目目录做 default | 官方强烈建议 **`default=StateBackend()`**，项目目录放 `routes`（如 `/workspace/`），否则 `/large_tool_results/`、`/conversation_history/` 等内部数据写进项目磁盘 | 改为 `default=StateBackend()` + routes 挂项目目录与 `/vault/` |
| 4 | §5.2 / §4 | 只给了项目 + vault 两条路由 | 长期记忆需 `/memories/` 路由到 `StoreBackend(namespace=...)`，且 `store=` 要传给 `create_deep_agent`（不传 backend） | 补充 `/memories/` 路由与 store 接线 |
| 5 | §5.2 注释 | `root_dir=project_dir`（相对） | root_dir **必须是绝对路径** | 用绝对路径（Windows 反斜杠或 pathlib） |
| 6 | §10.2 | 「子代理 `checkpointer=True` 编译 → 可深入子代理内部回退」 | Python `CompiledSubAgent` 只有 `name/description/runnable`，无 `checkpointer` 参数；深入子代理回退只能靠 runnable 图本身用 checkpointer 编译，且文档未承诺该行为 | 修正描述：子代理内部 time travel 不保证，一期按「子代理算单个 checkpoint」实现 |
| 7 | §2.1 | 中间件列表「retry / tool_error / ...」像是 deepagents 内置 | 这些是 **langchain 预置中间件**，需显式 `middleware=[...]` 传入；deepagents 内置栈另有其名 | 措辞改为「langchain 预置中间件，可传入 middleware=」 |
| 8 | §8.2 | `langchain-quickjs>=0.2.0`，Python `>=3.11` | 一致，但注意 deepagents 0.7.6 要求 quickjs `>=0.3.3` | 统一为 `>=0.3.3` |
| 9 | 一期验收「重启续上下文」| SqliteSaver | 需新装 `langgraph-checkpoint-sqlite`，用 `SqliteSaver.from_conn_string("checkpoints.sqlite")` | 补进 requirements |

**与设计文档一致、无需改动的部分**：§8.3 `task()` JS 签名（description/subagentType/responseSchema）✓；§8.4 三种模式 ✓；§8.5 PTC 白名单 `ptc=["glob"]` + 触发词 workflow + RLM ✓；§8.7 beta 风险 ✓；`create_deep_agent` 参数全集 ✓；后端命名全集 ✓；WIKI 导航式（grep/read_file 原生工具）✓。

---

## 语法速查清单（实现时照抄）

```python
# 1) 模型（OpenAI 兼容端点）
from langchain_openai import ChatOpenAI
model = ChatOpenAI(base_url="https://opencode.ai/zen/v1",
                   api_key="...", model="deepseek-v4-flash")

# 2) 后端：项目 + vault + 长期记忆（推荐形态）
from deepagents.backends import CompositeBackend, StateBackend, FilesystemBackend, StoreBackend
from langgraph.store.memory import InMemoryStore
backend = CompositeBackend(
    default=StateBackend(),
    routes={
        "/workspace/": FilesystemBackend(root_dir=r"E:\Thomas\Python_Project\thomas-project\truly_Javis", virtual_mode=True),
        "/vault/":     FilesystemBackend(root_dir=r"E:\Thomas\Obsidian_warehouse", virtual_mode=True),
        "/memories/":  StoreBackend(namespace=lambda _rt: ("memories",)),
    },
)
store = InMemoryStore()

# 3) 短期记忆
from langgraph.checkpoint.sqlite import SqliteSaver
checkpointer = SqliteSaver.from_conn_string("checkpoints.sqlite")

# 4) 子代理（dict 形态）
subagents = [{
    "name": "researcher",
    "description": "搜索互联网 + 检索 /vault/ 知识库并输出带引用总结",
    "system_prompt": "你是 researcher。检索流程：tavily 搜 → grep /vault/ → 沿 backlink 追笔记 → 融合去重 → 带引用总结。",
    "tools": [tavily_search],
}]

# 5) 组装
agent = create_deep_agent(
    model=model,                       # BaseChatModel 实例直接可用
    system_prompt="你是 JARVIS……",
    subagents=subagents,
    backend=backend,
    store=store,
    checkpointer=checkpointer,
    memory=["./AGENTS.md"],            # 或 /memories/preferences.md
    skills=["./skills/"],
)

# 6) 动态子代理（二期）
from langchain_quickjs import CodeInterpreterMiddleware
agent = create_deep_agent(
    model=model, subagents=subagents,
    middleware=[CodeInterpreterMiddleware(ptc=["glob"])],   # ptc 默认关闭
)
```

---

## 来源
- docs-langchain：`/oss/python/deepagents/customization.mdx`（签名/栈）、`backends.mdx`（后端）、`subagents.mdx`（子代理/task）、`dynamic-subagents.mdx`（动态编排）、`interpreters.mdx`（CodeInterpreterMiddleware/PTC/安全）、`memory.mdx`、`skills.mdx`、`human-in-the-loop.mdx`（interrupt_on）、`/oss/python/langgraph/checkpointers.mdx`（SqliteSaver）。
- PyPI JSON API：`deepagents 0.7.6`、`langchain-openai 1.5.1` 的 `requires_dist`。
- reference-langchain：`langgraph.checkpoint.sqlite.SqliteSaver` / `from_conn_string` 确认。
- `pip index versions`：deepagents 0.7.6 最新；langchain-quickjs 0.3.5 最新；langgraph-checkpoint-sqlite 3.1.1 最新。
