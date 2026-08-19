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
| 引用 vault/workspace 路径 | 输入 `@` 触发补全（Inbox 优先） |
| 退出 | `/exit` 或 `Ctrl+C` |

**HITL 审批**（写文件 / 执行命令等）：Modal 四按钮——放行(a) / 永久放行(s) / 拒绝(d) / 编辑参数(e)。写 Inbox 时会展示 unified diff 预览。

**写边界**：JARVIS 只能写 `/vault/Inbox/` 与 `/vault/Reports/`；Vault 其它路径只读。详见 [`docs/adr/0002-inbox-only-write-and-snapshots.md`](docs/adr/0002-inbox-only-write-and-snapshots.md)。

---

## 会话命令

在 TUI 或 CLI 输入 `/` 开头命令（完整列表见 `/help`）：

| 命令 | 说明 |
|------|------|
| `/sessions` | 列出历史会话（过滤 `sched-*`） |
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
# 单元测试（假 agent，可进 CI）——当前 165
pytest tests/ -q

# CLI 真模型冒烟（手动，消耗额度，不进 CI）
python -m src.smoke_test "调研大模型行业最新动态"

# TUI 真模型冒烟
python -m src.smoke_test --tui

# TUI HITL 冒烟：自动发送「写 Inbox」用例，手动点 Permission Modal 验证 resume
python -m src.smoke_test --tui-hitl
```

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
tests/             pytest
memory/            长期记忆（*.md，注入 system prompt）
schedules/         定时任务（每任务一 JSON）
skills/            Agent skills（SKILL.md）
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
| [`.scratch/javis-roadmap/map.md`](.scratch/javis-roadmap/map.md) | 后续路线（01–11）决策摘要 |

---

## 开发约定

1. 动手实现前，先到 GitHub 搜索优秀开源项目参考。
2. deepagents 更新很快，先通过 langchain MCP（docs-langchain）确认最新版功能与语法再实现。
3. 复用 deepagents 原生工具（`ls/read_file/write_file/.../execute/task`），不重造轮子。
4. 可变配置进 `javis.json` 或 `schedules/`，不写死。
