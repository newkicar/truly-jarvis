# Spec: JARVIS 一期 MVP（核心心智能力）

`Status: ready-for-agent`

> 依赖：本 spec 之前已完成 wayfinder 决策票 01/02/03/04。参见 `.scratch/javis-implementation/map.md`。

## Problem Statement

用户有一个庞大、持续增长的个人知识库（Obsidian vault，`E:\Thomas\Obsidian_warehouse`，含 46 篇笔记），以及一个持续变化的行业环境。但知识与资讯的获取是割裂的：

- 检索自己的笔记要靠人工在 Obsidian 里翻找，知识关联（wikilink/backlink）未被利用。
- 获取最新行业动态要自己盯资讯源，**注意力被大量无关信息消耗**。
- 没有一个统一的入口能「一边翻自己的已知，一边补外部的未知」，再收敛成一份带来源的结论。

用户希望有一个 JARVIS 式的助手：**问它一个学习/调研类问题，它能同时检索本地知识库和互联网，过滤无用信息，输出带来源引用的结构化总结**——把「收集→过滤→总结」这整个心智过程外包出去，让用户的注意力只花在最终结论上。

一期 MVP 的目标是跑通这条**核心心智管道**：CLI 交互 + 主代理路由 + researcher 子代理（本地 WIKI 导航检索 + 互联网搜索 + 带来源总结）+ 会话记忆 + 会话回退。

## Solution

用户在一个纯 CLI 里与 JARVIS 对话。当问及「调研/最新动态/我的笔记里」类问题时，JARVIS 自动委派 researcher 子代理：

1. 先用原生文件工具以 **WIKI 导航式**检索本地 Obsidian 知识库（grep 关键词 → 读命中笔记 → 沿 wikilink/backlink 追关联）。
2. 再用 Tavily 搜索互联网并抓取全文。
3. 本地结果优先、互联网补充，过滤无用信息。
4. 输出一份结构化 markdown 总结：TL;DR → 分节要点（每条带来源）→ 知识库相关笔记（/vault/ 路径）→ 参考资料（URL）。

会话有记忆：重启后上下文仍在；可通过 `/history` `/replay` `/fork` `/sessions` 回退/分叉历史会话。

## User Stories

1. 作为用户，我希望在终端启动 JARVIS 并进入对话，以便随时开始一次学习/调研。
2. 作为用户，我希望直接问自然语言问题（如「调研大模型行业最新动态」），以便不用学习任何命令语法。
3. 作为用户，我希望 JARVIS 自动识别「调研/最新动态/行业资讯」类问题并委派 researcher，以便不手动指定子代理。
4. 作为用户，我希望 JARVIS 自动识别「我的笔记里关于 X」类问题并检索本地知识库，以便利用我积累的知识。
5. 作为用户，我希望 researcher 优先用 WIKI 导航式检索本地 vault（grep→read→追 backlink），以便知识库内容被真正利用且零索引维护。
6. 作为用户，我希望 researcher 用 Tavily 搜索互联网并抓取全文，以便获得最新、深度的外部信息。
7. 作为用户，我希望本地 vault 结果优先、互联网结果补充，以便「我的已知」是基线、外部信息补时效。
8. 作为用户，我希望 researcher 过滤无关/重复信息，以便注意力不被稀释。
9. 作为用户，我希望输出是结构化 markdown（TL;DR + 分节要点 + 知识库相关笔记 + 参考资料），以便快速抓住结论、按需深挖。
10. 作为用户，我希望每条要点都带来源（vault 路径或网页 URL），以便溯源验证。
11. 作为用户，我希望闲聊/纯知识问答由主代理直接回答、不触发检索，以便响应快速、不浪费额度。
12. 作为用户，我希望重启 JARVIS 后上次会话的上下文仍在，以便延续讨论。
13. 作为用户，我希望 `/sessions` 列出历史会话，以便回到某次对话。
14. 作为用户，我希望 `/history` 查看当前会话的时间线，以便定位到某个历史节点。
15. 作为用户，我希望 `/replay <checkpoint_id>` 从历史节点重跑，以便回顾/复现当时的决策过程。
16. 作为用户，我希望 `/fork <checkpoint_id>` 从历史节点分叉出新分支，以便在保留原历史的前提下探索替代方案。
17. 作为用户，我希望 `/exit` 退出 CLI，以便正常结束。
18. 作为用户，我希望配置（vault 路径、模型、记忆目录）都在 javis.json 里可改，以便不写死路径。
19. 作为用户，我希望 `.env` 的密钥不进入 git，以便安全。
20. 作为用户，我希望 researcher 不确定的信息标注「待核实」，以便不把推测当事实。

## Implementation Decisions

- **配置层（src/config.py）**：
  - 读取 `.env` 中的 `BASE_URL` / `API_KEY` / `MODEL_ID` / `TAVILY_KEY`。⚠️ 当前 `.env` 是 `:` 分隔、小写键的非标准格式（`python-dotenv` 读不了），`config.py` 需先做兼容解析（支持 `KEY:VALUE` 与 `KEY=VALUE` 两种，键大小写不敏感），再读取 javis.json。
  - 读取 `javis.json`：模型 env 名映射、`obsidian_vault` 路径、`memory_dir`、`skills`、`mcps`、`schedules`。
  - 产出配置 dataclass，全部路径用绝对路径（Windows）。
- **工具层（src/tools.py）**：
  - `tavily_search(query, max_results)`：用 Tavily 搜索 → 返回 URL 列表 → 对值得的 URL 用 `httpx` 抓全文 → `markdownify` 转 markdown → 拼成结构化文本。
- **子代理层（src/subagents.py）**：
  - `researcher` 定义为 `SubAgent` dict（name/description/system_prompt/tools），定义见 04 票 Resolution 定稿。system_prompt 固化为：WIKI 导航式检索流程 + 互联网搜索 + vault 优先融合去重 + 结构化带来源输出格式。
  - `knowledge_keeper` / `executor` 本期仅留定义骨架（不在一期激活）。
- **主代理组装（src/agent.py）**：
  - `build_agent(config)` 用 `create_deep_agent` 组装：模型为 `ChatOpenAI(base_url, api_key, model)`；后端为 `CompositeBackend(default=StateBackend(), routes={/workspace/, /vault/, /memories/})`（root_dir 均绝对路径 + `virtual_mode=True`）；`store=InMemoryStore()`；`checkpointer=SqliteSaver`；`memory=[...]` 注入记忆文件；`skills=[...]`。
  - ⚠️ `SqliteSaver.from_conn_string(path)` 返回 **context manager**，必须在 `with ... as checkpointer:` 块内创建 agent，agent 生命周期随连接。
  - 主代理 system_prompt：JARVIS 人格 + 路由规则（双触发：时效/本地知识 → researcher；闲聊 → 自答）。
- **CLI（src/main.py）**：
  - 一期用标准库 `input()` 交互循环；`thread_id` 即会话标识（`session_id`）。
  - 内置命令：`/exit`、`/sessions`、`/history`、`/replay <id>`、`/fork <id>`。
  - 会话回退用 LangGraph checkpointer 原生能力：`get_state_history`（列历史）、`invoke(None, prior.config)`（回放）、`update_state(prior.config, values)`（分叉）。
- **git 快照（src/time_travel.py）**：文件状态回退为 git 快照，每 turn 一 commit + `{thread_id, checkpoint_id, commit_hash}` 映射表。⚠️ 一期只做**会话回退**（checkpointer 原生）；git 文件回退是二期。vault 不纳入 git 回退。
- **模型**：go 套餐 `https://opencode.ai/zen/go/v1` + `deepseek-v4-flash`（已验证对话 + tool calling ✅）。模型名不加前缀。
- **目录**：`src/` 已按 §11 建好 stub；`memory/`、`skills/` 已建占位。

## Testing Decisions

- **好测试的标准**：只测外部行为（函数输入→输出、agent 的可见响应），不测内部实现细节；确定性优先。
- **测试层级**：
  1. **单测（fake，无外部依赖）**：
     - `src/config.py`：`.env` 两种分隔格式解析、javis.json 读取、路径绝对化、缺 key 报错。纯函数，最高价值。
     - `src/tools.py`：mock Tavily client 与 httpx，验证搜索→抓取→markdownify 的拼接与异常处理（网络失败、空结果）。
     - `src/agent.py`：用 LangChain `FakeMessagesListChatModel` + mock 工具，验证 `build_agent` 能成功组装、`invoke` 能走通并返回消息。
  2. **真实模型冒烟脚本**（手动运行，不进 CI）：`smoke_test.py` 用真实 go 套餐模型跑一次「调研」问题，验证端到端（路由→researcher→结构化总结）。因消耗额度，仅手动触发。
- **测试框架**：`pytest`。
- **测试目录**：`tests/`（tests/test_config.py、tests/test_tools.py、tests/test_agent.py、smoke_test.py）。
- **先例**：仓库暂无测试（骨架阶段）；deepagents 官方示例（deep-research）作为集成测试范式参考。

## Out of Scope

- git 文件回退（二期，时间线映射表本期不建）。
- knowledge_keeper 回写 Obsidian（二期）。
- 定时检索（APScheduler，二期）。
- 动态子代理 fan-out（二期）。
- 长期记忆 StoreBackend 实际启用（一期用 InMemoryStore 占位）。
- skill/mcp 扩展接口实际接入（三期）。
- textual TUI（二期）。
- vault 文件状态回退（明确不纳入，靠 Obsidian 恢复）。
- 真实模型自动化测试纳入 CI（额度/非确定性，仅冒烟）。

## Further Notes

- 依赖已按 02 票版本矩阵安装成功（deepagents 0.7.6 / langchain 1.3.15 / core 1.5.5 / langchain-openai 1.5.1 / langgraph-checkpoint-sqlite 3.1.1 / langchain-quickjs 0.3.5）。
- conda env `thomas` 残留 embedchain 等旧包与 langchain 1.3.x 冲突（pip 警告），不影响 JARVIS，实现时避免误用。
- `.env` 已含密钥，已 gitignore；`config.py` 兼容解析是第一个实现点。
- researcher 的最终 system_prompt 以 04 票 Resolution 为准。
