"""共享测试工具。

Seam: 把 Config 构造抽到一处，避免 test_agent / test_scheduler 各维护一份
`_fake_config`（加字段要改两处，shotgun 症状）。
"""
import gc
import os

from src.config import Config


def pytest_collection_modifyitems(config, items):
    """GUI 子集进程内禁用自动 GC 周期（faulthandler 定案的 CI 崩族缓解）。

    崩族：套件中途某次自动 GC 周期触发 shiboken C 级 finalizer 析构被弃的
    Qt 包装器 → SIGSEGV / Fatal Python error: Aborted（faulthandler 帧实证：
    "Garbage-collecting" 顶帧 + 崩在 pytest teardown 机器里，无摘要行 →
    rc=139 容错救不了 → 红）。禁 GC 后循环垃圾累积到解释器退出期统一
    收集——退出期崩属已知容忍族（rc=139/134 + 全绿摘要即放行）。
    非 GUI 进程不收集到 test_gui_* 文件 → 钩子 no-op，零影响。
    判据用 nodeid basename 前缀，不依赖 item.module（收集期不导入模块）。
    """
    if any(os.path.basename(it.nodeid).startswith("test_gui_") for it in items):
        gc.disable()


def make_fake_config(tmp_path) -> Config:
    """构造指向 tmp_path 的假 Config（不触网、不碰真 vault）。"""
    return Config(
        project_root=tmp_path,
        base_url="https://fake/v1",
        api_key="sk",
        model_id="m",
        tavily_key="tvly",
        vault_path=tmp_path / "vault",
        memory_dir=tmp_path / "memory",
        checkpoint_db=tmp_path / "cp.sqlite",
        schedules_dir=tmp_path / "schedules",
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