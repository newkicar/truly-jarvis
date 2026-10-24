"""src/dream.py 梦境沉淀测试（tui-ux15）。

Seam: dream_job_config / 知识库读写 / _dedupe_order / distill / consolidate /
run_dream。
纪律：自建目录（tempfile.gettempdir 下），不使用 tmp_path（本机 pytest 基 temp 目录中毒）。
"""
import dataclasses
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from src import dream
from src.config import Config


@contextmanager
def _fake_cfg():
    base = Path(tempfile.gettempdir()) / ("jarvis_dream_test_%d" % os.getpid())
    shutil.rmtree(base, ignore_errors=True)
    (base / "memory").mkdir(parents=True, exist_ok=True)
    try:
        yield Config(
            project_root=base,
            base_url="https://fake/v1",
            api_key="sk",
            model_id="m",
            tavily_key="tvly",
            vault_path=base / "vault",
            memory_dir=base / "memory",
            checkpoint_db=base / "cp.sqlite",
            schedules_dir=base / "schedules",
            skills=(),
            mcps={},
            permissions={},
            hooks={},
            agents={},
            rag_ollama_base_url="http://localhost:11434",
            rag_embed_model="quentinz/bge-small-zh-v1.5",
            execution_max_steps=200,
            tui={"copy_on_select": True},
        )
    finally:
        shutil.rmtree(base, ignore_errors=True)


class FakeModel(BaseChatModel):
    """按 mode 切换行为的假模型（兼容 langmem tool-call 蒸馏与 plain JSON 合并）。"""

    mode: str = "distill"
    name: str = "fake"

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, *a, **k):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kw):
        if self.mode == "distill":
            msg = AIMessage(
                content="",
                tool_calls=[{
                    "name": "DreamItems",
                    "args": {"items": ["git pull 是安全只读操作", "用 PowerShell 写文件"]},
                    "id": "tc1",
                    "type": "tool_call",
                }],
            )
        elif self.mode == "json":
            msg = AIMessage(content='["新条目A", "B", 7]')
        else:  # empty / bad：无 tool call、无 JSON 数组
            msg = AIMessage(content="没什么可沉淀的。")
        return ChatResult(generations=[ChatGeneration(message=msg)])


def _mk_agent(model, msgs_by_tid, threads=("t1", "t2")):
    class FakeCheckpointer:
        @contextmanager
        def cursor(self):
            class _Cur:
                def execute(self, sql):
                    return self

                def fetchall(self):
                    return [(t,) for t in threads]

            yield _Cur()

    def get_state(cfg, *a, **k):
        return type("Head", (), {"values": {"messages": msgs_by_tid[cfg["configurable"]["thread_id"]]}})()

    return type("FakeAgent", (), {
        "checkpointer": FakeCheckpointer(),
        "get_state": staticmethod(get_state),
        "_jarvis_model": model,
    })()


# --- dream_job_config ---

def test_dream_job_config_defaults():
    with _fake_cfg() as cfg:
        assert dream.dream_job_config(cfg) == (True, "0 3 * * *")


def test_dream_job_config_custom():
    with _fake_cfg() as cfg:
        cfg2 = dataclasses.replace(cfg, dream={"enabled": False, "cron": "30 4 * * *"})
        assert dream.dream_job_config(cfg2) == (False, "30 4 * * *")


def test_dream_job_config_bad_cron_falls_back():
    with _fake_cfg() as cfg:
        for bad in ({"cron": 123}, {"cron": "   "}, {"cron": None}):
            cfg2 = dataclasses.replace(cfg, dream=bad)
            assert dream.dream_job_config(cfg2) == (True, "0 3 * * *")


def test_dream_job_config_non_dict_ignored():
    with _fake_cfg() as cfg:
        cfg2 = dataclasses.replace(cfg, dream="nonsense")
        assert dream.dream_job_config(cfg2) == (True, "0 3 * * *")


# --- 知识库读写 ---

def test_knowledge_roundtrip():
    with _fake_cfg() as cfg:
        assert dream.load_knowledge(cfg) == []
        path = dream.write_knowledge(cfg, ["条目一", "条目二"])
        assert path.exists()
        assert dream.load_knowledge(cfg) == ["条目一", "条目二"]


def test_knowledge_nonexistent_returns_empty():
    with _fake_cfg() as cfg:
        assert dream.load_knowledge(cfg) == []


def test_append_run_log_appends_lines():
    with _fake_cfg() as cfg:
        p1 = dream.append_run_log(cfg, "line-1")
        p2 = dream.append_run_log(cfg, "line-2")
        assert p1 == p2
        assert p1.read_text(encoding="utf-8") == "line-1\nline-2\n"


# --- _dedupe_order ---

def test_dedupe_casefold_first_wins():
    assert dream._dedupe_order(["ABC", "abc", "Xyz", "xyz", "q"]) == ["ABC", "Xyz", "q"]


def test_dedupe_truncates_to_max():
    assert dream._dedupe_order(["a", "b", "c", "d"], max_items=2) == ["a", "b"]


# --- distill ---

def test_distill_tool_call_ok():
    items = dream.distill(FakeModel(mode="distill"), [HumanMessage(content="hi")])
    assert items == ["git pull 是安全只读操作", "用 PowerShell 写文件"]


def test_distill_no_toolcall_returns_empty():
    assert dream.distill(FakeModel(mode="empty"), [HumanMessage(content="hi")]) == []


def test_distill_bad_mode_returns_empty():
    assert dream.distill(FakeModel(mode="bad"), [HumanMessage(content="hi")]) == []


def test_distill_none_model_returns_empty():
    assert dream.distill(None, [HumanMessage(content="hi")]) == []


# --- consolidate ---

def test_consolidate_json_ok():
    out = dream.consolidate(FakeModel(mode="json"), ["新条目A", "B"], ["旧条目"])
    assert out == ["新条目A", "B", "7"]


def test_consolidate_parse_fail_falls_back_to_dedupe():
    out = dream.consolidate(FakeModel(mode="bad"), ["x"], ["y", "x"])
    assert out == ["x", "y"]


def test_consolidate_none_model_dedupe():
    assert dream.consolidate(None, ["x"], ["y", "x"]) == ["x", "y"]


def test_consolidate_combined_empty():
    assert dream.consolidate(FakeModel(mode="json"), [], []) == []


# --- run_dream ---

def test_run_dream_no_model():
    with _fake_cfg() as cfg:
        agent = _mk_agent(None, {})
        assert dream.run_dream(agent, cfg) == "梦境沉淀失败：模型不可用，本次未沉淀（知识库现有 0 条）"


def test_run_dream_no_threads():
    with _fake_cfg() as cfg:
        agent = _mk_agent(FakeModel(mode="distill"), {}, threads=())
        assert dream.run_dream(agent, cfg) == "梦境沉淀：暂无可回顾的近期会话（知识库现有 0 条）"


def test_run_dream_e2e_distill_and_write():
    with _fake_cfg() as cfg:
        msgs = {
            "t1": [HumanMessage(content="帮我拉取代码"), AIMessage(content="已执行 git pull")],
            "t2": [HumanMessage(content="写个文件"), AIMessage(content="ok")],
        }
        agent = _mk_agent(FakeModel(mode="distill"), msgs)
        text = dream.run_dream(agent, cfg)
        assert text == "梦境沉淀完成：回顾 2 个会话，蒸馏 2 条 → 知识库 2 条（memory/dream/knowledge.md）"
        assert dream.load_knowledge(cfg) == ["git pull 是安全只读操作", "用 PowerShell 写文件"]
        runs = (cfg.memory_dir / "dream" / "runs.md").read_text(encoding="utf-8")
        assert "回顾 2 个会话" in runs


def test_run_dream_no_new_knowledge_keeps_existing():
    with _fake_cfg() as cfg:
        dream.write_knowledge(cfg, ["保留我"])
        msgs = {"t1": [HumanMessage(content="闲聊"), AIMessage(content="嗯")]}
        agent = _mk_agent(FakeModel(mode="empty"), msgs, threads=("t1",))
        text = dream.run_dream(agent, cfg)
        assert "未蒸馏到新的可复用知识" in text
        assert dream.load_knowledge(cfg) == ["保留我"]
        assert (cfg.memory_dir / "dream" / "runs.md").exists()


def test_run_dream_skips_incomplete_threads():
    with _fake_cfg() as cfg:
        msgs = {
            "t1": [HumanMessage(content="用户说"), AIMessage(content="JARVIS 答")],
            "t2": [SystemMessage(content="只有系统消息")],
        }
        agent = _mk_agent(FakeModel(mode="distill"), msgs)
        text = dream.run_dream(agent, cfg)
        assert "回顾 1 个会话" in text
