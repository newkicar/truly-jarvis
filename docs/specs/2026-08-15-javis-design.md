# JARVIS 设计文档

> 对标钢铁侠 JARVIS：可探讨技术、可学习知识、可共创方案、可执行任务。
> 核心理念：AI 时代 agent 的首要任务是**扩展人类心智**——过滤无用信息、总结有用信息，解决「注意力稀缺」。自动化只是副产品。

日期：2026-08-15
状态：已定稿（待实现）——已于 2026-08-15 依 deepagents 0.7.6 实测核验修订（§2/§5.2/§6/§8.2/§10.2/§12）

---

## 1. 目标与设计原则

### 1.1 使命
AI 时代，agent 最重要的任务不是自动完成工作，而是扩展人类的心智。通过「搜索互联网 + 本地知识库」，过滤无用信息、保留并总结有用信息，帮助用户快速掌握最新资讯、技术动态、行业知识。

### 1.2 四个可交付能力
1. **可探讨技术** —— 对话式技术讨论
2. **可学习知识** —— 检索、过滤、总结并沉淀知识
3. **可共创方案** —— 多角度调研 + 方案共创
4. **可执行任务** —— 自动化执行（二期）

### 1.3 三条工程原则
1. **复用不重造**：deepagents 原生工具（`ls/read_file/write_file/edit_file/glob/grep/execute/task`）、原生中间件、原生后端优先使用。
2. **扩展留接口**：skill / mcp / tools 均以「注册接口」方式接入，能力可后装。
3. **配置外置**：一切可变项（模型、vault 路径、记忆目录、定时任务目录）进 `javis.json` 或外置 JSON（定时任务走 `schedules/` 每任务一文件），不写死在代码里。

---

## 2. 技术选型（含调研依据）

| 组件 | 选型 | 依据 |
|---|---|---|
| 主 agent 库 | `deepagents==0.7.x`（2026-08 最新） | README 指定；`create_deep_agent()` 原生覆盖子代理/技能/记忆/文件后端/checkpointer |
| LLM 接入 | `langchain-openai` 的 `ChatOpenAI` | `.env` 是 OpenAI 兼容端点（`https://opencode.ai/zen/go/v1`（go 按月套餐） + mimo-v2.5，经 `MODEL_ID` 读取）|
| 短期记忆 | `langgraph-checkpoint-sqlite` 的 `SqliteSaver` | 本地单机最佳，重启可续；deepagents 官方推荐 |
| 长期记忆 | deepagents `FilesystemBackend` 指向项目 `memory/` | 文件持久、用户可看可编辑；`memory=` 注入所有 `*.md`（**不用 StoreBackend**，避免引入 Mem0/Zep/Letta 等重依赖）|
| 知识库访问 | `FilesystemBackend` 指向 Obsidian vault（WIKI 导航式） | 零索引维护、原生工具直接浏览 markdown + wikilink |
| 互联网搜索 | `tavily-python` + `httpx` + `markdownify` | 对齐官方 deep-research 范式（搜索→抓全文→转 markdown）|
| 动态子代理 | `langchain-quickjs`（`>=0.3.3`）的 `CodeInterpreterMiddleware` | v0.7 新增；agent 用 JS 编排子代理（fan-out）；quickjs extra 钉 `>=0.3.3` |
| 定时调度 | `APScheduler` | 内置进程内调度，随主进程跑 |
| 配置 | `python-dotenv` + `javis.json` | 读取 `.env` 与全局配置 |
| 文件回退 | git 快照（**手动 `/snapshot`**，不用自动每轮 commit） | Claude Code / Cursor / opencode 同款做法 |

### 2.1 deepagents 关键调研结论（v0.7.6）
- `create_deep_agent(model, tools, system_prompt, subagents, skills, memory, permissions, backend, middleware, checkpointer, store, ...)`（另有 `response_format` / `state_schema` / `context_schema` 等新增参数；`model` 可直接传 `BaseChatModel` 实例）
- 原生工具：`ls / read_file / write_file / edit_file / glob / grep / execute / task`
- 子代理：`SubAgent`（dict）/ `CompiledSubAgent` / `AsyncSubAgent`；默认自动加 `general-purpose`；主代理通过 `task()` 工具委派（参数 `subagent_type`）
- 技能：`skills=[...]` 读 `SKILL.md` frontmatter 索引，需要时加载全文（渐进式披露）
- 记忆注入：`memory=[...]` 指向文件（始终注入）
- 后端：`StateBackend`（默认）/ `FilesystemBackend` / `LocalShellBackend` / `StoreBackend` / `CompositeBackend` / `ContextHubBackend`
- 中间件：retry / tool_error / model_fallback / call_limit / summarization / human-in-the-loop 为 **langchain 预置中间件**，需显式 `middleware=[...]` 传入（deepagents 内置栈另有 SkillsMiddleware / FilesystemMiddleware / SubAgentMiddleware 等）
- 长短期记忆：短期=`checkpointer`；长期=项目 `memory/*.md`，`memory=` 注入 + `/memories/` 路由到 `FilesystemBackend`（**不用 StoreBackend**，文件持久且用户可编辑）
- ⚠️ 兼容版本：0.7.6 要求 `langchain>=1.3.14`、`langchain-core>=1.5.0`、`langchain-quickjs>=0.3.3`（本机旧版需升级）

---

## 3. 总体架构（主代理 + 子代理）

```
                    ┌─────────────────────────────────────┐
   用户 (CLI)  ───▶ │  主代理 JARVIS 编排器（意图路由）      │
                    │  · system_prompt 定义人格与路由规则      │
                    │  · CompositeBackend（项目 + vault）     │
                    │  · SqliteSaver（短期记忆 + time travel）│
                    └──────────────┬──────────────────────┘
                         task() 委派（隔离上下文）
        ┌──────────────────┬──────────────┬──────────────────┐
   ┌────▼─────┐      ┌──────▼──────┐  ┌────▼───────┐   ┌─────▼──────┐
   │researcher│      │knowledge_   │  │ shell 执行  │   │ (动态编排)   │
   │ 心智能力  │      │  keeper     │  │ (主代理直接) │   │ fan-out     │
   │ 搜索+检索 │      │ 知识管理员   │  │ execute+审批│   │ workflow    │
   │ 过滤+总结 │      │ 回写+链接维护 │  │ (见 §9)    │   │            │
   └──────────┘      └─────────────┘  └────────────┘   └────────────┘
```

**主代理 system_prompt 要点**：
- 人格：钢铁侠 JARVIS（冷静、专业、条理、带引用）。
- 路由规则：检索/学习类 → `task(subagent_type="researcher")`；写知识 → `knowledge_keeper`；需要执行 shell 命令 → 主代理直接用 `execute`（经 HITL 审批，见 §9）；闲聊/探讨 → 自己答。
- 复杂/多角度研究 → 触发动态子代理 fan-out（见 §6.2）。

---

## 4. 配置层（javis.json，模拟 opencode）

```jsonc
{
  "model": {
    "base_url_env": "BASE_URL",      // 从 .env 读，不硬编码 key
    "api_key_env": "API_KEY",
    "model_id_env": "MODEL_ID"
  },
"obsidian_vault": "E:\\Thomas\\Obsidian_warehouse",  // 可改、可增（多个目录）
  "memory_dir": "memory",            // 信息记忆（用户偏好/行业）→ 项目目录
  "schedules_dir": "schedules",      // 定时任务配置目录（每任务一个 JSON，二期）
  "skills": ["skills/"],             // 已安装 skill（渐进式披露）
  "mcps": [],                        // 已安装 MCP server
  "permissions": {                   // HITL 审批（对标 opencode permission）
    "*": "ask",                      // 默认：不配置即每次审批
    "execute": {"*": "ask", "git *": "allow"}  // 可按命令前缀精细控制
  }
```

**`.env` 规范化**（当前为 `:` 分隔小写，实现时统一为标准格式）：
```dotenv
BASE_URL=https://opencode.ai/zen/go/v1
API_KEY=sk-...
MODEL_ID=mimo-v2.5
TAVILY_KEY=tvly-dev-...
```
**`.gitignore`**：忽略 `.env`（含密钥）、`checkpoints.sqlite`、快照映射库等。

---

## 5. 知识库访问方法（核心决策：WIKI 导航式）

### 5.1 选型理由与 tradeoff 处理
| 候选 | 优点 | 缺点 | 处理 |
|---|---|---|---|
| RAG 向量检索 | 语义准、跨文档关联强 | 索引随知识库更新有维护负担 | 一期不用；二期若要，用**文件 hash 增量索引**（只重建变更文件）|
| Skill 渐进式披露 | 省 token | 文件间关联弱 | 仅作「检索方法论」封装，非主方案 |
| **WIKI 导航式（选）** | 零索引、实时更新、原生工具直接可用 | 靠关键词+链接，无语义 | 用 Obsidian 已有 **wikilink/backlink/MOC** 结构补关联 |

### 5.2 实现方法
```python
from deepagents.backends import CompositeBackend, StateBackend, FilesystemBackend

backend = CompositeBackend(
    default=StateBackend(),   # 内部数据（/large_tool_results/ 等）走临时 state，不落盘
    routes={
        "/workspace/": LocalShellBackend(root_dir=r"<项目绝对路径>", virtual_mode=True),  # 含 execute
        "/vault/":     FilesystemBackend(root_dir=config.obsidian_vault, virtual_mode=True),
        "/memories/":  FilesystemBackend(root_dir=config.memory_dir, virtual_mode=True),
    },
)
```
- `root_dir` 必须是**绝对路径**（Windows 反斜杠或 `pathlib`）；`virtual_mode=True` 启用路径沙箱。
- 检索流程（写进 researcher system_prompt）：`grep` 命中关键词 → `read_file` 读笔记 → 顺 **backlink** 追关联笔记 → 再读 → 综合。
- 回写：`knowledge_keeper` 用 `write_file` 在 `/vault/Inbox/` **新增**带 wikilink 的笔记（**只新增，绝不修改/删除既有笔记**；wikilink 仅关联确实存在的笔记，不编造）。用户在 Obsidian 审核后手动归档。
- 升级路径：同路径加向量索引工具做语义召回，`grep` 与语义结果合并去重，即「导航 + 增量 RAG 增强」。

---

## 6. 记忆方案（长短期分离）

**原则**：**知识 → Obsidian vault；信息记忆（偏好/行业）→ 项目目录**。

| 类型 | 载体 | deepagents 实现 |
|---|---|---|
| 短期（会话内） | SQLite | `checkpointer=SqliteSaver`（`checkpoints.sqlite`）|
| 长期·信息记忆 | 项目 `memory/*.md` | `memory=[...]` 注入所有 `*.md`（除 README）+ `/memories/` 路由到 `FilesystemBackend`（文件持久、用户可看可编辑；**不用 StoreBackend**）|
| 长期·知识 | Obsidian vault | `FilesystemBackend` 读写（WIKI 导航）|

**记忆 vs 知识分流规则**：
- `事实/概念/学习成果 → /vault/`（知识，写经 knowledge_keeper 到 `/vault/Inbox/`）
- `偏好/身份/决策 → memory/*.md`（信息记忆，`memory=` 注入，用户可编辑）

---

## 7. 心智能力（指定检索 + 定时检索）

### 7.1 指定检索流程（一期核心）
```
用户提问 → 主代理路由 → researcher 子代理：
  1. tavily_search 搜互联网（Tavily 找 URL → httpx 抓全文 → markdownify 转 md）
  2. grep/glob 检 /vault/ 本地知识库
  3. 融合去重 → 过滤无用信息 → 总结为带引用 markdown
  4. 返回终端展示
  5. （可选）knowledge_keeper 回写 Obsidian
```

### 7.2 定时检索流程（二期，APScheduler）
```
schedules/<任务>.json 配置（时间/任务/保存路径/要求）
→ src/scheduler.py 启动时扫描注册 CronTrigger
→ 到点调同一 researcher 管道（复用，无重复代码）
→ 结果按 save_path 写文件（vault:Inbox/ 等）
```
要点：定时任务与指定检索**共用同一检索管道**，调度器只负责「何时触发 + 写哪」。
任务配置**外置为独立 JSON**（每任务一文件，增删 = 加删文件），字段：`id/enabled/cron/task/save_path/requirements`。save_path 前缀约定 `vault:`（相对 vault）、`workspace:`（相对项目）。仅进程内调度，随 CLI 启动。
改 `schedules/*.json` 后可用 CLI `/reload-schedules` 重载（无需重启）；任务失败会写 `.error.md` 标记并打印 traceback（绝不静默）。

---

## 8. 动态子代理（Dynamic Subagents，v0.7 新增，已确认）

### 8.1 机制
agent 不再「一次选一个子代理」，而是**从解释器代码里动态派发子代理**。加装 `langchain-quickjs` 的 `CodeInterpreterMiddleware` 后，解释器暴露内置 `task()` 全局函数，agent 用 **JavaScript 的循环、分支、并行批量**编排子代理并合成结果。

### 8.2 前置条件
- `langchain-quickjs>=0.3.3`（deepagents 0.7.6 的 quickjs extra 钉版），Python `>=3.11`
- `middleware=[CodeInterpreterMiddleware()]`
- **beta**（API 可能变动）

### 8.3 `task()` 签名
```js
const r = await task({
  description: "任务描述",
  subagentType: "reviewer",      // 已配置的子代理名
  responseSchema: {...},         // 可选，结构化输出
});
```

### 8.4 三种官方模式
1. **classify-and-act**：先分类，再按类别路由到不同子代理
2. **fan-out-and-synthesize**：同一类工作并行派发到多个子代理，再合并结果
3. **adversarial verification**：首轮产出 + 独立验证子代理二轮复核

### 8.5 辅助能力
- **PTC**（Programmatic Tool Calling）：解释器代码里用 `tools.*` 调用工具，默认关闭，需 `ptc=["glob"]` 白名单
- 触发词 **"workflow"** 引导 agent 走动态编排
- 支持 **RLM**（递归语言模型）工作流

### 8.6 对 JARVIS 的应用
**研究/检索升级为 fan-out-and-synthesize**（多角度并行再收敛）：
```
用户：「调研 XXX 最新进展」
→ 主代理（workflow 触发）
→ 解释器写 JS：
     const angles = ["技术原理", "竞品动态", "行业影响", "落地案例"];
     const results = await Promise.all(angles.map(a =>
        task({ description: a, subagentType: "researcher" })
     ));
     → N 个 researcher 并行搜索+检索+总结
→ 合并去重 → 综合为带引用报告
```
命中 README「过滤无用信息 + 总结有用信息」——并行多角度检索再收敛，质量高于串行单点检索。

### 8.7 风险
1. beta 特性 API 可能变
2. 依赖模型写 JS 的能力（需实测 deepseek-v4-flash）
3. QuickJS 解释器有安全边界（沙箱）

---

## 9. 自动化能力（skill/mcp/tools 扩展接口）

- **原生工具**：`execute`（`LocalShellBackend` 提供）、文件工具直接可用，不重造。
- **tools 注册接口**：`create_deep_agent(tools=[...])` 统一挂载自定义工具。
- **skill 接口**：`skills=[...]` 目录扫描 `SKILL.md`（frontmatter 索引 + 按需加载），技能库目录即扩展点。
- **mcp 接口**：`mcps` 配置项 → `langchain-mcp-adapters` 加载外部 MCP server 工具，动态并入 `tools`。
- **执行能力**（三期）：主代理 `/workspace/` 路由用 `LocalShellBackend`（= FilesystemBackend + `execute`），主代理与所有子代理直接具备 shell 执行能力，**不设独立 executor 子代理**。
- **HITL 审批**（对标 opencode `permission`）：`javis.json` 的 `permissions` 段控制哪些 gated 工具需审批。
  - `"allow"` = 自动放行 / `"ask"` = 每次审批（默认）/ `"deny"` = 拒绝。
  - 支持对象形态规则集 `{"*": "ask", "git *": "allow"}`（最后匹配胜出），用于按命令前缀/路径模式精细控制。
  - 实现：`src/permissions.py` 把配置转成 `create_deep_agent(interrupt_on=...)`；`when` 谓词闭包引用可变 state，「always approve」只改 state + 写回 `javis.json`，无需重建 agent。
  - CLI 审批交互：`[y]本次放行 [n]拒绝 [e]编辑参数 [a]always approve`（三期 TUI 改为选择式，同 opencode）。

---

## 10. Time Travel（会话 + 文件双层）

### 10.1 双层设计
| 层 | 机制 | 覆盖范围 |
|---|---|---|
| **会话/任务回退** | LangGraph checkpointer（原生，无需 git） | 全部对话与 agent 状态 |
| **文件状态回退** | git 快照（**手动 `/snapshot`**） | **仅项目目录**（代码 + `memory/`）|

### 10.2 会话回退（原生，thread_id + checkpoint_id）
- `session_id = thread_id`，`task_id = checkpoint_id`（每个 super-step 一个）
- 定位：`get_state_history(config)` 倒序列出历史
- 读某时刻：`get_state({"configurable": {"thread_id", "checkpoint_id"}})`
- 回放：`invoke(None, prior.config)` 重跑该点之后
- 分叉：`update_state(prior.config, values, as_node=...)` 开新分支，**原历史保留**
- 子代理：Python 侧 `CompiledSubAgent` 只有 `name/description/runnable`，无 `checkpointer` 参数；子代理内部 time travel **不保证**，一期按「子代理算单个 checkpoint」实现
- CLI 命令：`/sessions`、`/history`、`/replay <id>`、`/fork <id>`、`/snapshot`、`/snapshots`、`/rollback <id>`、`/reload-schedules`
- **`/history` 只显示「边界点」**：`metadata.source in (input, fork, update)`，过滤掉中间 loop 超步骤（工具调用/子代理，会刷出 90+ 条噪音）。顺序从旧到新，每行带用户消息摘要（前 50 字）+ **短 id（前 13 位）**。
- **短 id 前缀匹配**：`/replay <id>`、`/fork <id>` 接受完整 id 或短 id（`/history` 显示的），按前缀唯一匹配；歧义返回失败。
- **`/fork` 后切换会话**：分叉成功返回新 thread_id，CLI 交互循环自动切到新会话（原 bug：fork 后仍写回旧线程）。
- **定时任务线程自动清理**：`_run_task` 结束（成功或失败）后 `checkpointer.delete_thread("sched-<id>")`，避免 `sched-*` 线程累积污染 checkpoints 表；`/sessions` 同时过滤 `sched-` 前缀线程。

### 10.3 文件回退（git 快照，**手动**触发）
- **纳入 git**：项目目录（`src/`、`memory/`、`javis.json` 等）
- **手动 `/snapshot`**：用户主动触发时，若项目目录有文件变更 → `git add -A && git commit -m "javis <checkpoint_id>"`（不自动每轮 commit，避免刷爆历史）
- **映射表**（项目内 SQLite）：`{thread_id, checkpoint_id, commit_hash, timestamp}`，`git_mapping.sqlite` 被 gitignore
- **回退**：会话 `update_state`/replay 回退 + 文件 `/rollback <checkpoint_id>` → `git reset --hard <对应 commit>`，两者对齐
- **`/snapshots`**：从旧到新，每行显示时间戳 + 短 commit（前 10 位）+ 所属线程 + 短 cid（前 13 位）；`/rollback <短cid>` 支持前缀唯一匹配。

### 10.4 Obsidian vault 处理（不纳入 git）
- vault 文件写入**不参与 git 回退**，依赖 Obsidian 自带 **File Recovery（文件恢复）插件**兜底。
- 后果：agent 回写 vault 的知识笔记无法 git 回退，只能靠 Obsidian 快照/手动改。
- 后续如需 vault 可回退，再补「vault 单独 git」或「写前日志」（接口预留）。

---

## 11. 项目结构

```
truly_Javis/
├── javis.json                # 全局配置
├── .env  /  .gitignore  /  requirements.txt
├── docs/specs/               # 设计文档
├── src/
│   ├── __init__.py
│   ├── main.py               # CLI 入口（readline 交互循环，/exit 退出）
│   ├── config.py             # 读 .env + javis.json → 配置 dataclass
│   ├── agent.py              # 组装：model + backend + subagents + memory + checkpointer
│   ├── subagents.py          # researcher / knowledge_keeper / executor 定义
│   ├── tools.py              # tavily_search 等自定义工具
│   ├── time_travel.py        # /history /replay /fork /sessions + git 映射表
│   └── scheduler.py          # APScheduler 定时任务（二期）
├── memory/                   # 信息记忆（用户偏好等 markdown）
└── skills/                   # 已安装 skill（SKILL.md）
```

---

## 12. 分阶段路线

| 阶段 | 范围 | 验收 |
|---|---|---|
| **一期（MVP）** | 主代理 + researcher（指定检索，直接 task() 委派）+ WIKI 导航知识库 + SqliteSaver 短期记忆（`langgraph-checkpoint-sqlite`，`SqliteSaver.from_conn_string("checkpoints.sqlite")`）+ 会话回退（/history /replay /fork /sessions）+ javis.json + Tavily | 问「调研 XXX」→ 搜索+检索+带引用总结；问「笔记里 YYY」→ vault 命中；重启续上下文；可回退历史会话 |
| **二期** | 动态子代理 fan-out（CodeInterpreterMiddleware，先实测 deepseek-v4-flash 写 JS）+ knowledge_keeper 回写 + APScheduler 定时检索 + 长期记忆（memory/ FilesystemBackend）+ git 文件回退（/rollback）+ **事件流式输出（event streaming）** | 定时自动检索并回写 Obsidian；偏好跨会话记忆（memory/*.md 注入）；多角度并行研究；文件可回退；CLI 实时可见子代理/工具/回答流式输出（见票 11） |
| **三期** | executor + LocalShellBackend + skill/mcp 扩展接口 + 增量 RAG 增强 + vault 回退增强（可选） | 可执行任务；可安装外部 skill/mcp；语义检索增强 |

---

## 13. 技术风险与对策

| 风险 | 对策 |
|---|---|
| 动态子代理为 beta，API 可能变 | 一期不用；二期接入前再次核对最新版语法；deepseek-v4-flash 写 JS 能力先实测，不行回退串行 |
| 模型需支持 tool calling | opencode.ai/zen/go/v1 为 OpenAI 兼容端点（go 套餐），deepseek 系列支持 tool calling，已冒烟验证；2026-08-17 起切 mimo-v2.5 |
| `.env` 当前格式不规范 | 实现时统一为标准 dotenv（`KEY=VALUE`），加 `.gitignore` |
| vault 大/含附件不便 git | vault 不纳入 git，走 Obsidian 恢复兜底 |
| 中文检索靠 grep 关键词，无语义 | 以 wikilink/backlink 补关联；二期可选增量 RAG 增强 |

---

## 14. 验收标准汇总

### 一期（MVP）
- [x] CLI 启动交互
- [x] 问「帮我调研 XXX 最新进展」→ researcher 搜索互联网 + 检索 vault → 带引用 markdown 总结
- [x] 问「我笔记里关于 YYY 的内容」→ 原生工具在 `/vault/` 命中并回答
- [x] 重启后对话上下文仍在（SqliteSaver）
- [x] `/sessions` `/history` `/replay` `/fork` 会话回退可用

### 二期
- [x] 定时检索自动触发并回写 Obsidian
- [x] knowledge_keeper 知识沉淀（对话中精选知识 → 带 wikilink 笔记写入 /vault/Inbox/，只新增不改动）
- [x] 多角度并行研究（fan-out）
- [x] 用户偏好跨会话记忆（`memory/*.md` 注入，FilesystemBackend）
- [x] git 文件回退（`/rollback`）可用
- [x] 事件流式输出（`stream_events` v3）：子代理/工具调用/最终回答实时可见，工具失败能看到 error

### 三期
- [x] 主代理直接 shell 执行能力（`/workspace/` 换 `LocalShellBackend`，不再设独立 executor 子代理）
- [x] HITL 审批（`javis.json` `permissions`：allow/ask/deny + 规则集；CLI y/n/e/a）
- [ ] 可安装外部 skill / mcp
- [ ] 增量 RAG 语义增强
