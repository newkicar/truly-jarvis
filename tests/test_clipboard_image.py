"""#03 剪贴板图片粘贴（clipboard_image 纯函数 + run_agent_turn 多模态 auto 回落）。"""
import base64
import os

import pytest

from src.clipboard_image import (
    build_multimodal_content,
    image_fallback_text,
    image_to_data_url,
    looks_like_image_path,
)
from src.streaming import run_agent_turn


def test_looks_like_image_path(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"x")
    assert looks_like_image_path(str(img)) == os.path.abspath(str(img))
    assert looks_like_image_path(str(tmp_path / "no.png")) is None
    assert looks_like_image_path(str(img) + " extra") is None
    assert looks_like_image_path("C:\\x\\y.txt") is None


def test_looks_like_image_path_allows_spaces_in_dirs(tmp_path):
    """GUI 工单 07 修：路径含空格（Windows 目录名常态，如 D:\\Python Project\\…）应识别。"""
    sub = tmp_path / "My Photos"
    sub.mkdir()
    pic = sub / "pic.png"
    pic.write_bytes(b"\x89PNG")
    assert looks_like_image_path(str(pic)) == os.path.abspath(str(pic))
    # 多行文本 / 无扩展名 / 不存在 仍拒
    assert looks_like_image_path("first line\nsecond.png") is None
    assert looks_like_image_path(str(pic) + " tail") is None
    assert looks_like_image_path(str(sub / "gone.png")) is None


def test_image_to_data_url(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG")
    url = image_to_data_url(str(img))
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == b"\x89PNG"
    assert image_to_data_url(str(tmp_path / "gone.png")) is None


def test_build_multimodal_content_parts(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"123")
    parts = build_multimodal_content("前文 [Image #1] 后文", {1: str(img)})
    assert parts[0] == {"type": "text", "text": "前文"}
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert parts[2] == {"type": "text", "text": "后文"}


def test_build_multimodal_missing_attachment_keeps_placeholder():
    parts = build_multimodal_content("x [Image #2]", {1: "/tmp/a.png"})
    assert {"type": "text", "text": "[Image #2]"} in parts


def test_build_multimodal_over_limit(tmp_path):
    big = tmp_path / "big.png"
    big.write_bytes(b"0" * (4 * 1024 * 1024 + 1))
    parts = build_multimodal_content("[Image #1]", {1: str(big)})
    assert len(parts) == 1
    assert parts[0]["type"] == "text"
    assert "超过 4MB" in parts[0]["text"]


def test_build_multimodal_read_failure():
    parts = build_multimodal_content("[Image #1]", {1: "/tmp/gone.png"}, data_url_fn=lambda p: None)
    assert len(parts) == 1
    assert "读取失败" in parts[0]["text"]


def test_image_fallback_text():
    text = "看 [Image #1] 和 [Image #2]"
    assert image_fallback_text(text, {1: "C:\\a.png", 2: "C:\\b.png"}) == (
        "看 图片 #1 路径: C:\\a.png 和 图片 #2 路径: C:\\b.png"
    )
    assert image_fallback_text("x [Image #9]", {}) == "x [Image #9]"


class _FakeStream:
    def __init__(self):
        self.output = None
        self.interrupted = False
        self.interrupts = None

    def interleave(self, *args):
        return iter(())


class _FakeImageAgent:
    """list content 抛 image 类错误；str content 成功。"""

    def __init__(self):
        self.inputs = []

    def stream_events(self, payload, *, version, config, control=None):
        self.inputs.append(payload)
        content = payload["messages"][0]["content"]
        if isinstance(content, list):
            raise ValueError("model does not support image input")
        return _FakeStream()


def _multimodal_input():
    return [
        {"type": "text", "text": "看 [Image #1] 这张图"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
    ]


def test_run_agent_turn_auto_fallback_retries_with_text():
    agent = _FakeImageAgent()
    statuses = []
    ok = run_agent_turn(
        agent, "t-img", _multimodal_input(),
        handle_interrupts=lambda i: None,
        callbacks={"on_status": statuses.append},
        model_image_input="auto",
        user_input_fallback="图片 #1 路径: C:\\x.png",
    )
    assert ok is True
    assert len(agent.inputs) == 2
    assert isinstance(agent.inputs[0]["messages"][0]["content"], list)
    assert agent.inputs[1]["messages"][0]["content"] == "图片 #1 路径: C:\\x.png"
    assert any("拒绝图片" in s for s in statuses)


def test_run_agent_turn_auto_without_fallback_arg_raises():
    agent = _FakeImageAgent()
    with pytest.raises(ValueError):
        run_agent_turn(
            agent, "t1", _multimodal_input(),
            handle_interrupts=lambda i: None,
            callbacks={},
            model_image_input="auto",
        )
    assert len(agent.inputs) == 1


def test_run_agent_turn_on_mode_no_fallback():
    agent = _FakeImageAgent()
    with pytest.raises(ValueError):
        run_agent_turn(
            agent, "t1", _multimodal_input(),
            handle_interrupts=lambda i: None,
            callbacks={},
            model_image_input="on",
            user_input_fallback="图片 #1 路径: x",
        )
    assert len(agent.inputs) == 1


def test_run_agent_turn_non_image_error_still_raises():
    class _AuthAgent(_FakeImageAgent):
        def stream_events(self, payload, *, version, config, control=None):
            self.inputs.append(payload)
            raise ValueError("401 unauthorized")

    agent = _AuthAgent()
    with pytest.raises(ValueError):
        run_agent_turn(
            agent, "t1", _multimodal_input(),
            handle_interrupts=lambda i: None,
            callbacks={},
            model_image_input="auto",
            user_input_fallback="图片 #1 路径: x",
        )
    assert len(agent.inputs) == 1


class _FakeImageAgentStatus400(_FakeImageAgent):
    """拒绝图片时报错文本不含 image/vision（通用 Bad Request + status_code=400）。"""

    def stream_events(self, payload, *, version, config, control=None):
        self.inputs.append(payload)
        content = payload["messages"][0]["content"]
        if isinstance(content, list):
            err = ValueError("Bad Request: payload rejected (code 1001)")
            err.status_code = 400
            raise err
        return _FakeStream()


class _FakeImageAgentStatus500(_FakeImageAgent):
    """服务端 5xx 与图片无关：不该触发回落，异常原样上抛。"""

    def stream_events(self, payload, *, version, config, control=None):
        self.inputs.append(payload)
        content = payload["messages"][0]["content"]
        if isinstance(content, list):
            err = ValueError("Internal Server Error")
            err.status_code = 500
            raise err
        return _FakeStream()


def test_auto_fallback_triggers_on_plain_400_without_image_words():
    agent = _FakeImageAgentStatus400()
    statuses = []
    ok = run_agent_turn(
        agent, "t-400", _multimodal_input(),
        handle_interrupts=lambda i: None,
        callbacks={"on_status": statuses.append},
        model_image_input="auto",
        user_input_fallback="图片 #1 路径: C:\\x.png",
    )
    assert ok is True
    assert len(agent.inputs) == 2
    assert isinstance(agent.inputs[1]["messages"][0]["content"], str)


def test_auto_fallback_not_triggered_on_5xx():
    agent = _FakeImageAgentStatus500()
    with pytest.raises(ValueError, match="Internal Server Error"):
        run_agent_turn(
            agent, "t-500", _multimodal_input(),
            handle_interrupts=lambda i: None,
            callbacks={},
            model_image_input="auto",
            user_input_fallback="图片 #1 路径: C:\\x.png",
        )
    assert len(agent.inputs) == 1
