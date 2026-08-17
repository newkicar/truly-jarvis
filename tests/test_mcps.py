"""MCP 工具加载测试。

Seam: src.mcps 的公开接口 load_mcp_tools / _parse_server_config / _enabled_servers。
mock MultiServerMCPClient 避免真实连接，验证配置解析、enabled 过滤、失败跳过。
"""
import pytest

from src.mcps import _enabled_servers, _parse_server_config, load_mcp_tools


class TestParseServerConfig:
    def test_local_with_list_command(self):
        conn = _parse_server_config({"type": "local", "command": ["uvx", "mcp-server-git"]})
        assert conn["transport"] == "stdio"
        assert conn["command"] == "uvx"
        assert conn["args"] == ["mcp-server-git"]

    def test_local_with_string_command(self):
        conn = _parse_server_config({"type": "local", "command": "python"})
        assert conn["transport"] == "stdio"
        assert conn["command"] == "python"
        assert conn["args"] == []

    def test_local_defaults_type(self):
        conn = _parse_server_config({"command": ["python", "server.py"]})
        assert conn["transport"] == "stdio"

    def test_local_with_env(self):
        conn = _parse_server_config(
            {"type": "local", "command": ["node", "server.js"], "env": {"KEY": "VAL"}}
        )
        assert conn.get("env") == {"KEY": "VAL"}

    def test_remote(self):
        conn = _parse_server_config({"type": "remote", "url": "http://localhost:8000/mcp"})
        assert conn["transport"] == "streamable_http"
        assert conn["url"] == "http://localhost:8000/mcp"

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError):
            _parse_server_config({"type": "nope", "url": "x"})


class TestEnabledServers:
    def test_filters_disabled(self):
        servers = _enabled_servers(
            {
                "servers": {
                    "a": {"type": "local", "command": ["x"], "enabled": True},
                    "b": {"type": "local", "command": ["x"], "enabled": False},
                    "c": {"type": "local", "command": ["x"]},
                }
            }
        )
        assert set(servers.keys()) == {"a", "c"}

    def test_empty_config(self):
        assert _enabled_servers({}) == {}
        assert _enabled_servers(None) == {}  # type: ignore[arg-type]

    def test_non_dict_servers(self):
        assert _enabled_servers({"servers": []}) == {}


class TestLoadMcpTools:
    def test_no_servers_returns_empty(self):
        assert load_mcp_tools({}) == []
        assert load_mcp_tools({"servers": {}}) == []

    def test_failed_server_skipped_with_warning(self, monkeypatch, capsys):
        """单个 server 连接失败 → 跳过并警告，不抛错。"""
        import src.mcps as mcps_mod

        captured = []

        def fake_get_tools(self, server_name=None):
            name = list(self.connections.keys())[0]
            captured.append(name)
            if name == "broken":
                raise RuntimeError("connection refused")
            return ["tool_ok"]

        monkeypatch.setattr(mcps_mod.MultiServerMCPClient, "get_tools", fake_get_tools)
        monkeypatch.setattr(mcps_mod.asyncio, "run", lambda coro: coro)

        config = {
            "servers": {
                "broken": {"type": "local", "command": ["python", "s.py"]},
                "good": {"type": "local", "command": ["python", "s.py"]},
            }
        }
        tools = load_mcp_tools(config)
        assert tools == ["tool_ok"]
        assert captured == ["broken", "good"]
        err = capsys.readouterr().out
        assert "跳过 server 'broken'" in err

    def test_all_disabled_returns_empty(self, monkeypatch):
        config = {"servers": {"a": {"type": "local", "command": ["x"], "enabled": False}}}
        assert load_mcp_tools(config) == []