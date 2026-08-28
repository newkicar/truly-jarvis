---
name: jarvis-self-help
description: "JARVIS 自身配置与使用帮助：当用户询问如何调整 JARVIS 配置、使用某个功能、解决运行问题、或想了解 JARVIS 支持什么能力时触发。包括：jarvis.json 字段含义、TUI 快捷键、会话命令、权限配置、MCP 接入、定时任务、记忆管理等。"
---

# JARVIS 自身配置与使用指导

> 本文档是 JARVIS 的「自传」，供 agent 在用户询问配置/用法时 read_file 读取后回答。

---

## 一、配置文件 `jarvis.json` 全字段速查

`jarvis.json` 放在项目根目录（与 `.env` 同级），首次运行自动创建。

```json
{
  "model": {
    "base_url_env": "BASE_URL",
    "api_key_env": "API_KEY",
    "model_id_env": "MODEL_ID"
  },
  "knowledge_base": "",
  "memory_dir": "memory",
  "checkpoint_db": "checkpoints/checkpoints.sqlite",
  "skills": ["skills/"],
  "schedules_dir": "schedules",
  "mcps": { "servers": {} },
  "permissions": {},
  "hooks": { "permission": [] },
  "rag": {
    "ollama_base_url": "http://localhost:11434",
    "embed_model": "quentinz/bge-small-zh-v1.5"
  },
  "execution": { "max_steps": 200 },
  "tui": { "copy_on_select": true },
  "theme": "flexoki"
}
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `model.base_url_env` | string | `"BASE_URL"` | 对应 `.env` 中的模型端点变量名 |
| `model.api_key_env` | string | `"API_KEY"` | 对应 `.env` 中的 API key 变量名 |
| `model.model_id_env` | string | `"MODEL_ID"` | 对应 `.env` 中的模型 ID 变量名 |
| `knowledge_base` | string | `""` | Obsidian vault 绝对路径；留空或删除 = 无 `/vault/` |
| `memory_dir` | string | `"memory"` | 用户记忆目录（相对项目根） |
| `checkpoint_db` | string | `"checkpoints/checkpoints.sqlite"` | 会话 checkpoint 数据库路径（相对项目根） |
| `skills` | array | `["skills/"]` | 项目级 skill 目录列表 |
| `schedules_dir` | string | `"schedules"` | 定时任务 JSON 目录（相对项目根） |
| `mcps.servers` | object | `{}` | MCP 服务器配置（见下方） |
| `permissions` | object | `{}` | 工具审批规则（见下方） |
| `hooks.permission` | array | `[]` | 审批前外部命令钩子 |
| `rag.ollama_base_url` | string | `"http://localhost:11434"` | Ollama 服务地址（RAG embedding） |
| `rag.embed_model` | string | `"quentinz/bge-small-zh-v1.5"` | embedding 模型名 |
| `execution.max_steps` | int | `200` | 单轮最大工具调用步数（10–9999） |
| `tui.copy_on_select` | bool | `true` | 鼠标拖选松开自动复制到剪贴板 |
| `theme` | string | `"flexoki"` | Textual TUI 主题（Ctrl+T 切换，20+ 可选） |

**全局合并**：`~/.jarvis/jarvis.json`（用户全局配置）与项目级 jarvis.json 深度合并，项目覆盖全局。

---

## 二、`.env` 环境变量

```dotenv
BASE_URL=https://your-model-endpoint/v1
API_KEY=sk-your-key
MODEL_ID=your-model-id
TAVILY_KEY=tvly-your-key
```

| 变量 | 必填 | 说明 |
|------|------|------|
| `BASE_URL` | ✓ | OpenAI 兼容 API 端点 |
| `API_KEY` | ✓ | API 密钥 |
| `MODEL_ID` | ✓ | 模型名（如 `mimo-v2.5`） |
| `TAVILY_KEY` | 可选 | Tavily 联网搜索 API key |

格式：`KEY:VALUE` 或 `KEY=VALUE`，键名大小写不敏感。

---

## 三、TUI 快捷键

| 操作 | 快捷键 |
|------|--------|
| 新会话 | `Ctrl+N` |
| 折叠/展开会话侧边栏 | `Ctrl+B` |
| 切换主题 | `Ctrl+T` |
| 取消流式输出 | `Esc` |
| Plan/Act 模式切换 | `Tab`（补全不活跃时）/ `Shift+Tab` |
| 路径补全 | 输入 `@` 触发，Tab 接受，Enter 发送 |
| 命令建议 | 输入 `/` 触发 |
| 退出 | `/exit` 或 `Ctrl+C` |
| 粘贴 | `Ctrl+V` / 右键 / 中键 |

---

## 四、会话命令速查

| 命令 | 说明 |
|------|------|
| `/help` | 显示所有命令 |
| `/sessions` | 列出历史会话（过滤定时任务线程） |
| `/history` | 当前会话边界点时间线（短 id 可回退） |
| `/replay <id>` | 从指定 checkpoint 重跑 |
| `/fork <id>` | 从指定 checkpoint 分叉新会话 |
| `/snapshot` | 手动记录项目文件 git 快照 |
| `/snapshots` | 列出文件快照 |
| `/rollback <id>` | 回退项目文件 + 还原该会话写过的 Inbox |
| `/reload-schedules` | 热重载 `schedules/*.json`（无需重启） |
| `/doctor` | 诊断模型/配置/会话健康状态 |
| `/delete-session` | 删除当前会话 checkpoint |

---

## 五、权限配置（HITL）

### jarvis.json `permissions` 段

```json
{
  "permissions": {
    "*": "ask",
    "execute": "allow",
    "write_file": "ask",
    "git push*": "deny"
  }
}
```

| 值 | 行为 |
|----|------|
| `"allow"` | 自动放行，不弹审批 |
| `"ask"` | 每次弹 Modal 审批（默认） |
| `"deny"` | 拒绝执行 |

规则按最后匹配胜出。支持通配符（`"git push*"`）。

### 永久放行

审批 Modal 选「永久放行(s)」→ 修改 jarvis.json 并写回，无需重启。

### Hooks（审批前钩子）

```json
{
  "hooks": {
    "permission": [
      {
        "match": "execute:git push*",
        "command": ["python", "hooks/permission_example.py"]
      }
    ]
  }
}
```

Hook 收到 JSON（tool/args/path/thread_id），返回 `{"decision":"allow"|"deny"|"ask"}`。

---

## 六、MCP 服务器接入

```json
{
  "mcps": {
    "servers": {
      "my-server": {
        "type": "local",
        "command": ["npx", "-y", "@my/mcp-server"],
        "env": { "API_KEY": "..." }
      },
      "remote-server": {
        "type": "remote",
        "url": "http://localhost:3000/mcp"
      }
    }
  }
}
```

| 字段 | 说明 |
|------|------|
| `type` | `"local"`（stdio）/ `"remote"`（streamable_http） |
| `command` | local 类型的启动命令数组 |
| `url` | remote 类型的 URL |
| `env` | 可选，环境变量 |
| `headers` | 可选，HTTP 头（remote 类型） |
| `cwd` | 可选，工作目录（local 类型） |
| `enabled` | 可选，`false` 禁用单个 server |

工具名自动加 server 前缀（如 `git_get_file`）。需重启生效。

---

## 七、定时任务（Schedules）

每任务一个 JSON 文件，放在 `schedules/` 目录：

```json
{
  "id": "tech-daily",
  "enabled": true,
  "cron": "0 8 * * *",
  "task": "调研国内 AI 大模型行业最新动态",
  "save_path": "vault:Inbox/",
  "requirements": "重点关注模型发布、融资、政策、商业化。"
}
```

| 字段 | 说明 |
|------|------|
| `id` | 唯一标识 |
| `enabled` | `false` 则跳过 |
| `cron` | 5 位 cron 表达式（分 时 日 月 周） |
| `task` | 任务描述（发给 agent） |
| `save_path` | 结果保存路径（`vault:Inbox/` / `vault:Reports/`） |
| `requirements` | 可选，任务补充要求 |

**注意**：进程内调度，jarvis 运行期间才触发。`/reload-schedules` 热重载。`*.example.json` 文件自动跳过。

---

## 八、记忆管理

| 目录 | 用途 | 注入方式 |
|------|------|----------|
| `memory/*.md` | 用户偏好/职业/行业信息 | 启动时注入 system prompt |
| `vault/` | Obsidian 知识库（可选） | `/vault/` 路由，工具读写 |

记忆文件是普通 `.md`，用户可直接编辑。`README.md` 不注入。

---

## 九、常见调整场景

### 换模型

修改 `.env` 的 `MODEL_ID`，重启 jarvis。无需改 `jarvis.json`。

### 加定时任务

在 `schedules/` 新建 JSON 文件，格式见第七节。`/reload-schedules` 热重载。

### 加 MCP server

在 `jarvis.json` 的 `mcps.servers` 加配置，重启 jarvis。

### 加自定义子代理

在 `jarvis.json` 的 `agents` 段添加：

```json
{
  "agents": {
    "my-agent": {
      "description": "专门做 X 的子代理",
      "system_prompt": "你是..."
    }
  }
}
```

### 关闭某个工具审批

在 `jarvis.json` 的 `permissions` 段设置对应工具为 `"allow"`。

---

## 十、故障排查

| 问题 | 原因 | 解决 |
|------|------|------|
| API 400 / BadRequestError | 模型端点偶发 / checkpoint 损坏 / MODEL_ID 不对 | 重试；`/doctor` 诊断；`-n` 开新会话核对 MODEL_ID |
| 会话卡住不动 | 步数上限 / GraphRecursionError | `/doctor` 查看；`-n` 开新会话 |
| Ollama 不可用 | 未安装或未启动 Ollama | RAG 自动回落，不影响对话；安装后 `localhost:11434` |
| `Ctrl+V` 粘贴无效 | Textual 默认剪贴板不读系统 | 已内置 PasteInput 修复，检查 `jarvis.json` 无 `tui.clipboard` 覆盖 |
| bash 管道静默退出 | 管道环境下长任务流式偶发 | 用 `-n --cli` 显式退出；`python -m src.smoke_test` 替代 |
| 定时任务不触发 | jarvis 未运行 / cron 表达式错误 | 确认 jarvis 在跑；`/reload-schedules` 检查日志 |
| `/vault/` 不可用 | `knowledge_base` 未配置 | `jarvis.json` 填 Obsidian vault 路径；留空 = 无知识库 |
| 写文件被拒 | Plan 模式拦截 / 权限 deny | 切到 Act 模式（Tab）；检查 `permissions` 配置 |

**快速自检**：输入 `/doctor` 查看项目根、模型、permission hooks、当前会话状态。
