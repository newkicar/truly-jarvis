"""MCP 工具加载。

从 javis.json 的 mcps.servers 读取 MCP server 配置（OpenCode 风格），
通过 langchain-mcp-adapters 加载为 LangChain BaseTool 列表，供主代理使用。

说明（langchain-mcp-adapters >= 0.3.2）：
- MultiServerMCPClient 不再支持 async context manager；
  工具内部每次调用时自动创建并销毁 session（stdio 子进程随开随关）。
- 因此这里只负责「启动时一次性加载工具」，不做长期生命周期管理；
  返回的工具列表可直接交给 create_deep_agent(tools=...) 注入主代理。
"""
import asyncio
from typing import cast

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import Connection

try:
    from langchain_core.tools import BaseTool
except ImportError:  # pragma: no cover
    BaseTool = object  # type: ignore[assignment, misc]


def _parse_server_config(raw: dict) -> Connection:
    """把 OpenCode 风格 server 配置转成 langchain-mcp-adapters connection 格式。

    local → transport stdio（command 为命令名，args 为参数列表）
    remote → transport streamable_http（url）
    """
    server_type = raw.get("type", "local")
    if server_type == "local":
        cmd = raw.get("command", [])
        if isinstance(cmd, str):
            cmd = [cmd]
        conn: Connection = {  # type: ignore[typeddict-item]
            "transport": "stdio",
            "command": cmd[0] if cmd else "python",
            "args": list(cmd[1:]),
        }
        if raw.get("env"):
            conn["env"] = dict(raw["env"])
        if raw.get("cwd"):
            conn["cwd"] = raw["cwd"]
        return conn
    if server_type == "remote":
        conn = {"transport": "streamable_http", "url": raw["url"]}
        if raw.get("headers"):
            conn["headers"] = dict(raw["headers"])
        return cast(Connection, conn)
    raise ValueError(f"未知 MCP server type: {server_type!r}（支持 local/remote）")


def _enabled_servers(mcps_config: dict) -> dict[str, dict]:
    """筛选 mcps.servers 中 enabled 的 server，返回 {name: raw_cfg}。"""
    servers = (mcps_config or {}).get("servers", {})
    if not isinstance(servers, dict):
        return {}
    return {
        name: cfg
        for name, cfg in servers.items()
        if isinstance(cfg, dict) and cfg.get("enabled", True)
    }


def load_mcp_tools(mcps_config: dict) -> list:
    """同步加载所有启用的 MCP server 工具。

    单个 server 加载失败 → 跳过并打印警告，不影响其他 server。
    mcps_config 为 javis.json 的 mcps 段（OpenCode 风格 {"servers": {...}}）。
    无配置或全部失败时返回空列表。
    """
    servers = _enabled_servers(mcps_config)
    if not servers:
        return []

    tools: list = []
    for name, raw_cfg in servers.items():
        try:
            connection = _parse_server_config(raw_cfg)
            client = MultiServerMCPClient(
                {name: connection},
                tool_name_prefix=True,
                handle_tool_errors=True,
            )
            tools.extend(asyncio.run(client.get_tools(server_name=name)))
            print(f"[MCP] 已加载 server '{name}'")
        except Exception as exc:  # noqa: BLE001
            print(f"[MCP] 跳过 server '{name}': {exc}")
    return tools