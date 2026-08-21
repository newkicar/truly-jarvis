"""system_context_enforcer 测试。"""
from datetime import datetime

from langchain_core.messages import AIMessage, HumanMessage

from src.system_context_enforcer import (
    SystemContextEnforcerMiddleware,
    SystemContextIntent,
    build_system_context_answer,
    classify_system_context,
    format_date_answer,
    wrong_tool_message,
)


class _Req:
    def __init__(self, name: str, args: dict, state: dict | None = None):
        self.tool_call = {"name": name, "args": args, "id": "tc1"}
        self.state = state or {}


def test_classify_date_questions():
    assert classify_system_context("今天几号").date
    assert classify_system_context("今天星期几").date
    assert classify_system_context("今天").date
    assert not classify_system_context("今天调研国产大模型").date


def test_classify_time_questions():
    assert classify_system_context("现在几点").time
    assert classify_system_context("几点了").time
    assert not classify_system_context("今天下午几点开会").time


def test_classify_location_questions():
    assert classify_system_context("我在哪").location
    assert classify_system_context("什么城市").location


def test_classify_combined():
    intent = classify_system_context("现在几点，我在哪")
    assert intent.time and intent.location


def test_format_date_answer():
    text = format_date_answer(now=datetime(2026, 8, 20, 12, 0, 0))
    assert text == "今天是 2026-08-20，星期四。"


def test_build_answer_date_only():
    answer = build_system_context_answer(
        SystemContextIntent(date=True),
        now=datetime(2026, 8, 20, 12, 0, 0),
    )
    assert answer == "今天是 2026-08-20，星期四。"


def test_build_answer_time_and_location():
    answer = build_system_context_answer(
        SystemContextIntent(time=True, location=True),
        time_fetcher=lambda: "2026-08-20 20:30:00 (China Standard Time)",
        location_fetcher=lambda: "北京，北京市，中国",
    )
    assert "当前本机时间" in answer
    assert "北京" in answer


def test_before_model_short_circuits_date_only():
    mw = SystemContextEnforcerMiddleware()
    state = {"messages": [HumanMessage(content="今天几号")]}
    result = mw.before_model(state, runtime=None)
    assert result is not None
    assert result["jump_to"] == "end"
    assert isinstance(result["messages"][0], AIMessage)
    assert "2026" in result["messages"][0].content or "星期" in result["messages"][0].content


def test_before_model_time_not_short_circuited():
    mw = SystemContextEnforcerMiddleware()
    state = {"messages": [HumanMessage(content="现在几点")]}
    assert mw.before_model(state, runtime=None) is None


def test_before_model_location_not_short_circuited():
    mw = SystemContextEnforcerMiddleware()
    state = {"messages": [HumanMessage(content="我在哪")]}
    assert mw.before_model(state, runtime=None) is None


def test_before_model_skips_complex():
    mw = SystemContextEnforcerMiddleware()
    state = {"messages": [HumanMessage(content="今天调研 AI 进展")]}
    assert mw.before_model(state, runtime=None) is None


def test_blocks_eval_on_time_question():
    mw = SystemContextEnforcerMiddleware()
    req = _Req("eval", {"code": "new Date()"}, state={"messages": [HumanMessage("现在几点")]})
    msg = mw.wrap_tool_call(req, handler=lambda r: None)
    assert msg.status == "error"
    assert "禁止 eval" in msg.content


def test_blocks_task_researcher_on_location():
    mw = SystemContextEnforcerMiddleware()
    req = _Req(
        "task",
        {"subagent_type": "researcher", "description": "查城市"},
        state={"messages": [HumanMessage("我在哪")]},
    )
    msg = mw.wrap_tool_call(req, handler=lambda r: None)
    assert msg.status == "error"
    assert "researcher" not in msg.content.lower() or "禁止 task" in msg.content


def test_wrong_tool_message_mentions_execute():
    text = wrong_tool_message("eval", SystemContextIntent(time=True))
    assert "Get-Date" in text
