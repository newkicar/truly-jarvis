# to-jarvis.md — truly-jarvis 接入硅基组织内核指南

> 本文档描述如何让 truly-jarvis 接入 sok 内核（大脑），实现员工 Agent 与大脑的双向通信。
> 将此文件剪切到 truly-jarvis 项目中，让那里的代理帮忙修改代码。

---

## 一、接入概述

truly-jarvis 通过 MCP 协议接入 sok 内核，实现：
- **Agent → Brain**（jarvis 调 sok）：查询组织状态、知识库、审批决策
- **Brain → Agent**（sok 派任务给 jarvis）：拉取待办任务、认领、汇报结果

两个项目保持独立，通过 HTTP MCP 协议对接。

## 二、jarvis 侧需要做的事

### 1. 修改 `jarvis.json`，添加 MCP Server 配置

在 `jarvis.json` 的 `mcps.servers` 中添加 sok 服务：

```jsonc
{
  "mcps": {
    "servers": {
      "sok": {
        "type": "remote",
        "url": "http://10.x.x.x:8000/mcp",
        "enabled": true
      }
    }
  }
}
```

其中 `10.x.x.x:8000` 替换为 sok 服务器的实际地址和端口。

### 2. 添加员工任务拉取定时任务

在 `schedules/` 目录下创建 `pull-sok-tasks.json`：

```jsonc
{
  "id": "sok-pull-tasks",
  "enabled": true,
  "cron": "*/30 * * * * *",
  "task": "检查 sok 内核是否有新的待办任务。调用 get_my_tasks 工具获取任务列表，按优先级处理每个任务。",
  "save_path": "vault:Inbox/"
}
```

### 3. 配置 API Key

在 `.env` 或环境变量中设置：

```ini
SOK_API_KEY=sk-your-api-key-here
SOK_SERVER_URL=http://10.x.x.x:8000
```

API Key 由 sok 侧的管理员配置（见 `sok/server/auth.py` 的 `API_KEY_TO_PERSON` 映射表）。

### 4. jarvis Agent 的 MCP 工具使用

jarvis 的 agent 通过 MCP 协议自动获得以下工具：

#### 组织状态查询
- `query_resource_state(resource_id, api_key)` → 资源最新状态
- `query_resource_history(resource_id, api_key)` → 资源状态变更时间线
- `query_audit_log(target_id, api_key)` → 审计日志

#### 知识检索
- `search_knowledge(query, type, api_key)` → 搜索知识库
- `get_knowledge(knowledge_id, api_key)` → 获取知识条目

#### 场景/决策交互
- `trigger_scenario(scenario_type, use_mock_llm, api_key)` → 触发黄金场景
- `query_decision(decision_id, api_key)` → 查决策详情
- `accept_decision(decision_id, api_key)` → 接受决策
- `reject_decision(decision_id, reason, api_key)` → 拒绝决策

#### 员工任务队列
- `get_my_tasks(api_key)` → 拉取 pending 任务
- `claim_task(task_id, api_key)` → 认领任务
- `complete_task(task_id, summary, api_key)` → 完成任务
- `report_to_brain(message, context, api_key)` → 向大脑发送信息

## 三、sok 侧已实现的模块

### 新增模块
| 模块 | 职责 |
|------|------|
| `sok/objects/employee.py` | EmployeeTask 对象（Plugin，状态机） |
| `sok/server/auth.py` | API Key → Person ID 认证 |
| `sok/server/mcp_server.py` | MCP Server（暴露工具给 jarvis） |
| `sok/server/employee_routes.py` | 员工任务 HTTP 端点 |
| `sok/server/permissions.py` | 组织树权限过滤 |
| `sok/memory/base.py` | Memory ABC 扩展（EmployeeTask 方法） |

### 新增测试文件
| 文件 | 覆盖 |
|------|------|
| `tests/test_employee_task.py` | EmployeeTask 对象状态机 |
| `tests/test_employee_auth.py` | API Key 认证 |
| `tests/test_employee_task_storage.py` | Memory 存储扩展 |
| `tests/test_mcp_tools.py` | MCP 工具函数 |
| `tests/test_employee_permissions.py` | 组织树权限 |
| `tests/test_employee_routes.py` | HTTP 端点 |
| `tests/test_employee_task_timeout.py` | 超时扫描 |

## 四、通信协议详情

### MCP 协议（Agent → Brain）

传输方式：HTTP（`streamable_http` transport）
端点：`http://10.x.x.x:8000/mcp`
认证：每个 MCP 工具调用时传入 `api_key` 参数

### HTTP 轮询（Brain → Agent）

端点：
- `GET /employee/tasks` → 拉取 pending 任务
- `POST /employee/tasks/{id}/claim` → 认领任务
- `POST /employee/tasks/{id}/complete` → 完成任务
- `POST /employee/report` → 向大脑发送信息

认证：`Authorization: Bearer <api_key>` header

### EmployeeTask 状态机

```
pending → claimed → done
pending → claimed → failed
pending → escalated（认领超时，默认 30 分钟）
claimed → pending（执行超时，默认 120 分钟）
```

## 五、启动方式

### 启动 sok 服务

```bash
cd "D:\Python Project\silicon_organization_kernel"
pip install -e ".[server]"
python demo/run_server.py  # 默认 127.0.0.1:8000
```

### 启动 jarvis 并接入

```bash
cd "D:\Python Project\truly-jarvis-main"
# 确保 jarvis.json 已配置 MCP Server
jarvis  # 或 python -m jarvis
```

## 六、验证接入

1. 启动 sok 服务
2. 启动 jarvis
3. 在 jarvis 中询问："查询设备 A-023 的状态"
4. jarvis 应通过 MCP 调用 sok 的 `query_resource_state` 工具
5. 返回设备状态信息

## 七、注意事项

1. **API Key 管理**：sok 侧的 `auth.py` 中的映射表需要管理员维护
2. **离线队列**：jarvis 不在线时，sok 的任务在队列中积压，上线后自动拉取
3. **权限隔离**：普通员工只看自己的数据，管理者看下属数据（基于 OrgUnit 树）
4. **超时处理**：pending 超时 30 分钟 → escalated；claimed 超时 120 分钟 → 回退 pending
5. **mcp 包版本**：sok 使用 `mcp>=1.25.0`，确保 jarvis 侧版本兼容
