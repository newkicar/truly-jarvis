> AI时代，agent最重要的任务并不是自动完成工作，而是扩展人类的心智
>> 机器出现：人类的力量变强了，需要更多的计算
>> 计算机时代：人类的计算能力变强了，需要更多的共享
>> 互联网时代：人类的信息共享能力变强了，需要更多的注意力
>> AI时代：AI的真正用途是：可以帮人类过滤无用的信息，总结有用的信息，以使得人类的注意力不再稀缺——>本项目的最重要目标
>> 自动化工作：是每个时代都会出现的副产品：机器时代自动化的机器、计算机时代自动化的软件、互联网时代自动化的系统、AI时代自动化的创作

主要编程语言：python  
主 agent 库：deepagents  
项目目标：100% 对标钢铁侠的 JARVIS——可探讨技术、可学习知识、可共创方案、可执行任务

领域术语见 [`CONTEXT.md`](CONTEXT.md)（Vault / Inbox / 沉淀 / 归档等）。

---

## 快速开始

### 环境

- Python 3.11+（推荐 3.12）
- 依赖：`pip install -r requirements.txt`
- 模型：`.env` 配置 OpenAI 兼容端点（当前默认 `https://opencode.ai/zen/go/v1` + `mimo-v2.5`）
- 知识库：Obsidian vault 路径写在 `javis.json` 的 `obsidian_vault`
- 可选：Ollama（增量 RAG embedding）、已配置的 MCP servers

### 配置

1. 复制并填写 `.env`（支持 `KEY:VALUE` 或 `KEY=VALUE`，键名大小写不敏感）：

```dotenv
BASE_URL=https://opencode.ai/zen/go/v1
API_KEY=sk-...
MODEL_ID=mimo-v2.5
TAVILY_KEY=tvly-...
```

2. 编辑 `javis.json`：vault 路径、`permissions`、`mcps.servers`、`schedules_dir` 等可变项均在此，不写死在代码里。

**项目根**：在哪运行，哪就是 `/workspace/`。JARVIS 从 cwd 向上找 `javis.json` 确定项目根；也可设 `JARVIS_PROJECT_ROOT` 覆盖。在 `truly_Javis/` 内开发时行为与以前一致。

**新项目初始化**（任意空目录）：

```bash
python -m src.main --init e:\tmp\javis-test
# 然后双击 e:\tmp\javis-test\run-javis.cmd 启动（不要 cd 进去 python -m src.main）
```

`run-javis.cmd` 会设置 `JARVIS_PROJECT_ROOT` 并回到引擎安装目录启动。也可手动：

```bash
set JARVIS_PROJECT_ROOT=e:\tmp\javis-test
cd e:\Thomas\Python_Project\thomas-project\truly_Javis
python -m src.main
```

### 运行

```bash
# 默认：Textual TUI
python -m src.main

# 回退纯 CLI（命令 + y/n/e/a 审批）
python -m src.main --cli

# 新会话 thread
python -m src.main -n
```

---

## TUI 使用

| 操作 | 快捷键 / 方式 |
|------|----------------|
| 新会话 | `Ctrl+N` |
| 折叠/展开会话侧边栏 | `Ctrl+B` |
| 切换主题（写回 javis.json） | `Ctrl+T` |
| 取消流式输出 | `Esc` |
| 引用 workspace / vault / memories 路径 | 输入 `@` 触发补全（**workspace 优先**；`@vault/` 进知识库）；**Tab** 接受建议，**Enter** 发送 |
| 复制对话区文本 | 鼠标拖选后松开自动复制（`javis.json` → `tui.copy_on_select`，默认 true）；或 Ctrl+Insert |
| 命令建议 | 输入 `/` 或 `/his` 等前缀即弹出（无需先 `/help`） |
| 退出 | `/exit` 或 `Ctrl+C` |

**HITL 审批**（写文件 / 执行命令等）：Modal 四按钮——放行(a) / 永久放行(s) / 拒绝(d) / 编辑参数(e)。写 Inbox 时会展示 unified diff 预览。

**写边界**：JARVIS 只能写 `/vault/Inbox/` 与 `/vault/Reports/`；Vault 其它路径只读。详见 [`docs/adr/0002-inbox-only-write-and-snapshots.md`](docs/adr/0002-inbox-only-write-and-snapshots.md)。

**系统上下文**（日期 / 时间 / 城市）：启动时 system prompt 仅含**当天日期 + 星期**；问精确时间或城市时用 `execute` 读本机，不写死 `javis.json` 或 profile。详见 [`docs/adr/0003-system-context-on-demand.md`](docs/adr/0003-system-context-on-demand.md)。

---

## 会话命令

在 TUI 或 CLI 输入 `/` 开头命令（完整列表见 `/help`）：

| 命令 | 说明 |
|------|------|
| `/sessions` | 列出历史会话（过滤 `sched-*`） |
| `/doctor` | 诊断模型/配置/会话 checkpoint 是否健康 |
| `/history` | 当前会话边界点时间线（短 id 可用于回退） |
| `/replay <id>` | 从 checkpoint 重跑 |
| `/fork <id>` | 从 checkpoint 分叉新会话 |
| `/snapshot` | 手动记录项目文件 git 快照 |
| `/snapshots` | 列出文件快照 |
| `/rollback <id>` | 回退项目文件 + 还原该会话写过的 Inbox |
| `/reload-schedules` | 热重载 `schedules/*.json` |

---

## 测试与冒烟

```bash
# 单元测试（假 agent，可进 CI）
pytest tests/ -q

# CLI 真模型冒烟（手动，消耗额度，不进 CI）
python -m src.smoke_test "调研大模型行业最新动态"

# TUI 真模型冒烟
python -m src.smoke_test --tui

# TUI HITL 冒烟：自动发送「写 Inbox」用例，手动点 Permission Modal 验证 resume
python -m src.smoke_test --tui-hitl
```

### 调试与排错

**CLI 非交互测试**：不要用 `echo "你好" | python -m src.main --cli`——管道关闭后 CLI 仍会卡在 `JARVIS>` 等输入，进程不会退出，还可能占用 `checkpoints.sqlite`。若必须脚本化，请在新会话里显式退出：

```bash
(echo 你好 & echo /exit) | python -m src.main -n --cli
```

更推荐：`python -m src.smoke_test "你好"`（跑一轮即退出），或 `python -m src.main -n --cli` 手动测。

**API 400（`BadRequestError` / 空 assistant 消息）** 常见原因：

| 原因 | 处理 |
|------|------|
| opencode 端点偶发 400 | 直接重试；代码会自动 repair + 重试一次 |
| `default` 等会话 checkpoint 损坏（此前任务 mid-stream 失败） | `/delete-session` 或 `python -m src.main -n --cli` 开新会话 |
| `.env` 的 `MODEL_ID` 与套餐不一致 | 核对 go 套餐可用模型名 |

**会话隔离**：调试模型/API 问题时优先 `-n` / `--new`，避免污染 `default` 线程。定时任务线程 `sched-*` 会自动清理，勿手动删。

**LangSmith 401 警告**：未配置 LangSmith API key 时会有 tracing 报错，不影响对话；本地可设 `LANGCHAIN_TRACING_V2=false` 静音。

**快速自检**：输入 `/doctor` 查看项目根、模型、配置来源与当前会话是否 stuck；取消/Esc 后若仍异常，同 thread 再发消息会自动 `finalize_turn` 清理。

---

## 项目结构（摘要）

```
src/
  main.py          入口（默认 TUI，--cli 回退）
  agent.py         主代理组装
  commands.py      命令/会话纯逻辑（CLI + TUI 共用）
  streaming.py     流式消费 + HITL 决策
  tui.py           Textual 界面
  vault_guard.py   Inbox 写边界
  inbox_snapshots.py  Inbox 快照与 rollback 还原
  rag.py / wiki.py / tools.py  知识检索与搜索
  agent.py           主代理组装（含 session 日期注入）
  skill_paths.py     skill 三层发现（安装 / ~/.javis / 项目）
  project_paths.py   项目根 + 用户全局 ~/.javis
tests/             pytest
memory/            长期记忆（*.md，注入 system prompt；不含固定所在地）
schedules/         定时任务（每任务一 JSON）
skills/            随安装包默认 skill（用户 skill 放 ~/.javis/skills/）
docs/specs/        权威设计文档
docs/adr/          架构决策记录
```

实现状态与模块清单亦见 [`AGENTS.md`](AGENTS.md)（agent 协作约定）。

---

## 文档索引

| 文档 | 内容 |
|------|------|
| [`docs/specs/2026-08-15-javis-design.md`](docs/specs/2026-08-15-javis-design.md) | 完整设计：架构、配置、分阶段验收 |
| [`CONTEXT.md`](CONTEXT.md) | 领域术语表 |
| [`docs/adr/0001-jarvis-tui.md`](docs/adr/0001-jarvis-tui.md) | TUI 选型与交互决策 |
| [`docs/adr/0002-inbox-only-write-and-snapshots.md`](docs/adr/0002-inbox-only-write-and-snapshots.md) | Inbox 写边界与快照回退 |
| [`docs/adr/0003-system-context-on-demand.md`](docs/adr/0003-system-context-on-demand.md) | 会话日期注入 + execute 读时间/位置；结果导向主提示词 |
| [`.scratch/javis-roadmap/map.md`](.scratch/javis-roadmap/map.md) | 后续路线（01–11）决策摘要 |

---

## 开发约定

1. 动手实现前，先到 GitHub 搜索优秀开源项目参考。
2. deepagents 更新很快，先通过 langchain MCP（docs-langchain）确认最新版功能与语法再实现。
3. 复用 deepagents 原生工具（`ls/read_file/write_file/.../execute/task`），不重造轮子。
4. 可变配置进 `javis.json` 或 `schedules/`，不写死。
