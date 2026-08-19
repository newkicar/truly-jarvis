"""system_context 与 system-context skill 脚本测试。"""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src.system_context import (
    format_system_context,
    lookup_geo_from_ip,
    make_get_system_context_tool,
    read_system_context,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _fake_geo() -> dict[str, str]:
    return {
        "ip": "1.2.3.4",
        "city": "上海",
        "region": "上海",
        "country": "中国",
        "location": "上海，中国",
        "location_source": "ip-api",
    }


def test_read_system_context_uses_clock(tmp_path):
    frozen = datetime(2026, 8, 19, 21, 30, 0)
    ctx = read_system_context(now=frozen, geo_lookup=_fake_geo)
    assert ctx["date"] == "2026-08-19"
    assert ctx["time"] == "21:30:00"
    assert ctx["weekday"] == "星期三"
    assert ctx["city"] == "上海"
    assert ctx["location"] == "上海，中国"


def test_read_system_context_skips_location_when_disabled():
    ctx = read_system_context(include_location=False)
    assert "city" not in ctx
    assert "location" not in ctx


def test_format_system_context_includes_location():
    text = format_system_context(
        {
            "datetime": "2026-08-19 21:30:00",
            "weekday": "星期三",
            "location": "上海，中国",
        }
    )
    assert "星期三" in text
    assert "上海" in text


def test_lookup_geo_from_ip_parses_success():
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": "success",
                "query": "8.8.8.8",
                "city": "Ashburn",
                "regionName": "Virginia",
                "country": "美国",
            }

    class FakeClient:
        def get(self, url):
            return FakeResp()

        def close(self):
            return None

    data = lookup_geo_from_ip(client=FakeClient())
    assert data["ip"] == "8.8.8.8"
    assert data["city"] == "Ashburn"
    assert data["location_source"] == "ip-api"
    assert "Ashburn" in data["location"]


def test_lookup_geo_from_ip_returns_empty_on_failure():
    class FakeClient:
        def get(self, url):
            raise OSError("offline")

        def close(self):
            return None

    data = lookup_geo_from_ip(client=FakeClient())
    assert data["location_source"] == "unavailable"
    assert data["city"] == ""


def test_get_system_context_tool_returns_json():
    tool = make_get_system_context_tool()
    with patch("src.system_context.lookup_geo_from_ip", _fake_geo):
        data = json.loads(tool.invoke({}))
    assert "date" in data
    assert "time" in data
    assert "weekday" in data
    assert data["city"] == "上海"


def test_read_context_script_prints_json():
    script = PROJECT_ROOT / "skills" / "system-context" / "scripts" / "read_context.py"
    env = {**dict(__import__("os").environ), "PYTHONIOENCODING": "utf-8"}
    with patch("src.system_context.lookup_geo_from_ip", _fake_geo):
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    data = json.loads(proc.stdout)
    assert "date" in data
    assert "time" in data
    assert "weekday" in data
    assert "city" in data


def test_skill_sources_use_workspace_virtual_paths(tmp_path):
    from dataclasses import replace

    from src.agent import _skill_sources

    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    cfg = replace(__import__("conftest", fromlist=["make_fake_config"]).make_fake_config(tmp_path), skills=(skills_root,))
    assert _skill_sources(cfg) == ["/workspace/skills/"]


def test_backend_loads_system_context_skill():
    """CompositeBackend + /workspace/skills/ 应能列出 system-context。"""
    from deepagents.middleware.skills import _list_skills

    from src.agent import _make_backend, _skill_sources
    from src.config import load_config

    cfg = load_config()
    backend = _make_backend(cfg)
    sources = _skill_sources(cfg)
    assert "/workspace/skills/" in sources
    names = []
    for src in sources:
        names.extend(s["name"] for s in _list_skills(backend, src))
    assert "system-context" in names


def test_build_agent_registers_skills_directory(tmp_path, monkeypatch):
    """skills/ 应映射为 /workspace/skills/ 虚拟路径传入 create_deep_agent。"""
    import src.agent as agent_mod
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from src.agent import build_agent, create_deep_agent

    class Fake(BaseChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

        @property
        def _llm_type(self):
            return "fake"

    skills_root = tmp_path / "skills"
    (skills_root / "demo-skill").mkdir(parents=True)
    (skills_root / "demo-skill" / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: demo\n---\n",
        encoding="utf-8",
    )

    from dataclasses import replace
    from conftest import make_fake_config

    cfg = replace(make_fake_config(tmp_path), skills=(skills_root,))
    captured = {}

    def spy(**kwargs):
        captured.update(kwargs)
        return create_deep_agent(**kwargs)

    monkeypatch.setattr(agent_mod, "create_deep_agent", spy)
    build_agent(cfg, model=Fake())
    assert captured.get("skills") == ["/workspace/skills/"]
