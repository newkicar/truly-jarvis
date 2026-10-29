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
    from PySide6.QtWidgets import QDialog

    # PySide6 6.x 起枚举不在实例上暴露（wiz.Accepted 不存在）→ 类级作用域枚举
    if wiz.result() == QDialog.DialogCode.Accepted:
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
        # GUI 自配层喂内核：无项目 .env 时必需键全来自向导 LLM 配置（不落明文）；
        # TAVILY 可空（搜索工具未配置时温和提示，不阻断启动）。
        overrides = None
        if llm is not None:
            overrides = {
                "BASE_URL": llm.base_url,
                "API_KEY": llm.api_key,
                "MODEL_ID": llm.model_id,
                "TAVILY_KEY": "",
            }
        config = load_config(env_overrides=overrides)

    model, label = None, ""
    if llm is not None:
        model = llm.to_chat_model()
        label = llm.model_id

    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    from src.gui.events import UiBridge
    from src.gui.main_window import MainWindow
    from src.gui.project_registry import ProjectRegistry, default_registry_path
    from src.gui.workspace_controller import WorkspaceController

    app = QApplication.instance() or QApplication(sys.argv[:1])
    bridge = UiBridge()

    # 多项目工作区（工单 05）：全局注册表 + 切项目控制器。启动 = 打开最近项目，
    # 首次（空注册表）= 登记并打开启动目录对应的项目。
    registry = ProjectRegistry(default_registry_path())
    launch = registry.pick_launch()
    start_root = Path(str(launch["path"])) if launch else Path(config.project_root)
    if not launch:
        registry.add(start_root)

    def _make_runtime(root):
        from src.gui.runtime import build_runtime

        cfg = load_config(project_root=Path(root), env_overrides=overrides)
        rt, _gate = build_runtime(
            cfg, model=model, enable_mcp=enable_mcp,
            enable_scheduled=enable_scheduled, label=label or cfg.model_id,
        )
        return rt

    controller = WorkspaceController(registry, _make_runtime, bridge)
    presenter = controller.switch_project(start_root)
    key_store = llm_config.make_key_store() if llm is not None else None
    win = MainWindow(presenter, bridge, llm=llm, key_store=key_store, workspace=controller)
    win.show()

    try:
        rc = app.exec()
    finally:
        controller.shutdown()
    return int(rc or 0)


if __name__ == "__main__":
    sys.exit(main())
