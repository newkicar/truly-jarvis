# to-silicon.md — sok 侧接入准备清单

> 生成时间：2026-09-03
> 来源：truly-jarvis 项目
> 目的：sok 项目需要完成以下修改后，jarvis 才能通过 MCP 协议接入

---

## 前置条件

truly-jarvis 侧已完成配置：
- `jarvis.json` 添加了 `mcps.servers.sok`（remote, streamable_http）
- `.env` 添加了 `SOK_API_KEY` + `SOK_SERVER_URL`
- `src/mcps.py` 支持 `${ENV_VAR}` 环境变量插值

---

## 需要修改的文件（共 3 个）

### 1. `pyproject.toml` — 添加 mcp 依赖

**问题**：`sok/server/mcp_server.py` 有 `from mcp.server.fastmcp import FastMCP`，但 pyproject.toml 未声明 mcp 依赖。

**修改**：在 `[project.optional-dependencies] server` 中添加 `mcp>=1.0`：

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8",
    "mypy>=1.8",
]
server = [
    "fastapi>=0.141",
    "uvicorn>=0.30",
    "httpx>=0.27",
    "mcp>=1.0",          # ← 新增
]
```

---

### 2. `sok/server/app.py` — 挂载 MCP 路由

**问题**：`create_app()` 没有调用 `mount_mcp()` 或 `mount_employee_routes()`，服务启动后 `/mcp` 端点不可用。

**修改**：扩展 `create_app()` 签名，可选挂载 MCP + 员工路由：

```python
"""FastAPI 应用工厂（Plugin）。

用法：
    import uvicorn
    uvicorn.run("sok.server.app:create_app", factory=True)

MES 看板路由由 sok.server.mes_routes.mount_mes 显式挂载（保持工厂与内核解耦）。
MCP Server 由 mount_mcp 显式挂载（需要 auth_config）。
"""

from __future__ import annotations

from fastapi import FastAPI

from sok.memory import InMemoryMemory, Memory

from .auth import AuthConfig
from .routes import router

APP_TITLE = "Silicon Organization Kernel"
APP_VERSION = "0.1.0"


def create_app(
    memory: Memory | None = None,
    auth_config: AuthConfig | None = None,
    mount_mcp_routes: bool = False,
) -> FastAPI:
    """应用工厂：memory 缺省时创建进程内共享记忆（状态/审计端点查询用）。

    Args:
        memory: Memory 实例（缺省用 InMemoryMemory）
        auth_config: 认证配置（mount_mcp_routes=True 时必须提供）
        mount_mcp_routes: 是否挂载 MCP Server + 员工任务路由
    """
    if memory is None:
        memory = InMemoryMemory()
    app = FastAPI(title=APP_TITLE, version=APP_VERSION)
    app.state.memory = memory
    app.include_router(router)

    if mount_mcp_routes:
        if auth_config is None:
            raise ValueError("mount_mcp_routes=True 需要提供 auth_config")
        from .employee_routes import mount_employee_routes
        from .mcp_server import mount_mcp

        app.state.auth_config = auth_config
        mount_employee_routes(app)
        mount_mcp(app, memory, auth_config)

    return app
```

---

### 3. `demo/run_server.py` — 启动时挂载 MCP

**问题**：启动脚本没有调用 `mount_mcp()` 和 `mount_employee_routes()`。

**修改**：导入 auth 配置，传入 `create_app()`：

```python
#!/usr/bin/env python
"""HTTP 服务启动脚本：uvicorn 承载 Silicon Organization Kernel。

默认挂载 MES 看板（/dashboard、/mes/*）、员工任务路由（/employee/*）、
MCP Server（/mcp）并启动 30 分钟整点快照刷新。

用法：
  python demo/run_server.py                    # 默认 127.0.0.1:8000
  python demo/run_server.py --host 0.0.0.0 --port 9000
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# 保证从项目根运行时可导入 sok
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402
from sok.server.app import create_app  # noqa: E402
from sok.server.auth import load_auth_config  # noqa: E402
from sok.server.mes_routes import mount_mes  # noqa: E402
from sok.server.scheduler import start_snapshot_scheduler  # noqa: E402


def _load_auth_from_env() -> dict[str, str]:
    """从环境变量加载 API Key 映射。

    支持 SOK_API_KEYS 环境变量，格式：sk-xxx=110430,sk-yyy=210532
    """
    raw = os.environ.get("SOK_API_KEYS", "")
    if not raw:
        return {}
    mapping = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if "=" in pair:
            key, person_id = pair.split("=", 1)
            mapping[key.strip()] = person_id.strip()
    return mapping


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 Silicon Organization Kernel HTTP 服务")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8000, help="监听端口（默认 8000）")
    parser.add_argument("--no-mcp", action="store_true", help="禁用 MCP Server（默认启用）")
    args = parser.parse_args()

    auth_config = load_auth_config(_load_auth_from_env())

    app = create_app(
        auth_config=auth_config,
        mount_mcp_routes=not args.no_mcp,
    )
    mount_mes(app)
    start_snapshot_scheduler(app)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
```

---

## API Key 配置

sok 侧需要配置 API Key → Person ID 映射。两种方式：

### 方式 A：环境变量（推荐）

```bash
export SOK_API_KEYS="sk-jarvis-agent=110430,sk-another-agent=210532"
```

### 方式 B：代码硬编码（临时）

在 `demo/run_server.py` 中直接构造：

```python
auth_config = load_auth_config({"sk-jarvis-agent": "110430"})
```

---

## 验证步骤

1. 安装依赖：
   ```bash
   pip install -e ".[server]"
   ```

2. 配置 API Key：
   ```bash
   export SOK_API_KEYS="sk-jarvis-agent=110430"
   ```

3. 启动服务：
   ```bash
   python demo/run_server.py
   ```

4. 测试 MCP 端点：
   ```bash
   curl http://127.0.0.1:8000/mcp
   # 应返回 MCP 协议响应（非 404）
   ```

5. 测试员工路由：
   ```bash
   curl -H "Authorization: Bearer sk-jarvis-agent" http://127.0.0.1:8000/employee/tasks
   # 应返回 {"tasks": [], "total": 0}
   ```

---

## MCP 工具清单（13 个）

jarvis 接入后可调用的工具：

| 分组 | 工具 | 功能 |
|------|------|------|
| 组织状态 | `query_resource_state` | 查资源最新状态 |
| | `query_resource_history` | 资源状态变更时间线 |
| | `query_audit_log` | 审计日志 |
| 知识检索 | `search_knowledge` | 关键词搜索知识库 |
| | `get_knowledge` | 按 ID 获取知识条目 |
| 场景/决策 | `trigger_scenario` | 触发黄金场景 |
| | `query_decision` | 查决策审计记录 |
| | `accept_decision` | 接受决策 |
| | `reject_decision` | 拒绝决策 |
| 员工任务 | `get_my_tasks` | 拉取 pending 任务 |
| | `claim_task` | 认领任务 |
| | `complete_task` | 完成任务 |
| | `report_to_brain` | 向大脑发送信息 |

---

## 注意事项

- MCP 传输方式：`streamable_http`（非 stdio）
- 认证方式：每个工具接受 `api_key: str = ""` 参数，或通过 HTTP Header `Authorization: Bearer <key>`
- EmployeeTask 状态机：pending → claimed → done（可 fail/retry/escalate）
- 超时：pending 30 分钟 → escalated；claimed 120 分钟 → 回退 pending
