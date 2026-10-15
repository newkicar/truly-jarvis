"""JarvisSkillsMiddleware 单测（#08：manual-only skill 不进模型上下文）。"""
from dataclasses import dataclass, replace

from langchain_core.messages import SystemMessage

from src.jarvis_skills import JarvisSkillsMiddleware


@dataclass
class _FakeRequest:
    """鸭子模型 ModelRequest：只覆盖 modify_request 的消耗面（state / system_message / override）。"""

    state: dict
    system_message: object | None

    def override(self, **kwargs):
        return replace(self, **kwargs)


def _meta(name: str) -> dict:
    return {
        "name": name,
        "description": f"desc {name}",
        "path": f"/skills/{name}/SKILL.md",
        "metadata": {},
        "license": None,
        "compatibility": None,
        "allowed_tools": [],
    }


def _text_of(system_message) -> str:
    content = system_message.content
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict))


def test_manual_only_skills_excluded_from_model_context():
    mw = JarvisSkillsMiddleware(
        backend=object(), sources=["/skills/"], flagged={"manual-x"}
    )
    req = _FakeRequest(
        state={"skills_metadata": [_meta("plain-skill"), _meta("manual-x")], "skills_load_errors": []},
        system_message=SystemMessage(content="基础系统提示"),
    )
    out = mw.modify_request(req)
    text = _text_of(out.system_message)
    assert "plain-skill" in text
    assert "manual-x" not in text
    assert "基础系统提示" in text


def test_no_flagged_skills_delegates_to_base_behavior():
    mw = JarvisSkillsMiddleware(backend=object(), sources=["/skills/"], flagged=set())
    req = _FakeRequest(
        state={"skills_metadata": [_meta("a-skill"), _meta("b-skill")]},
        system_message=None,
    )
    out = mw.modify_request(req)
    text = _text_of(out.system_message)
    assert "a-skill" in text and "b-skill" in text


def test_flagged_names_case_insensitive():
    mw = JarvisSkillsMiddleware(backend=object(), sources=["/skills/"], flagged={"MANUAL-X"})
    req = _FakeRequest(
        state={"skills_metadata": [_meta("manual-x"), _meta("plain")]},
        system_message=None,
    )
    text = _text_of(mw.modify_request(req).system_message)
    assert "manual-x" not in text
    assert "plain" in text
