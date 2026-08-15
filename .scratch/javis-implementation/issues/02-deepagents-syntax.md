# 02-deepagents最新语法核验

`Type: research`  `Status: resolved`  `Blocked by:`

## Question

按 README 强制要求#2，用 docs-langchain MCP 核对 deepagents 当前最新版（0.7.x）的实际语法与能力，重点确认：
1. `create_deep_agent` 的签名与关键参数（backend / subagents / skills / memory / checkpointer / middleware）
2. `FilesystemBackend` / `CompositeBackend` / `LocalShellBackend` 的确切构造方式与 `virtual_mode` 用法
3. `SqliteSaver` 的接入方式（`langgraph-checkpoint-sqlite`）
4. 子代理定义（`SubAgent` 与 `task()` 委派）的最新写法
5. 动态子代理（`CodeInterpreterMiddleware` + `task()`）的前置要求是否满足（Python≥3.11 ✅、langchain-quickjs 版本）
6. 与 `langchain-openai` / `langchain` 主版本的兼容版本矩阵

预期产出：一份最新版「语法速查」结论，作为 G1 与后续实现的依据；任何与设计文档不符处在此标出。

## Resolution

由 `/research` 子代理用 docs-langchain MCP 核对完成（findings：`../research/02-deepagents-syntax-findings.md`）。

- **最新版**：`deepagents==0.7.6`（PyPI 最新，设计文档写的 0.7.5 需更正）
- **签名**：`create_deep_agent(model|tools|system_prompt|middleware|subagents|skills|memory|permissions|backend|interrupt_on|response_format|state_schema|context_schema|checkpointer|store|...)`。`model` 可直接传 `ChatOpenAI` 实例。
- **后端**：`FilesystemBackend(root_dir, virtual_mode=True)`（root_dir 必须绝对路径）；`CompositeBackend(default=StateBackend(), routes={...})`（最长前缀优先）；`LocalShellBackend` 无沙箱。
- **SqliteSaver**：`langgraph-checkpoint-sqlite`（最新 3.1.1），`from langgraph.checkpoint.sqlite import SqliteSaver`，`SqliteSaver.from_conn_string("checkpoints.sqlite")` ✅
- **子代理**：dict 形态 `SubAgent`（name/description/system_prompt 必填）+ `CompiledSubAgent` + `AsyncSubAgent`；默认自动加 `general-purpose`；主代理走 `task` 工具（`subagent_type` 参数）
- **动态子代理**：`langchain_quickjs.CodeInterpreterMiddleware`，`langchain-quickjs>=0.3.3`、Python>=3.11、beta；JS `task({description, subagentType, responseSchema})`；PTC 需 `ptc=[...]` 白名单
- **兼容矩阵**：0.7.6 要求 `langchain>=1.3.14`、`langchain-core>=1.5.0`
- ⚠️ **本机现状不满足**：deepagents 0.6.11、langchain 1.3.10、core 1.4.8、quickjs 0.3.0——需升级（清单见 findings §6）

### 设计文档需修正（4 处重点）
1. 版本 0.7.5 → **0.7.6**
2. `CompositeBackend` 的 default 应为 **`StateBackend()`** 而非项目目录（否则内部数据落盘）
3. 长期记忆缺 `/memories/` → `StoreBackend` 路由，且 `store=` 传参位置要更正
4. §10.2「子代理 `checkpointer=True` 编译」在 Python 侧不存在，子代理内部 time travel 无法保证
