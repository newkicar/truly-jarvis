"""JarvisRuntime worker isolation + agent_runs audit tests (ticket 06).

Fake model + MemorySaver checkpointer; scratch state under
.scratch/runtime-test-tmp (gitignored); no tmp_path fixtures in this repo.
"""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest
import yaml
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from src import commands, jarvis_runtime
from src.jarvis_runtime import create
from src.profiles.db import list_agent_run_rows
from src.profiles.spec import _reset_bake_cache
from tests.test_agent import ToolCapableFake

_ROOT = Path(__file__).resolve().parent.parent
_SCRATCH = _ROOT / ".scratch" / "runtime-test-tmp"
PID = "rt-prof"


@pytest.fixture(autouse=True)
def _clean_scratch():
    yield
    _reset_bake_cache()
    shutil.rmtree(_SCRATCH, ignore_errors=True)


def _new_home() -> Path:
    home = _SCRATCH / f"home-{uuid.uuid4().hex[:12]}"
    home.mkdir(parents=True)
    return home


def _new_workspace() -> Path:
    ws = _SCRATCH / f"ws-{uuid.uuid4().hex[:12]}"
    ws.mkdir(parents=True)
    return ws


def _write_profile(home: Path, pid: str = PID) -> None:
    d = home / "agents" / pid
    d.mkdir(parents=True)
    (d / "agent.yaml").write_text(
        yaml.safe_dump(
            {
                "id": pid,
                "name": "RT Prof",
                "permissions": {"approvals": {
                    "execute": "optional",
                    "external_network": "optional",
                    "destructive_operations": "optional",
                }},
            }
        ),
        encoding="utf-8",
    )
    (d / "AGENTS.md").write_text("runtime test rules", encoding="utf-8")


ENV_OVERRIDES = {
    "BASE_URL": "https://fake/v1",
    "API_KEY": "sk",
    "MODEL_ID": "m",
    "TAVILY_KEY": "tvly",
}


def _make(home, ws, monkeypatch, **kw):
    monkeypatch.setenv("JARVIS_HOME", str(home))
    kw.setdefault("model", ToolCapableFake(reply="ok"))
    kw.setdefault("env_overrides", dict(ENV_OVERRIDES))
    kw.setdefault("user_home", home)
    return create(PID, ws, **kw)


def _row(home, runtime_id):
    rows = [r for r in list_agent_run_rows(home, profile_id=PID) if r["runtime_id"] == runtime_id]
    assert len(rows) == 1
    return rows[0]


class FailingFake(BaseChatModel):
    def bind_tools(self, *a, **k):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise RuntimeError("model exploded")

    @property
    def _llm_type(self) -> str:
        return "failing-fake"


class TestCreateValidation:
    def test_workspace_missing_raises(self, monkeypatch):
        home = _new_home()
        monkeypatch.setenv("JARVIS_HOME", str(home))
        with pytest.raises(FileNotFoundError):
            create(PID, _SCRATCH / "nope", task_id="t1")

    def test_pinned_version_rejected_without_audit_row(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        _write_profile(home)
        with pytest.raises(ValueError):
            _make(home, ws, monkeypatch, task_id="t6", profile_version=2)
        assert list_agent_run_rows(home, profile_id=PID) == []
        # matching pin passes
        ok = _make(home, ws, monkeypatch, task_id="t6", profile_version=1)
        assert _row(home, ok.runtime_id)["status"] == "created"


class TestInvoke:
    def test_invoke_returns_122_dict(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        _write_profile(home)
        h = _make(home, ws, monkeypatch, task_id="t1", checkpointer=MemorySaver())
        out = h.invoke("hello")
        assert set(out) == {
            "runtime_id", "profile_id", "profile_version", "task_id",
            "session_id", "status", "result", "artifacts",
            "memory_candidates", "usage",
        }
        assert out["status"] == "completed"
        assert out["result"] == "ok"
        assert out["profile_id"] == PID
        assert out["profile_version"] == "1"
        assert out["task_id"] == "t1"
        assert out["session_id"] is None
        assert out["artifacts"] == []
        assert out["memory_candidates"] == []
        assert out["usage"] == {}
        assert out["runtime_id"] == h.runtime_id
        assert len(h.runtime_id) == 32
        # thread state contains the human message
        state = h.agent.get_state(commands.thread_config("t1"))
        assert any(
            isinstance(m, HumanMessage) and m.content == "hello"
            for m in state.values["messages"]
        )

    def test_invoke_failed_audit(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        _write_profile(home)
        h = _make(home, ws, monkeypatch, task_id="t2", model=FailingFake())
        with pytest.raises(RuntimeError):
            h.invoke("hi")
        row = _row(home, h.runtime_id)
        assert row["status"] == "failed"
        assert row["finished_at"]

    def test_invoke_closed_raises(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        _write_profile(home)
        h = _make(home, ws, monkeypatch, task_id="t2b")
        h.close()
        with pytest.raises(RuntimeError):
            h.invoke("late")


class TestAuditLifecycle:
    def test_agent_runs_lifecycle(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        _write_profile(home)
        h = _make(home, ws, monkeypatch, task_id="t4", checkpointer=MemorySaver())
        assert _row(home, h.runtime_id)["status"] == "created"
        h.invoke("x")
        row = _row(home, h.runtime_id)
        assert row["status"] == "completed"
        assert row["finished_at"]
        h.close()
        # terminal status is not overwritten by close
        assert _row(home, h.runtime_id)["status"] == "completed"

    def test_close_open_row_cancelled(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        _write_profile(home)
        h = _make(home, ws, monkeypatch, task_id="t5")
        h.close()
        row = _row(home, h.runtime_id)
        assert row["status"] == "cancelled"
        assert row["finished_at"]
        h.close()  # idempotent


class TestWorkerIsolation:
    def test_dual_worker_isolation(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        _write_profile(home)
        ck_a, ck_b = MemorySaver(), MemorySaver()
        h1 = _make(home, ws, monkeypatch, task_id="t7", session_id="s-a", checkpointer=ck_a)
        h2 = _make(home, ws, monkeypatch, task_id="t7", session_id="s-b", checkpointer=ck_b)
        assert h1.agent.checkpointer is not h2.agent.checkpointer
        assert h1.thread_id == "s-a" and h2.thread_id == "s-b"
        h1.invoke("hi from A")
        h2.invoke("hi from B")
        st_a = h1.agent.get_state(commands.thread_config("s-a"))
        texts_a = [m.content for m in st_a.values["messages"] if isinstance(m, HumanMessage)]
        assert "hi from A" in texts_a
        assert "hi from B" not in texts_a
        st_b = h2.agent.get_state(commands.thread_config("s-b"))
        texts_b = [m.content for m in st_b.values["messages"] if isinstance(m, HumanMessage)]
        assert "hi from B" in texts_b
        assert "hi from A" not in texts_b

    def test_distinct_runtimes_have_distinct_ids(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        _write_profile(home)
        h1 = _make(home, ws, monkeypatch, task_id="t7")
        h2 = _make(home, ws, monkeypatch, task_id="t7")
        assert h1.runtime_id != h2.runtime_id


class TestStream:
    def test_stream_completes(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        _write_profile(home)
        h = _make(home, ws, monkeypatch, task_id="t8", checkpointer=MemorySaver())
        events = list(h.stream("hi"))
        assert events
        assert _row(home, h.runtime_id)["status"] == "completed"

    def test_stream_early_break_cancels(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        _write_profile(home)
        h = _make(home, ws, monkeypatch, task_id="t9", checkpointer=MemorySaver())
        gen = h.stream("hi")
        next(gen)  # guaranteed at least one v3 event
        gen.close()
        assert _row(home, h.runtime_id)["status"] == "cancelled"


class TestResume:
    def test_resume_lifecycle(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        _write_profile(home)
        h0 = _make(home, ws, monkeypatch, task_id="t10")
        with pytest.raises(RuntimeError):
            h0.resume()
        ck = MemorySaver()
        h = _make(home, ws, monkeypatch, task_id="t10", checkpointer=ck)
        assert h.resume() is None
        h.invoke("go")
        r = h.resume()
        assert r["thread_id"] == "t10"
        assert r["checkpoint_id"] is not None
        assert r["next"] == ()
        # metadata = snapshot + runtime_id
        md = h.metadata
        assert md["runtime_id"] == h.runtime_id
        assert md["profile_id"] == PID
        assert md["profile_version"] == "1"
        assert md["engine"] == "deepagents"
        assert len(md["profile_hash"]) == 64


class TestModuleSurface:
    def test_exports(self):
        assert hasattr(jarvis_runtime, "create")
        assert hasattr(jarvis_runtime, "RuntimeHandle")
        assert jarvis_runtime.TERMINAL_STATUSES == ("completed", "failed", "cancelled")
