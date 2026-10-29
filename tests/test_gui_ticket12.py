"""工单 12 — 可选依赖降级与自检页（chromadb 回落 / Ollama 探测 / 单 scheduler / doctor）。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

from src.gui import doctor
from src.gui.events import UiBridge
from src.gui.llm_config import InMemoryKeyStore, LlmConfig
from src.gui.main_window import MainWindow
from src.gui.runtime import GuiPresenter, SchedulerGate
from tests.gui_fakes import cleanup_home, new_home
from tests.test_gui_presenter import _fake_runtime

def _row(rows, block, item=None):
    cands = [r for r in rows if r.block == block and (item is None or r.item == item)]
    assert cands, f"缺区块 {block}/{item}: {[r.block for r in rows]}"
    return cands[0]


# ---------------------------------------------------------------- LLM 区块
def test_report_llm_env_fallback():
    cfg = _fake_runtime().config
    rows = doctor.build_doctor_report(cfg)
    assert _row(rows, "LLM", "端点/凭据").status == doctor.STATUS_OK
    assert "项目 .env" in _row(rows, "LLM", "端点/凭据").detail


def test_report_llm_dangling_key_ref():
    cfg = _fake_runtime().config
    llm = LlmConfig(base_url="https://gw/v1", api_key="sk-x", model_id="m")
    rows = doctor.build_doctor_report(cfg, llm=llm, key_store=InMemoryKeyStore())
    assert _row(rows, "LLM", "端点/凭据").status == doctor.STATUS_WARN
    assert "向导" in _row(rows, "LLM", "端点/凭据").hint


def test_report_llm_key_ok():
    cfg = _fake_runtime().config
    llm = LlmConfig(base_url="https://gw/v1", api_key="sk-x", model_id="m")
    store = InMemoryKeyStore()
    store.set("jarvis-llm", "sk-real")
    rows = doctor.build_doctor_report(cfg, llm=llm, key_store=store)
    assert _row(rows, "LLM", "端点/凭据").status == doctor.STATUS_OK


# ---------------------------------------------------------------- 可选依赖
def test_report_chromadb_missing_guidance(monkeypatch):
    monkeypatch.setattr(doctor, "chromadb_available", lambda: False)
    rows = doctor.build_doctor_report(_fake_runtime().config)
    r = _row(rows, "可选依赖", "RAG 语义索引（chromadb）")
    assert r.status == doctor.STATUS_WARN
    assert "grep/wiki" in r.detail and "pip install chromadb" in r.hint


def test_report_chromadb_ok():
    rows = doctor.build_doctor_report(_fake_runtime().config)
    assert _row(rows, "可选依赖", "RAG 语义索引（chromadb）").status == doctor.STATUS_OK


def test_report_ollama_unreachable_fallback():
    rows = doctor.build_doctor_report(_fake_runtime().config, ollama_reachable=False)
    r = _row(rows, "可选依赖", "Ollama embedding")
    assert r.status == doctor.STATUS_WARN
    assert "grep/wiki" in r.detail and "Ollama" in r.hint


def test_report_ollama_ok():
    r = _row(doctor.build_doctor_report(_fake_runtime().config, ollama_reachable=True),
             "可选依赖", "Ollama embedding")
    assert r.status == doctor.STATUS_OK


def test_report_mcp_count():
    assert "0 工具" in _row(doctor.build_doctor_report(_fake_runtime().config,
                                                        mcp_tool_count=0), "可选依赖", "MCP").detail
    assert "3 个 MCP 工具" in _row(doctor.build_doctor_report(_fake_runtime().config,
                                                               mcp_tool_count=3), "可选依赖", "MCP").detail


# ---------------------------------------------------------------- 记忆 / 检查点 / 定时
def test_report_memory_and_checkpoint_and_scheduler_rows():
    home = new_home()
    try:
        cfg = _fake_runtime().config
        rows = doctor.build_doctor_report(cfg, scheduler_running=False)
        mem_rows = [r for r in rows if r.block == "记忆"]
        assert len(mem_rows) == 2 and all(r.status == doctor.STATUS_OK for r in mem_rows)
        assert _row(rows, "检查点", "checkpoints.sqlite").status == doctor.STATUS_OK
        assert "未启动" in _row(rows, "定时任务", "scheduler").detail
        assert "输入通道" in {r.block for r in rows}
    finally:
        cleanup_home(home)


# ---------------------------------------------------------------- scheduler 门控
def test_scheduler_gate_enable_idempotent_single(monkeypatch):
    from src import scheduler as sched_mod

    rt = _fake_runtime()
    calls = {"n": 0, "started": 0}

    class _FakeSched:
        def start(self):
            calls["started"] += 1

        def get_jobs(self):
            return []

        def shutdown(self, wait=False):
            pass

    fake = _FakeSched()

    def _make(agent, config):
        calls["n"] += 1
        return fake

    monkeypatch.setattr(sched_mod, "make_scheduler", _make)
    gate: SchedulerGate = rt.gate
    assert gate.enabled is False
    assert "已启动" in gate.enable()
    assert gate.enabled is True and calls["n"] == 1 and calls["started"] == 1
    assert "已在运行" in gate.enable()  # 后启动者不双开
    assert calls["n"] == 1 and calls["started"] == 1


# ---------------------------------------------------------------- RAG 内核降级
def test_rag_search_degrades_when_index_broken(monkeypatch):
    from pathlib import Path

    from src import rag

    def _raise(*a, **k):
        raise ImportError("No module named 'chromadb'")

    monkeypatch.setattr(rag, "RagIndex", _raise)
    tool = rag.make_semantic_search_tool(Path("x"), Path("y"))
    out = tool.invoke({"query": "查询"})
    assert "chromadb" in out and "grep" in out


# ---------------------------------------------------------------- 对话框 + 菜单
def test_doctor_dialog_renders_rows(qapp):
    rows = doctor.build_doctor_report(_fake_runtime().config, ollama_reachable=False,
                                      mcp_tool_count=0, scheduler_running=True)
    assert {"LLM", "输入通道", "可选依赖", "记忆", "检查点", "定时任务"} <= {r.block for r in rows}
    html = doctor.doctor_report_markup(rows)
    assert "<b>LLM</b>" in html and "Ollama 不可达" in html
    dlg = doctor.make_doctor_dialog(rows, None)
    dlg.show()
    qapp.processEvents()
    assert dlg.doctor_rows == rows
    dlg.close()


def test_main_window_doctor_menu(qapp, monkeypatch):
    rt = _fake_runtime()
    p = GuiPresenter(rt, UiBridge())
    win = MainWindow(p, p.bridge)
    captured: dict = {}

    class _Dlg:
        def exec(self):
            captured["shown"] = True

    def _fake_dialog(rows, parent=None):
        captured["rows"] = rows
        return _Dlg()

    monkeypatch.setattr(doctor, "make_doctor_dialog", _fake_dialog)
    monkeypatch.setattr(win, "_probe_ollama", lambda: False)

    from PySide6.QtWidgets import QMenu

    mb = win.menuBar()
    cmd = next(m for m in mb.findChildren(QMenu) if m.title() == "命令")
    act = next(a for a in cmd.actions() if "Doctor" in a.text())
    act.trigger()
    assert captured.get("shown") is True
    assert _row(captured["rows"], "LLM", "端点/凭据").status == doctor.STATUS_OK
