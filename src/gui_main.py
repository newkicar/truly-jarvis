"""GUI 入口：python -m src.gui_main。

装配与 main.py 同源（config → SqliteSaver → permissions → agent → JumpInRegistry），
差异点：
- 交互形态 = PySide6 窗口（CLI/TUI 仍走 src.main，零改动）。
- LLM 优先用户自配层（%APPDATA%\\Jarvis\\config.json + 凭据管理器）；
  未配置/悬空 → 首启 5 步向导（可跳过）；跳过且无 .env → 友好退出。
- 定时任务默认不启动（SchedulerGate，遗留 d：单 scheduler 约束）。
"""
from __future__ import annotations

import sys


def _run_wizard(app) -> "object | None":
    """首启/悬空 LLM 向导。返回 LlmConfig（保存）或 None（跳过/取消）。"""
    from src.gui import llm_config
    from src.gui.wizard import LlmWizard

    home = llm_config.default_home()
    store = llm_config.make_key_store(home)
    res = llm_config.load_llm_config(store, home)
    start_page = 2 if res.key_status == "dangling" else 0  # 悬空回第 3 步重填 key
    wiz = LlmWizard(key_store=store, home=home, start_page_index=start_page, parent=None)
    wiz.show()
    wiz.exec()
    if wiz.result() == wiz.Accepted:
        return wiz.current_config()
    return None


def main(argv: list[str] | None = None) -> int:
    from src.config import ensure_utf8_stdout, load_config
    from src.project_init import auto_init_project
    from src.project_paths import ensure_user_home

    ensure_utf8_stdout()
    ensure_user_home()

    argv = argv if argv is not None else sys.argv[1:]
    enable_mcp = "--mcp" in argv
    enable_scheduled = "--scheduled" in argv

    from src.gui import llm_config

    # ① 用户自配层：key_ref 有效 → 优先用；悬空 → 向导第 3 步重填（spec）；
    # 无配置 且 无 .env → 全量向导；有 .env → 静默走 .env（开发机零打扰）。
    res = llm_config.ensure_configured()
    llm = None
    config = None
    if res.key_status == "ok":
        llm = res.config
    else:
        try:
            config = load_config()
        except (KeyError, FileNotFoundError):
            config = None
        if res.key_status == "dangling" or config is None:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance() or QApplication(sys.argv[:1])
            llm = _run_wizard(app)
            if llm is None and config is None:
                print("LLM 尚未配置：首启请完成向导（或放置 .env 后重启）。")
                return 1
    if config is None:
        auto_init_project()
        config = load_config()

    model, label = None, ""
    if llm is not None:
        model = llm.to_chat_model()
        label = llm.model_id

    from src.gui.runtime import build_runtime

    runtime, gate = build_runtime(
        config,
        model=model,
        enable_mcp=enable_mcp,
        enable_scheduled=enable_scheduled,
        label=label or config.model_id,
    )

    from PySide6.QtWidgets import QApplication

    from src.gui.events import UiBridge
    from src.gui.main_window import MainWindow
    from src.gui.presenter_wiring import wire_presenter

    app = QApplication.instance() or QApplication(sys.argv[:1])
    bridge = UiBridge()
    presenter = wire_presenter(runtime, bridge, app=app)
    win = MainWindow(presenter, bridge)
    win.show()

    try:
        rc = app.exec()
    finally:
        gate.shutdown()
        runtime.close()
    return int(rc or 0)


if __name__ == "__main__":
    sys.exit(main())
