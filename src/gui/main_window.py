"""GUI 主窗口（PySide6）：会话侧栏（占位）+ 对话区（QStackedWidget 每 thread 一栈）
+ 输入区 + 状态行。worker→主线程事件经 UiBridge 信号驱动，本模块只做渲染。

工单 01 范围：最小可对话窗口（真实模型、流式上屏、回合门、取消）。
工单 03/04/05/06… 在本文件上渐进扩展（输入区自动拉高 / 审批卡片 / 命名侧栏 / 工具详情）。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src import clipboard_image, commands
from src.gui.completion import CompletionPopup, accept_suggestion, resolve_for_input
from src.gui.events import UiBridge
from src.gui.image_strip import build_image_submit, save_clipboard_image_to_temp
from src.gui.image_widgets import ImageStrip
from src.gui.input_bar import InputBar
from src.gui.notify_channels import make_hooks
from src.gui.notify_policy import TaskNotifier
from src.gui.pane import RENDER_BATCH_MS, ChatPane
from src.gui.queue_strip import QueueStrip
from src.gui.runtime import GuiPresenter
from src.gui.runtime_registry import normalize_root_key
from src.gui.status_view import StatusView
from src.gui.workspace_controller import StaticWorkspace

_PROJ_ROLE = Qt.ItemDataRole.UserRole + 100
_TID_ROLE = Qt.ItemDataRole.UserRole + 101


def make_text_dialog(title: str, text: str, parent=None) -> None:
    """长文报告对话框（gui15 G7：/help 等命令输出）——可滚动 + 可拖选，不再压状态栏。"""
    from PySide6.QtWidgets import QDialog, QScrollArea

    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    lay = QVBoxLayout(dlg)
    area = QScrollArea()
    area.setWidgetResizable(True)
    label = QLabel(text)
    label.setObjectName("report-label")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    area.setWidget(label)
    lay.addWidget(area)
    btn = QPushButton("关闭")
    btn.clicked.connect(dlg.accept)
    lay.addWidget(btn)
    dlg.resize(720, 460)
    dlg.exec()


class MainWindow(QMainWindow):
    def __init__(self, presenter: GuiPresenter, bridge: UiBridge, *, llm=None, key_store=None, workspace=None) -> None:
        QMainWindow.__init__(self)
        self.presenter = presenter
        # 多项目工作区接口（工单 04）：缺省 = StaticWorkspace（单项目，行为不变）；
        # gui_main 传入 WorkspaceController（多项目，切项目=关旧建新）
        self._workspace = workspace or StaticWorkspace(presenter, bridge)
        # 后台任务完成标记 + 三通道通知器（gui bgnotify；键=(normalize_root_key(root), tid)）
        self._sess_done: dict = {}   # (归一 root, tid) -> "ok"/"fail"
        self._proj_done: dict = {}   # 归一 root -> 最近一次结果
        self._notifier = TaskNotifier(make_hooks())
        self._notifier.policy = self._active_policy()
        self.bridge = bridge
        self._llm = llm  # LlmConfig | None（GUI 自配层；None = 走项目 .env）
        self._key_store = key_store
        self.panes: dict[str, ChatPane] = {}
        self.active_tid: str | None = None
        self._last_input_text = ""
        self._drafts: dict[str, tuple[str, list[str]]] = {}  # #1: 每会话未提交草稿（文本+图片）
        self._build_ui()
        self._wire_bridge()
        # 启动即应用已持久化主题（taste-skill token QSS；切主题零重建、全量跟随）
        from PySide6.QtWidgets import QApplication

        from src.gui import theme as _theme

        _theme.apply_theme(QApplication.instance(), _theme.load_theme())
        # 懒建 pane（重记录重建只在首访该会话时发生，启动不预建全部）；
        # 启动打开「上次活动会话」（工单 05），没有则取最新或新会话
        # 空态（presenter=None：jarvis 依赖文件已删/目录已移）：不崩、不自动重建文件；
        # 禁用输入区，等用户手动「打开项目 / 新建项目」关联
        if presenter is not None:
            first = presenter.session_ids()
            start = self._workspace.pick_start(self._workspace.active_root())
            self._switch_to(start or (first[0] if first else presenter.new_session_id()))
        else:
            self.input_bar.edit.setEnabled(False)
            self.input_bar.btn_send.setEnabled(False)

    # ---- 任务完成通知
    def _active_policy(self):
        pres = self.presenter
        rt = getattr(pres, "runtime", None)
        return getattr(rt, "notifier_policy", None) if rt is not None else None

    # ---- 结构
    def _build_ui(self) -> None:
        self._update_title()
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 工单 08：左侧模式徽标（Plan/Act·YOLO 菜单挪到「高级」，菜单栏末位）
        self.mode_badge = QLabel("")
        self.mode_badge.setObjectName("badge-mode")

        # ---- 工单 05：打开项目 / 新建项目（多项目工作区，放菜单栏最前）
        open_menu = self.menuBar().addMenu("打开项目")
        self._build_open_project_menu(open_menu)
        new_menu = self.menuBar().addMenu("新建项目")
        new_act = new_menu.addAction("新建项目…")
        new_act.triggered.connect(self._new_project_dialog)

        # ---- 工单 10：命令菜单 / 主题 / MCP / 定时任务
        cmd = self.menuBar().addMenu("命令")
        filter_action = cmd.addAction("筛选命令…")
        filter_action.triggered.connect(self._on_filter_commands)
        cmd.addSeparator()
        doctor_action = cmd.addAction("自检（Doctor）…")
        doctor_action.triggered.connect(self._on_doctor)
        cmd.addSeparator()
        self._show_archived = False
        self._archived_action = cmd.addAction("显示已归档会话")
        self._archived_action.setCheckable(True)
        self._archived_action.triggered.connect(self._on_show_archived_toggled)
        self._build_command_menu(cmd)

        theme_menu = self.menuBar().addMenu("主题")
        from src.gui import theme as _theme

        self._theme_items = {}
        for t in _theme.THEMES:
            act = theme_menu.addAction(t.upper())
            act.setCheckable(True)
            act.setChecked(_theme.load_theme() == t)
            act.triggered.connect(lambda _on=False, tt=t: self._on_theme(tt))
            self._theme_items[t] = act
        theme_menu.addSeparator()
        theme_menu.addAction("下一个主题", lambda: self._on_theme(_theme.toggle_theme()))

        # ---- 工单 09：时间旅行菜单（移至 主题 之后）
        tt = self.menuBar().addMenu("时间旅行")
        tt_snapshot = tt.addAction("手动快照")
        tt_snapshot.triggered.connect(self._on_snapshot)
        tt_snapshots = tt.addAction("快照列表")
        tt_snapshots.triggered.connect(self._on_snapshots_list)
        tt_replay = tt.addAction("回放点…（回放 / 开分支 / 压缩）")
        tt_replay.triggered.connect(self._on_time_travel_dialog)
        self._tt_menu = tt

        mcp_menu = self.menuBar().addMenu("MCP 工具")
        self._build_mcp_menu(mcp_menu)

        sched_menu = self.menuBar().addMenu("定时任务")
        sched_open = sched_menu.addAction("打开定时任务面板")
        sched_open.triggered.connect(self._on_scheduler_panel)

        # ---- 工单 08：高级菜单（菜单栏末位：Plan/Act · 替我审批 · YOLO · 撤回）
        adv = self.menuBar().addMenu("高级")
        self.plan_action = adv.addAction("规划模式（Plan：写工具被拦，先规划）")
        self.plan_action.setCheckable(True)
        self.plan_action.toggled.connect(self._on_plan_toggled)
        self.proxy_action = adv.addAction("替我审批（自动放行安全审批，拦住危险）")
        self.proxy_action.setCheckable(True)
        self.proxy_action.toggled.connect(self._on_proxy_toggled)
        self.yolo_action = adv.addAction("YOLO（本会话免审批）")
        self.yolo_action.setCheckable(True)
        self.yolo_action.toggled.connect(self._on_yolo_toggled)
        adv.addSeparator()
        undo_action = adv.addAction("撤回上一轮（消息层）")
        undo_action.triggered.connect(self._on_undo)
        compact_action = adv.addAction("自动压缩上下文阈值…")
        compact_action.triggered.connect(self._on_set_auto_compaction)
        self._compact_action = compact_action
        # 空态（无活动项目）置灰，避免「点了没反应」误以为 bug；恢复项目后由 _do_switch_project 重新启用
        self._compact_action.setEnabled(self.presenter is not None)
        self._advanced_menu = adv

        left = QFrame()
        left.setFixedWidth(230)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(8, 8, 4, 8)
        title = QLabel("<b>JARVIS</b>  会话")
        title.setObjectName("title-sessions")
        title.setTextFormat(Qt.TextFormat.RichText)
        ll.addWidget(title)
        self.project_tree = QTreeWidget()
        self.project_tree.setObjectName("session-list")
        self.project_tree.setRootIsDecorated(True)  # 项目节点显示 +/− 展开柄
        self.project_tree.setUniformRowHeights(True)
        self.project_tree.itemClicked.connect(self._on_tree_item_clicked)
        self.project_tree.itemDoubleClicked.connect(self._on_tree_item_double_clicked)
        self.project_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.project_tree.customContextMenuRequested.connect(self._on_tree_context)
        ll.addWidget(self.project_tree, stretch=1)
        self._empty_hint = QLabel("还没有项目（用「打开项目 / 新建项目」开始）")
        self._empty_hint.setObjectName("hint-note")
        self._empty_hint.setWordWrap(True)
        self._empty_hint.hide()
        ll.addWidget(self._empty_hint)
        self.btn_new = QPushButton("＋ 新会话")
        self.btn_new.setObjectName("btn-primary")
        self.btn_new.clicked.connect(self._on_new_session_clicked)
        ll.addWidget(self.btn_new)
        self.running_badge = QLabel("")
        self.running_badge.setObjectName("badge-running")
        self._running_badge_state = "idle"  # gui15 #1：居临工作状态徽标（idle/running/awaiting/stopped）
        ll.addWidget(self.running_badge)
        ll.addWidget(self.mode_badge)
        root.addWidget(left)

        # gui-ux22 工单 02：中央区 = 水平 QSplitter 双槽——左槽 = 主线四件套（同现状单列），
        # 右槽 = 侧边会话四件套（各独立实例、绑自己的 pane 组）；右槽默认折叠（0 宽），
        # 开侧边会话展开、关闭折叠
        self.chat_splitter = QSplitter(Qt.Horizontal)
        self.chat_splitter.setObjectName("chat-splitter")

        # ---- 左槽：主线四件套（widget/属性名不变；左槽连接保持无参直连）
        left_slot = QWidget()
        ll = QVBoxLayout(left_slot)
        ll.setContentsMargins(4, 4, 4, 4)
        ll.setSpacing(2)
        self.stack = QStackedWidget()
        ll.addWidget(self.stack, stretch=1)

        self.status_label = StatusView("就绪")
        ll.addWidget(self.status_label)

        self.queue_strip = QueueStrip()
        ll.addWidget(self.queue_strip)
        self.queue_strip.pull_out_requested.connect(self._on_queue_pull_out)
        self.queue_strip.jump_requested.connect(self._on_queue_jump)

        self.image_strip = ImageStrip()
        ll.addWidget(self.image_strip)
        self.input_bar = InputBar()
        self.input_bar.edit.setPlaceholderText("输入消息（Enter 发送，Shift+Enter / Alt+Enter 换行）")
        self.input_bar.set_image_paste_hook(self._try_image_paste)
        self.input_bar.submit_requested.connect(self._on_input_submit)
        self.input_bar.cancel_requested.connect(self._cancel_active)
        ll.addWidget(self.input_bar)

        # ---- 右槽：侧边会话四件套（独立实例；side_pill 挪至右槽头部；
        # submit/取消/Esc/图片粘贴/补全等 hook 工单 03 再接）
        right_slot = QWidget()
        rl = QVBoxLayout(right_slot)
        rl.setContentsMargins(4, 4, 4, 4)
        rl.setSpacing(2)
        # side 会话「回主线」pill（side-chat 工单 03）：仅当前会话为 side 时可见
        self.side_pill = QPushButton("← 回主线")
        self.side_pill.setObjectName("side-pill")
        self.side_pill.hide()
        self.side_pill.clicked.connect(self._on_side_pill_clicked)
        rl.addWidget(self.side_pill)
        self.side_stack = QStackedWidget()
        rl.addWidget(self.side_stack, stretch=1)

        self.side_status = StatusView("就绪")
        rl.addWidget(self.side_status)

        self.side_queue_strip = QueueStrip()
        rl.addWidget(self.side_queue_strip)
        self.side_queue_strip.pull_out_requested.connect(lambda t: self._on_queue_pull_out(t, side=True))
        self.side_queue_strip.jump_requested.connect(lambda t: self._on_queue_jump(t, side=True))

        self.side_image_strip = ImageStrip()
        rl.addWidget(self.side_image_strip)
        self.side_input_bar = InputBar()
        self.side_input_bar.edit.setPlaceholderText("输入消息（Enter 发送，Shift+Enter / Alt+Enter 换行）")
        rl.addWidget(self.side_input_bar)

        self.chat_splitter.addWidget(left_slot)
        self.chat_splitter.addWidget(right_slot)
        self.chat_splitter.setCollapsible(0, False)  # 左槽（主线）始终可见
        self.chat_splitter.setCollapsible(1, True)   # 右槽无 side 时可收到 0 宽
        self.chat_splitter.setSizes([1, 0])          # 初始 = 现状单列布局
        root.addWidget(self.chat_splitter, 1)

        # gui-ux22 工单 02：槽归属（splitter 建好即设；__init__ 后段才调 _switch_to）
        self._main_slot_tid: str | None = None
        self._side_slot_tid: str | None = None

        self.setCentralWidget(central)
        self.resize(1060, 700)

        # 150ms 合批重渲（工单 03；逐 token 即时 = pane.render_strategy="instant"）
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(RENDER_BATCH_MS)
        self._render_timer.timeout.connect(self._flush_all_dirty)
        self._render_timer.start()

        # 补全弹层（工单 10：@ 路径 / / 命令 / /use skill 模糊；Tab 接受）
        self._completion_state = None
        self.completion_popup = CompletionPopup(self._on_completion_accept, self)
        self.completion_popup.hide()
        self.input_bar.edit.textChanged.connect(lambda: self._completion_timer.start())
        self.input_bar.edit.cursorPositionChanged.connect(lambda: self._completion_timer.start())
        self.input_bar.edit.textChanged.connect(lambda: self._save_slot_draft("main"))  # #1: 草稿随会话（每次输入即存）
        self.image_strip.changed.connect(lambda: self._save_slot_draft("main"))  # #1: 图片增删也进草稿
        # 逐键防抖（120ms singleShot 重启）：消除「每敲一键全量重扫+重挂弹层」的卡顿
        self._completion_timer = QTimer(self)
        self._completion_timer.setSingleShot(True)
        self._completion_timer.setInterval(120)
        self._completion_timer.timeout.connect(self._refresh_completion_now)
        # Tab/Esc 在输入框侧处理（弹层 NoFocus 不抢键盘；接受/关闭不进弹层）
        self.input_bar.set_tab_hook(self._completion_tab_accept)
        self.input_bar.set_esc_hook(lambda: self._on_esc_pressed("main"))  # 工单 03：主编辑裸 Esc 恒主槽语义（工单 13 三级不变）
        self._skills_cache: list = [0.0, None]  # [ts, catalog]，TTL 10s；None=未扫过
        # 工单 13 — Esc 三级语义（对标 TUI ESC_UNDO_WINDOW=1.5s）；gui-ux15 增取消→撤回级联（对标 TUI tui-ux15）：
        # ① 补全弹层开着→关弹层；② 回合进行中且未取消→Esc#1 prime、Esc#2 取消并立即 prime 撤回；
        # ③ 空闲或取消收尾（drain）→1.5s 内二 Esc 撤回一轮（取消已 prime 时单 Esc 即撤回）。
        # 单 Esc 永不退 app（TUI 同款约定）。
        self._esc_run_primed = False
        self._esc_run_primed_at = 0.0
        self._esc_undo_primed = False
        self._esc_undo_primed_at = 0.0
        self._esc_run_timer = QTimer(self)
        self._esc_run_timer.setSingleShot(True)
        self._esc_run_timer.timeout.connect(self._esc_run_disarm)
        self._esc_undo_timer = QTimer(self)
        self._esc_undo_timer.setSingleShot(True)
        self._esc_undo_timer.timeout.connect(self._esc_undo_disarm)
        # gui-ux22 工单 03：侧槽独立交互四件套（补全弹层/草稿 hooks/Esc 双级 primed）——
        # 与主槽 L314-343 同构镜像；侧条**不**接 esc_hook（c5：裸 Esc 走窗口 eventFilter，P-Q）
        self._last_side_input_text = ""
        self._side_completion_state = None
        self._side_completion_popup = CompletionPopup(self._on_side_completion_accept, self)
        self._side_completion_popup.hide()
        self.side_input_bar.edit.textChanged.connect(lambda: self._side_completion_timer.start())
        self.side_input_bar.edit.cursorPositionChanged.connect(lambda: self._side_completion_timer.start())
        self.side_input_bar.edit.textChanged.connect(lambda: self._save_slot_draft("side"))  # 镜像主条：侧草稿随侧会话
        self.side_image_strip.changed.connect(lambda: self._save_slot_draft("side"))
        # 逐键防抖（120ms singleShot 重启），与主槽同节拍
        self._side_completion_timer = QTimer(self)
        self._side_completion_timer.setSingleShot(True)
        self._side_completion_timer.setInterval(120)
        self._side_completion_timer.timeout.connect(lambda: self._refresh_completion("side"))
        # Tab 在侧输入条侧处理（弹层 NoFocus 不抢键盘）
        self.side_input_bar.set_tab_hook(self._side_completion_tab_accept)
        self.side_input_bar.edit.installEventFilter(self)  # c5：窗口级 filter 后装（只匹配侧编辑，见 P-Q 注释）
        self.side_input_bar.submit_requested.connect(self._on_side_input_submit)
        self.side_input_bar.cancel_requested.connect(lambda: self._cancel_slot("side"))
        self.side_input_bar.set_image_paste_hook(lambda: self._try_image_paste("side"))
        # 侧槽 Esc 双级 primed（属性名 _side_ 前缀，P-G _esc_attr 契约）
        self._side_esc_run_primed = False
        self._side_esc_run_primed_at = 0.0
        self._side_esc_undo_primed = False
        self._side_esc_undo_primed_at = 0.0
        self._side_esc_run_timer = QTimer(self)
        self._side_esc_run_timer.setSingleShot(True)
        self._side_esc_run_timer.timeout.connect(self._side_esc_run_disarm)
        self._side_esc_undo_timer = QTimer(self)
        self._side_esc_undo_timer.setSingleShot(True)
        self._side_esc_undo_timer.timeout.connect(self._side_esc_undo_disarm)
        # Ctrl+N 新建对话（TUI 键位迁移；_on_new_session_clicked 已含空态守卫）
        self._sc_new_session = QShortcut(QKeySequence("Ctrl+N"), self)
        self._sc_new_session.activated.connect(self._on_new_session_clicked)

    def closeEvent(self, event) -> None:
        # 关窗即停挂起的防抖/卸载 timer：singleShot 补全 timer 若留在父级 Qt app 里，
        # 会泵进下一个测试的事件循环并访问已析构/缺字段的 runtime（测试隔离卫生）
        self._completion_timer.stop()
        self._esc_run_timer.stop()
        self._esc_undo_timer.stop()
        # gui-ux22 工单 03：侧槽三个 timer 同停（与主槽同卫生：不泵进下一个测试事件循环）
        self._side_completion_timer.stop()
        self._side_esc_run_timer.stop()
        self._side_esc_undo_timer.stop()
        super().closeEvent(event)

    def _on_new_session_clicked(self) -> None:
        """新会话按钮：空态（无关联项目）时只提示，不崩。"""
        if self.presenter is None:
            self.status_label.setText("还没有关联项目，请先「打开项目 / 新建项目」")
            return
        self._switch_to(self.presenter.new_session_id())

    # ---- 工单 08：高级模式（Plan/Act 全局 · YOLO 线程级 · 撤回消息层）
    def _on_plan_toggled(self, on: bool) -> None:
        from src import plan_mode

        if self.presenter is None:
            self.plan_action.setChecked(False)
            return
        plan_mode.set_mode(self.presenter.runtime.permission_state, "plan" if on else "act")
        self._refresh_mode_badges()

    def _on_yolo_toggled(self, on: bool) -> None:
        from src import permissions

        if self.presenter is None:
            self.yolo_action.setChecked(False)
            return
        state = self.presenter.runtime.permission_state
        tid = self._mode_tid() or ""  # side 聚焦时 YOLO 写主线线程（side 只读不持有 YOLO）
        if on:
            permissions.yolo_on(state, tid)
        else:
            permissions.yolo_off(state, tid)
        self.status_label.setText(
            f"YOLO 已开启（{tid} 免审批；其他会话不受影响）" if on else "YOLO 已关闭"
        )
        self._refresh_mode_badges()

    def _on_proxy_toggled(self, on: bool) -> None:
        from src import permissions

        if self.presenter is None:
            self.proxy_action.setChecked(False)
            return
        state = self.presenter.runtime.permission_state
        tid = self._mode_tid() or ""  # side 聚焦时写主线线程（side 只读不持有 proxy）
        if on:
            permissions.proxy_on(state, tid)
        else:
            permissions.proxy_off(state, tid)
        self.status_label.setText(
            f"替我审批已开启（{tid} 自动放行安全审批、拦住危险审批；其他会话不受影响）" if on else "替我审批已关闭"
        )
        self._refresh_mode_badges()

    def _on_undo(self) -> None:
        # gui-ux22 工单 03：零参主入口保留（Esc ③ 主路径 / 菜单 / slash 兼容）；逐槽版 _on_undo_for
        # 菜单 undo = 当前焦点槽的主线语义（对标 TUI「undo 作用当前焦点 pane」）；offscreen 无焦点回 main
        self._on_undo_for(self._slot_tid(self._focus_slot()))

    def _on_undo_for(self, tid: str | None) -> None:
        if not tid:
            return
        b = self.presenter.bridge
        agent = self.presenter.runtime.agent

        def _run() -> str:
            # gui-ux16（对标 codex）：先取后撤——undo 之后被撤消息已不在 checkpoint，
            # get_state 的最近 human 变成上上轮，所以必须在 undo 前抓「即将撤回的那条」；
            # 成功才回填（契约：成功 ⇔ 以「已撤回」开头，见 commands.undo docstring）
            restored = commands.last_user_input(agent, tid)
            msg = commands.undo(agent, tid)
            b.rebuild_pane.emit(tid)  # 主线程重建 pane 记录（worker 不碰 widget）
            if msg.startswith("已撤回") and restored:
                b.input_set.emit(tid, restored)  # 队列信号 → 主线程按被撤回会话的槽写输入框
            if msg.startswith("已撤回"):
                # ADR-0014: 撤到空白 → 清该会话压缩基线并去 🗜 标（防屏幕残影）
                from src.gui import compact_baseline, replay

                try:
                    live = replay.thread_record(agent, tid)
                    if not any(r.kind in ("user", "ai") for r in live):
                        compact_baseline.clear_baseline(
                            self.presenter.runtime.config.project_root, tid
                        )
                        self.presenter.session_registry.set_compacted(tid, False)
                except Exception:  # noqa: BLE001 — 展示层清理不影响撤回
                    pass
            return msg

        self.presenter.run_command(_run, tid)

    def _on_set_auto_compaction(self) -> None:
        """高级菜单: auto_compaction 上下文自动压缩阈值（写**全局** jarvis.json，agent 重建后生效）"""
        if self.presenter is None:
            self.status_label.setText(
                "当前没有活动项目，请先「打开项目 / 新建项目」后再设置自动压缩阈值。"
            )
            return
        cfg = self.presenter.runtime.config
        current = int(getattr(cfg, "auto_compaction", 0) or 0)
        from PySide6.QtWidgets import QInputDialog

        # 写入目标 = 全局 ~/.jarvis/jarvis.json（auto_compaction 为全局配置，对所有项目生效；
        # 预填值 current 仍取活动项目合并后的 Config——它才是该项目实际生效值）
        # PySide6 SIP 绑定不支持 min=/max= keyword（实证：getInt(..., min=0) 抛
        # AttributeError: unsupported keyword 'min'；value=/step= 可用）→ 全位置传参
        value, ok = QInputDialog.getInt(
            self,
            "自动压缩上下文阈值（全局配置）",
            "上下文 token 数超过该值时自动压缩历史（0 = 关闭）",
            current, 0, 200000, 1000,
        )
        if not ok:
            return
        from src.config import save_auto_compaction

        try:
            written = save_auto_compaction(value)
        except OSError as exc:
            self.status_label.setText("自动压缩阈值写入失败: " + str(exc))
            return
        self.status_label.setText(
            "自动压缩阈值 = " + str(value)
            + "（全局配置，对所有项目生效）已写入 " + str(written)
            + "（重启应用后生效；若项目级 jarvis.json 显式配置了 auto_compaction，该项目将覆盖全局值）"
        )

    def _merged_display_records(self, tid: str) -> list:
        """ADR-0014 压缩基线：压缩前历史记录（基线文件）+ 当前 live 记录 合并展示。

        /compact（或自动压缩）后 token 已压缩、旧历史不在 checkpoint，UI 用
        baseline+live 合并保持屏幕上的历史连续性（对标 codex：token 可压缩、
        显示记录仍在）。
        """
        from src.gui import compact_baseline, replay

        agent = self.presenter.runtime.agent
        root = self.presenter.runtime.config.project_root
        try:
            base = compact_baseline.load_baseline(root, tid)
        except Exception:  # noqa: BLE001 — 展示增强，失败只回落 live
            base = []
        try:
            live = replay.thread_record(agent, tid)
        except Exception:  # noqa: BLE001 — live 取失败回落仅 baseline
            live = []
        return list(base) + list(live)

    def _rebuild_pane(self, tid: str) -> None:
        # #4：undo/重建会拆掉审批卡片 widget；若 worker 仍停在 CardSession.wait，
        # 必须唤醒放弃（gate 才能 finish），否则该 thread 后续消息永排队不发出。
        if self.presenter is not None:
            self.presenter.wake_parked(tid)
        p = self.panes.get(tid)
        if p is None:
            return
        try:
            p.rebuild_from_records(self._merged_display_records(tid))
        except Exception:  # noqa: BLE001 — 重建失败保留原 pane，不崩 app
            pass

    def _on_input_set(self, tid: str, text: str) -> None:
        """undo 回填（gui-ux16；gui-ux22 03 双参）：被撤回的用户消息进「被撤回会话」所属槽的输入框。

        双槽下 active_tid 可能已漂移到侧会话，按 tid 路由才不会把主线 undo 的回填错写进侧输入框。
        """
        self._slot_input_widgets(self._slot_of_tid(tid))[0].fill_text(text)

    # ---- 工单 09：时间旅行（渲染入口）
    def _on_snapshot(self) -> None:
        tid = self.active_tid
        if not tid:
            return
        agent = self.presenter.runtime.agent

        def _run() -> str:
            return commands.snapshot(agent, tid)

        self.presenter.run_command(_run, tid)

    def _on_snapshots_list(self) -> None:
        self._show_text("文件快照", commands.list_snapshots())

    # ---- 工单 10：命令菜单 / 补全 / 主题 / MCP / 定时任务
    def _build_command_menu(self, menu) -> None:
        from src.slash_completion import SLASH_COMMANDS

        for c in SLASH_COMMANDS:
            act = menu.addAction(c.usage)
            act.setToolTip(c.summary)
            usage = c.usage
            act.triggered.connect(lambda _on=False, u=usage: self._route_slash(u))

    def _on_filter_commands(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        from src.slash_completion import SLASH_COMMANDS, filter_commands

        q, ok = QInputDialog.getText(self, "筛选命令", "关键词（留空=全部）:")
        if not ok:
            return
        cmds = filter_commands(SLASH_COMMANDS, q.strip())
        lines = "\n".join(f"{c.usage}  — {c.summary}" for c in cmds) or "（无匹配）"
        self._show_text(f"命令（{q}）", lines)

    def _probe_ollama(self) -> bool:
        """Ollama 可达性（2s 超时，任何异常 = 不可达；注入点便于测试跳过）。"""
        import httpx

        base = self.presenter.runtime.config.rag_ollama_base_url or "http://localhost:11434"
        try:
            r = httpx.get(f"{base.rstrip('/')}/api/tags", timeout=2.0)
            return r.status_code == 200
        except Exception:
            return False

    def _on_doctor(self) -> None:
        if self.presenter is None:
            self.status_label.setText("还没有关联项目，请先「打开项目 / 新建项目」")
            return
        from src.gui import doctor

        rt = self.presenter.runtime
        gate = getattr(rt, "gate", None)
        rows = doctor.build_doctor_report(
            rt.config,
            llm=self._llm,
            key_store=self._key_store,
            ollama_reachable=self._probe_ollama(),
            mcp_tool_count=rt.mcp_tool_count,
            scheduler_running=bool(gate and gate.enabled),
        )
        dlg = doctor.make_doctor_dialog(rows, self)
        dlg.exec()

    def _execute_slash(self, raw: str, tid: str | None = None) -> None:  # noqa: C901
        tid = tid or self.active_tid
        if not tid:
            return
        agent = self.presenter.runtime.agent
        state = self.presenter.runtime.permission_state
        b = self.presenter.bridge
        first = raw.lstrip().split(None, 1)[0]

        def _run() -> str:  # noqa: C901
            # ADR-0014: 会话正在执行中禁止手动 /compact（压缩会覆盖历史，
            # 并发回合会丢失压缩边界）——直接拒绝并提示
            if first == "/compact" and self.presenter.gate.is_running(tid):
                return "本会话正在执行中，请等回合结束后再 /compact（或先停止当前回合）"
            # ADR-0014: /compact 前快照压缩前历史记录（压缩后展示基线）
            pre = []
            if first == "/compact":
                from src.gui import replay

                try:
                    pre = replay.thread_record(agent, tid)
                except Exception:  # noqa: BLE001 — 快照失败不挡压缩
                    pre = []
            text, new_tid, replay_cid = commands.dispatch_command(
                agent, tid, raw, None,
                vault_path=self.presenter.runtime.config.vault_path,
                permission_state=state,
            )
            if replay_cid:
                self.presenter.start_replay(new_tid or tid, replay_cid)
            elif new_tid:
                b.switch_session.emit(new_tid, f"已切换到会话 {new_tid}")
            if text:
                b.notify.emit(text)
            # ADR-0014: /compact 成功 → 压缩前记录追加进基线文件 + 标记 🗜
            if first == "/compact" and text and text.startswith("已压缩上下文"):
                from src.gui import compact_baseline

                root = self.presenter.runtime.config.project_root
                try:
                    compact_baseline.save_baseline(
                        root, tid, compact_baseline.load_baseline(root, tid) + pre
                    )
                    self.presenter.session_registry.set_compacted(tid, True)
                except Exception:  # noqa: BLE001 — 基线写失败不影响压缩结果
                    pass
            # /yolo、/proxy 改的是共享 permission_state：worker 完成后回主线程重同步
            # 菜单勾选 / [YOLO][PROXY] 徽标（_refresh_mode_badges 单一同步点；状态栏由 notify 承载）
            if first in ("/yolo", "/proxy"):
                b.sync_modes.emit()
            # diagnosing-bugs /goal 修复：/goal 族 → 状态行常驻目标行（status 信号按槽路由，
            # 非瞬态 notify）+ 徽标刷新（[GOAL]）+ 链重启（create/resume kick 经 start_turn）
            if first == "/goal":
                b.status.emit(tid, commands.goal_text(tid))
                b.sync_modes.emit()
                kick = commands.goal_kick_prompt(tid, raw)
                if kick is not None:
                    self.presenter.start_turn(tid, kick)
            return text or ""

        self.presenter.run_command(_run, tid)

    def _on_scheduler_panel(self) -> None:
        if self.presenter is None:
            self.status_label.setText("\u8fd8\u6ca1\u6709\u5173\u8054\u9879\u76ee\uff0c\u65e0\u6cd5\u6253\u5f00\u5b9a\u65f6\u4efb\u52a1\u9762\u677f")
            return
        from src.gui.scheduler_panel import SchedulerPanel

        SchedulerPanel(self.presenter, self).exec()

    def _build_mcp_menu(self, menu) -> None:
        if self.presenter is None:
            act = menu.addAction("\uff08\u5c1a\u672a\u5173\u8054\u9879\u76ee\uff0cMCP \u672a\u52a0\u8f7d\uff09")
            act.setEnabled(False)
            return
        cfg = self.presenter.runtime.config
        servers = cfg.mcps or {}
        if not servers:
            act = menu.addAction("（未配置 mcps.servers）")
            act.setEnabled(False)
            return
        for name, spec in servers.items():
            enabled = spec.get("enabled", True) if isinstance(spec, dict) else True
            act = menu.addAction(f"{name}（{'启用' if enabled else '停用'}）")
            act.setEnabled(False)  # 只读展示；改 jarvis.json 的 mcps.servers 后重启生效
            act.setToolTip(str(spec))
        count = getattr(self.presenter.runtime, "mcp_tool_count", 0)
        if count:
            note = menu.addAction(f"已加载 {count} 个 MCP 工具（工具行带 server 前缀）")
            note.setEnabled(False)

    def _on_theme(self, theme: str) -> None:
        from PySide6.QtWidgets import QApplication

        from src.gui import theme as _theme

        _theme.save_theme(theme)
        _theme.apply_theme(QApplication.instance(), theme)
        for t, act in self._theme_items.items():
            act.setChecked(t == theme)

        self._refresh_mode_badges()
        self._apply_running_badge(self._running_badge_state)

    # ---- 补全（工单 10；2026-10-28 规格：无边框浮层 + 不挡输入框 + 无匹配提示
    #      + 不抢键盘（ToolTip/NoFocus）+ 逐键防抖 + skill 目录 TTL 缓存）
    def _skills_cached(self) -> list:
        import time

        if self.presenter is None:
            return []
        now = time.monotonic()
        ts, cached = self._skills_cache
        if cached is not None and now - ts < 10.0:
            return cached
        cat = self.presenter.skills_catalog()
        self._skills_cache = [now, cat if cat is not None else []]
        return self._skills_cache[1]

    def _refresh_completion(self, slot: str = "main") -> None:
        """gui-ux22 工单 03：逐槽补全刷新（120ms 防抖不变；各槽 popup 独立，仅焦点槽活跃）。"""
        from PySide6.QtWidgets import QApplication

        from src.gui.completion import has_query_no_match

        bar, _ = self._slot_input_widgets(slot)
        if slot == "side":
            popup, state_attr = self._side_completion_popup, "_side_completion_state"
        else:
            popup, state_attr = self.completion_popup, "_completion_state"
        if self.presenter is None:
            popup.hide()
            setattr(self, state_attr, None)
            return
        skills = self._skills_cached()
        state = resolve_for_input(
            bar.edit,
            skills=skills,
            config=self.presenter.runtime.config,
        )
        setattr(self, state_attr, state)
        if state.kind != "none":
            no_match = has_query_no_match(bar.edit, state)
            popup.show_items(state.items, no_match=no_match)
            # 弹层底边贴输入条上沿（不挡输入框）；上方放不下时翻到输入条下沿之下
            bar_geo = bar.geometry()
            anchor = bar.mapToGlobal(QPoint(0, 0))
            ph = popup.sizeHint().height()
            y = anchor.y() - ph - 4
            screen = QApplication.primaryScreen().availableGeometry()
            if y < screen.y() + 2:
                y = anchor.y() + bar_geo.height() + 4
            popup.move(anchor.x() + 4, y)
            popup.show()
        else:
            popup.hide()

    def _refresh_completion_now(self) -> None:
        # gui-ux22 工单 03：降级主槽委托（L325 timer / ticket 10 十二处调用点零改动）
        self._refresh_completion("main")

    def _side_completion_tab_accept(self) -> bool:
        """侧输入条裸 Tab：侧弹层开着且有候选 → 接受首项（True 消费）；否则 False 原生。"""
        return self._side_completion_popup.accept_top() if self._side_completion_popup.isVisible() else False

    def _on_side_completion_accept(self, insert: str) -> None:
        bar, _ = self._slot_input_widgets("side")
        if self._side_completion_state is not None:
            accept_suggestion(bar.edit, self._side_completion_state, insert)
        self._side_completion_popup.hide()
        self._side_completion_state = None
        self._refresh_completion("side")

    def _completion_tab_accept(self) -> bool:
        """输入框裸 Tab：弹层开着且有候选 → 接受首项（True 消费）；否则 False 原生。"""
        return self.completion_popup.accept_top() if self.completion_popup.isVisible() else False

    def _completion_esc_dismiss(self) -> bool:
        """输入框裸 Esc：弹层开着 → 关掉它（保留文本）；否则不消费。"""
        if self.completion_popup.isVisible():
            self.completion_popup.hide()
            return True
        return False

    def _on_completion_accept(self, insert: str) -> None:
        if self._completion_state is not None:
            accept_suggestion(self.input_bar.edit, self._completion_state, insert)
        self.completion_popup.hide()
        self._completion_state = None
        self._refresh_completion()

    def _on_time_travel_dialog(self) -> None:
        if not self.active_tid:
            return
        from src.gui.time_travel_dialog import TimeTravelDialog

        dlg = TimeTravelDialog(self.presenter, self.active_tid, self)
        dlg.exec()

    def _on_switch_session(self, new_tid: str, note: str) -> None:
        self._switch_to(new_tid)
        text = note or f"已切换到 {new_tid}"
        # #goal 06: 有 goal 记录的会话切换 → 状态行附带目标行
        from src import goals as _goals
        if _goals.goal_status(thread_id=new_tid) is not None:
            from src import commands as _commands
            text += "\n" + _commands.goal_text(new_tid)
        self.status_label.setText(text)

    def _show_text(self, title: str, text: str) -> None:
        make_text_dialog(title, text, self)

    def _refresh_mode_badges(self) -> None:
        from src import permissions, plan_mode

        state = self.presenter.runtime.permission_state
        # side 隔离：全局模式面（徽标 + 菜单勾选态）跟随主线会话 tid——side 被强制
        # 只读（effective_mode=plan）且不持有 YOLO，用 active_tid 会把主线徽标翻成
        # [Plan] 并清掉 YOLO 勾选（开侧边会话污染主对话的症状）。
        tid = self._mode_tid() or ""
        mode = plan_mode.effective_mode(state, tid)
        yolo = permissions.yolo_active(state, tid)
        proxy = permissions.proxy_active(state, tid)
        from src.gui import theme as _theme_mod

        tok = _theme_mod.current_tokens()
        html = f'<span style="color: {tok["ok"]}; font-weight: bold;">[{"Plan" if mode == "plan" else "Act"}]</span>'
        if yolo:
            html += f' <span style="color: {tok["negative"]}; font-weight: bold;">[YOLO]</span>'
        if proxy:
            html += f' <span style="color: {tok["ok"]}; font-weight: bold;">[PROXY]</span>'
        # diagnosing-bugs /goal 修复：goal 标签+状态徽标（thread 级存储，按 active_tid 显示；
        # side 会话强制只读无 goal 记录，与 _mode_tid() 侧边隔离正交）
        from src import goals as _goals
        g = _goals.goal_status(thread_id=(self.active_tid or ""))
        if g is not None:
            html += (f' <span style="color: {tok["ok"]}; font-weight: bold;">'
                     f'[GOAL] {g.turns_used}/{g.max_turns} {_goals.GOAL_STATUS_CN.get(g.status, g.status)}</span>')
        self.mode_badge.setText(html)
        # 菜单勾选态与真实状态同步（全局模式面随主线会话；side 聚焦/切换不污染）
        self.plan_action.blockSignals(True)
        self.plan_action.setChecked(plan_mode.current_mode(state) == "plan")
        self.plan_action.blockSignals(False)
        self.yolo_action.blockSignals(True)
        self.yolo_action.setChecked(yolo)
        self.yolo_action.blockSignals(False)
        self.proxy_action.blockSignals(True)
        self.proxy_action.setChecked(proxy)
        self.proxy_action.blockSignals(False)

    _BADGE_STATES: dict = {
        "awaiting": ("等待审批…", "warning"),
        "running": ("工作中…", "ok"),
        "stopped": ("已停止", "negative"),
        "idle": ("", ""),
    }

    def _refresh_running_badge(self) -> None:
        tid = self.active_tid or ""
        p = self.panes.get(tid)
        if p is not None and p.awaiting_card:
            state = "awaiting"
        elif self.presenter.gate.is_running(tid):
            state = "running"
        elif p is not None and p.stopped:
            state = "stopped"
        else:
            state = "idle"
        self._apply_running_badge(state)

    def _apply_running_badge(self, state: str) -> None:
        self._running_badge_state = state
        text, tok_key = self._BADGE_STATES.get(state, ("", ""))
        if not text:
            self.running_badge.setText("")
            self.running_badge.setStyleSheet("")
            return
        from src.gui import theme as _theme_mod

        tok = _theme_mod.current_tokens()
        self.running_badge.setText(f"● {text}")
        self.running_badge.setStyleSheet(
            f"color: {tok.get(tok_key, tok['text'])}; font-size: 12px; font-weight: bold;"
        )

    # ---- 会话栈
    def _ensure_pane(self, tid: str) -> ChatPane:
        if tid in self.panes:
            return self.panes[tid]
        p = ChatPane(tid)
        # 工单 06：冷建/首访旧会话 → 检查点完整记录重建（含工具行，默认折叠）
        try:
            p.rebuild_from_records(self._merged_display_records(tid))
        except Exception:  # noqa: BLE001 — 记录重建是增强，失败回落空 pane 不崩
            pass
        self._stack_for(tid).addWidget(p)  # gui-ux22 工单 02：按会话归属槽路由
        self.panes[tid] = p
        return p

    def _save_active_draft(self) -> None:
        """#1: 把当前未提交输入（文本+图片条）记为活动会话草稿（纯写 dict，无去重逻辑）。

        gui-ux22 工单 02：槽化后经 active_tid 所属槽保存（左右槽各有自己的输入件）。"""
        if self.active_tid is None:
            return
        self._save_slot_draft(self._slot_of_tid(self.active_tid))

    # ---- gui-ux22 工单 02：双槽布局 helpers（左槽 = 主线，右槽 = 侧边会话）
    def _slot_of_tid(self, tid: str | None) -> str:
        """会话归属槽：side 会话 → "side"；其余（含 None/presenter 缺失）→ "main"。"""
        if tid and self.presenter is not None and self.presenter.is_side(tid):
            return "side"
        return "main"

    def _stack_for(self, tid: str) -> QStackedWidget:
        """会话归属的 pane 栈（ChatPane re-parent 目标）。"""
        return self.side_stack if self._slot_of_tid(tid) == "side" else self.stack

    def _slot_input_widgets(self, slot: str) -> tuple:
        """指定槽的 (输入条, 图片条) 两件套（各槽独立实例）。"""
        if slot == "side":
            return self.side_input_bar, self.side_image_strip
        return self.input_bar, self.image_strip

    def _slot_status(self, slot: str) -> StatusView:
        """指定槽的状态行。"""
        return self.side_status if slot == "side" else self.status_label

    def _slot_tid(self, slot: str) -> str | None:
        """gui-ux22 工单 03：逐槽 tid；legacy 回落（只设 active_tid 的旧路径/测试，按槽归属路由）。"""
        tid = self._side_slot_tid if slot == "side" else self._main_slot_tid
        if tid is None and self.active_tid and self._slot_of_tid(self.active_tid) == slot:
            tid = self.active_tid
        # gui-ux22 双槽路由修复：stale side tid 兜底——一切漏清路径（如 slash 跨线程
        # close 后未清槽）下 side 槽视为无侧边会话，由调用方拒收（不回落主线）
        if tid is not None and slot == "side" and self.presenter is not None \
                and not self.presenter.is_side(tid):
            return None
        return tid

    def _mode_tid(self) -> str | None:
        """全局模式面（徽标/菜单勾选态/YOLO 写）跟随的主线会话 tid：side 聚焦时
        仍是主线 tid（plan 为全局键、side 强制只读不持有 YOLO）；空态回落 active_tid。"""
        return self._main_slot_tid or self.active_tid

    def _cancel_slot(self, slot: str) -> None:
        """gui-ux22 工单 03：逐槽取消（零参 _cancel_active 保留，实体走主槽）。"""
        tid = self._slot_tid(slot)
        if tid and self.presenter is not None:
            self.presenter.cancel(tid)

    def _esc_attr(self, slot: str) -> str:
        """逐槽 Esc primed 属性前缀：主 "_" / 侧 "_side_"（裸名四件套共享）。"""
        return "_side_" if slot == "side" else "_"

    def _esc_timers(self, slot: str) -> dict:
        if slot == "side":
            return {"run": self._side_esc_run_timer, "undo": self._side_esc_undo_timer}
        return {"run": self._esc_run_timer, "undo": self._esc_undo_timer}

    def _esc_disarm(self, slot: str, which: str) -> None:
        """逐槽解除 primed 标记（which ∈ run/undo；主槽与旧 _esc_run_disarm/_esc_undo_disarm 等价）。"""
        setattr(self, self._esc_attr(slot) + "esc_" + which + "_primed", False)

    def _esc_slot_esc_dismiss(self, slot: str) -> bool:
        """逐槽 ①：补全弹层开着 → 关掉（主槽必经 _completion_esc_dismiss，保留 monkeypatch 面）。"""
        if slot == "side":
            if self._side_completion_popup.isVisible():
                self._side_completion_popup.hide()
                return True
            return False
        return self._completion_esc_dismiss()

    def _esc_slot_banner(self, slot: str, text: str) -> None:
        """逐槽 Esc 状态行 banner（主槽落 status_label，逐字文案见 _on_esc_pressed）。"""
        self._slot_status(slot).setText(text)

    def _reset_side_esc_state(self) -> None:
        """gui-ux22 工单 03：侧槽折叠/切项目时复位两级 primed 与 timer（状态不跨会话带）。"""
        self._side_esc_run_primed = False
        self._side_esc_run_primed_at = 0.0
        self._side_esc_undo_primed = False
        self._side_esc_undo_primed_at = 0.0
        self._side_esc_run_timer.stop()
        self._side_esc_undo_timer.stop()

    def _side_esc_run_disarm(self) -> None:
        self._esc_disarm("side", "run")

    def _side_esc_undo_disarm(self) -> None:
        self._esc_disarm("side", "undo")

    def _update_slot_ownership(self, tid: str) -> None:
        """切换会话时更新左右槽 tid 归属（side 占右槽；主线 tid 取 side 的 parent 回填）。"""
        if self._slot_of_tid(tid) == "side":
            self._side_slot_tid = tid
            self._main_slot_tid = self.presenter.side_parent(tid) or self._main_slot_tid
        else:
            self._main_slot_tid = tid
            # side 工单 03：主线目标 -> 右槽绑该主线的 side child（无则清 None 防 stale）
            child = self.presenter.side_child(tid) if self.presenter is not None else ""
            self._side_slot_tid = child or None

    def _sync_slot_panes(self) -> None:
        """ChatPane re-parent：把全部 pane 移到应属的栈（同 pane 实例 per-thread 常驻，
        dirty flush / sticky-bottom 不变）。"""
        for tid, pane in list(self.panes.items()):
            target = self._stack_for(tid)
            if pane.parentWidget() is not target:
                pane.setParent(target)
                target.addWidget(pane)
        if self._main_slot_tid and self._main_slot_tid in self.panes:
            self.stack.setCurrentWidget(self.panes[self._main_slot_tid])
        if self._side_slot_tid and self._side_slot_tid in self.panes:
            self.side_stack.setCurrentWidget(self.panes[self._side_slot_tid])

    def _expand_side_slot(self) -> None:
        """开 side 会话：右槽展开半宽（QSplitter 手柄可自由调比例——原生行为）。"""
        self.chat_splitter.setSizes([1, 1])

    def _collapse_side_slot(self) -> None:
        """关 side 会话：右槽折叠 0 宽（布局回到现状单列）。"""
        self._side_slot_tid = None
        self.chat_splitter.setSizes([1, 0])
        self._reset_side_esc_state()  # gui-ux22 工单 03：折叠即复位侧槽 Esc 双级 primed
        self._refresh_side_pill()  # side 工单 03：pill 跟随右槽归属，折叠即同步清 pill

    def _save_slot_draft(self, slot: str) -> None:
        """#1 槽版：把指定槽未提交输入（文本+图片条）记为该槽 tid 会话的草稿。"""
        tid = self._side_slot_tid if slot == "side" else self._main_slot_tid
        if tid is None:
            return
        bar, imgs = self._slot_input_widgets(slot)
        self._drafts[tid] = (bar.edit.toPlainText(), list(imgs.paths()))

    def _switch_to(self, tid: str) -> None:
        self._save_active_draft()  # #1: 先记「上一个」会话的未提交草稿（此刻 active_tid 还指向旧会话）
        p = self._ensure_pane(tid)
        self.active_tid = tid
        self._update_slot_ownership(tid)
        self._sync_slot_panes()  # gui-ux22 工单 02：取代原 stack.setCurrentWidget(p)——各槽自设当前件
        # side 工单 03：右槽持 side 会话 ⇒ 确保其 pane 存在（_stack_for 路由 side_stack）
        if self._side_slot_tid:
            self._ensure_pane(self._side_slot_tid)
        self._sync_slot_panes()  # gui-ux22 工单 02：各槽自设当前件
        # gui-ux22 工单 02 + side 工单 03：状态驱动布局不变式——右槽展开 ⇔ 持有 side 会话
        # （主线目标有 side 重新展开其 child；无 side 折叠清 stale；开/关 side 路径幂等）
        if self._side_slot_tid:
            self._expand_side_slot()
        else:
            self._collapse_side_slot()
        p.stick = True
        p.snap_to_bottom()
        self._workspace.set_last_active(self._workspace.active_root(), tid)
        self.refresh_tree()
        bar, _ = self._slot_input_widgets(self._slot_of_tid(tid))
        bar.edit.setFocus()
        self._refresh_queue_strip()
        note = "（回合进行中，切走不影响执行）" if self.presenter.gate.is_running(tid) else ""
        # 打开该会话/项目 → 消费其完成标记
        arn = self._workspace.active_root()
        rn = normalize_root_key(arn) if arn is not None else None
        if rn is not None:
            for k in [k for k in self._sess_done if k[0] == rn]:
                self._sess_done.pop(k, None)
            self._proj_done.pop(rn, None)
        proj = self._active_project_name()
        self._slot_status(self._slot_of_tid(tid)).setText(f"{proj} · 会话 {tid}{note}" if proj else f"会话 {tid}{note}")
        self._refresh_mode_badges()
        self._refresh_running_badge()
        # #1: 恢复目标会话的未提交草稿（无记录 = 清空输入区与图片条）；
        # gui-ux22 工单 02：双槽各按自身 tid 恢复（tid=None 槽跳过、无草稿则清空该槽）
        if self._main_slot_tid is not None:
            bar_m, img_m = self._slot_input_widgets("main")
            text_m, imgs_m = self._drafts.get(self._main_slot_tid, ("", []))
            bar_m.edit.setPlainText(text_m)
            img_m.clear()
            for _img in imgs_m:
                img_m.add_image(_img)
        if self._side_slot_tid is not None:
            bar_s, img_s = self._slot_input_widgets("side")
            text_s, imgs_s = self._drafts.get(self._side_slot_tid, ("", []))
            bar_s.edit.setPlainText(text_s)
            img_s.clear()
            for _img in imgs_s:
                img_s.add_image(_img)
        self._refresh_side_pill()

    # ---- 项目树（工单 04：项目→会话；点项目名=切换，+/−=展开；右键各自菜单）
    def _active_session_rows(self) -> list[tuple[str, bool]]:
        """活动项目的会话行：置顶优先 + 归档过滤（同旧平铺逻辑）。返回 [(tid, is_active)]。"""
        reg = self.presenter.session_registry
        tids = self.presenter.session_ids()
        pinned: list[str] = []
        others: list[str] = []
        for tid in tids:
            if reg.is_archived(tid) and not self._show_archived:
                continue
            (pinned if reg.is_pinned(tid) else others).append(tid)
        ordered = pinned + others
        if self.active_tid and self.active_tid not in ordered:
            ordered = [self.active_tid] + ordered
        return [(tid, tid == self.active_tid) for tid in ordered]

    def _session_row_label(self, tid: str, active: bool, reg, gate, done_mark: str = "") -> str:
        mark = "▸ " if active else "   "
        pin = "★ " if reg.is_pinned(tid) else ""
        arch = "📁 " if reg.is_archived(tid) else ""
        compact_mark = "🗜 " if reg.is_compacted(tid) else ""
        run = " ⚡" if gate.is_running(tid) else ""
        side = "◇ " if (
            self.presenter is not None and self.presenter.is_side(tid)
        ) else ""
        return f"{mark}{done_mark}{side}{pin}{arch}{compact_mark}{self.presenter.session_label(tid)}{run}"

    def refresh_tree(self) -> None:
        """重建项目→会话树（活动项目=live 会话，非活动项目=只读会话名）。保留已展开项。"""
        tree = self.project_tree
        active = self._workspace.active_root()
        reg = self.presenter.session_registry if self.presenter is not None else None
        gate = self.presenter.gate if self.presenter is not None else None
        prev_expanded = {
            tree.topLevelItem(i).data(0, _PROJ_ROLE)
            for i in range(tree.topLevelItemCount())
            if tree.topLevelItem(i).isExpanded()
        }
        tree.clear()
        active_norm = str(Path(str(active))) if active is not None else None
        active_rn = normalize_root_key(active) if active is not None else None
        for root, name, pinned in self._workspace.projects():
            r = str(Path(root))
            rp_norm = normalize_root_key(root)
            proj_mark = {"ok": " ●", "fail": " ✗"}.get(self._proj_done.get(rp_norm), "")
            pitem = QTreeWidgetItem([f"{'★ ' if pinned else ''}{name}{proj_mark}"])
            pitem.setData(0, _PROJ_ROLE, r)
            pitem.setToolTip(0, r)
            tree.addTopLevelItem(pitem)
            is_active = active_norm is not None and r == active_norm
            if is_active:
                for tid, is_act in self._active_session_rows():
                    s_mark = {"ok": "● ", "fail": "✗ "}.get(
                        self._sess_done.get((active_rn, tid), "") if active_rn is not None else "", ""
                    )
                    leaf = QTreeWidgetItem([self._session_row_label(tid, is_act, reg, gate, done_mark=s_mark)])
                    leaf.setData(0, _TID_ROLE, tid)
                    leaf.setToolTip(0, tid)
                    pitem.addChild(leaf)
            else:
                running = set(self._workspace.running_sessions(root))
                for tid, name in self._workspace.sessions_for(root):
                    s_mark = {"ok": "● ", "fail": "✗ "}.get(self._sess_done.get((rp_norm, tid), ""), "")
                    run = " ⚡" if tid in running else ""
                    leaf = QTreeWidgetItem([f"{s_mark}{name}{run}"])
                    leaf.setData(0, _TID_ROLE, tid)
                    leaf.setToolTip(0, tid)
                    pitem.addChild(leaf)
            pitem.setExpanded(is_active or r in prev_expanded)
        self._select_active_leaf()
        self._refresh_empty_hint()
        self._refresh_side_pill()

    # 兼容旧信号/测试名（bridge refresh_sessions → 重建树）
    def refresh_sessions(self) -> None:
        self.refresh_tree()

    def _select_active_leaf(self) -> None:
        tree = self.project_tree
        for i in range(tree.topLevelItemCount()):
            pitem = tree.topLevelItem(i)
            for j in range(pitem.childCount()):
                leaf = pitem.child(j)
                if leaf.data(0, _TID_ROLE) == self.active_tid:
                    tree.setCurrentItem(leaf)
                    return

    def session_leaf_texts(self) -> list[str]:
        """全部会话叶子文本（测试 / 复用）：跨项目按树序。"""
        out: list[str] = []
        tree = self.project_tree
        for i in range(tree.topLevelItemCount()):
            pitem = tree.topLevelItem(i)
            for j in range(pitem.childCount()):
                out.append(pitem.child(j).text(0))
        return out

    def _teardown_panes(self) -> None:
        """切项目前清空旧项目的双槽 pane 栈（新项目的 thread 是另一套检查点库）。"""
        for p in list(self.panes.values()):
            p.setParent(None)
        self.panes.clear()
        while self.stack.count():
            self.stack.removeWidget(self.stack.widget(0))
        # gui-ux22 工单 02：右槽同样清空 + 槽归属复位 + 折叠回单列
        #（若新焦点是 side 会话，_switch_to 会按不变式重新展开）
        while self.side_stack.count():
            self.side_stack.removeWidget(self.side_stack.widget(0))
        self._main_slot_tid = None
        self._side_slot_tid = None
        self.chat_splitter.setSizes([1, 0])
        self._reset_side_esc_state()  # gui-ux22 工单 03：切项目同样复位侧槽 Esc 双级状态

    def _do_switch_project(self, root, focus_tid: str | None = None) -> None:
        """切到项目 root（关旧建新 + 打开 focus_tid / 上次活动 / 新会话）。"""
        root = Path(str(root))
        rp_norm = normalize_root_key(root)
        for k in [k for k in self._sess_done if k[0] == rp_norm]:
            self._sess_done.pop(k, None)
        self._proj_done.pop(rp_norm, None)
        if self._workspace.active_root() is not None and root == Path(str(self._workspace.active_root())):
            if focus_tid:
                self._switch_to(focus_tid)
            return
        pres = self._workspace.switch_project(root)
        if pres is None:
            self.refresh_tree()  # ADR-0015：剪枝/拒绝切换 → 刷新左树（陈旧项目消失；空态由 _refresh_empty_hint 提示）
            return
        self.presenter = pres
        self._compact_action.setEnabled(True)  # 空态→活跃：恢复自动压缩菜单项
        self._notifier.policy = self._active_policy()
        # 空态恢复：刚无关联项目时（启动落空态）切项目后重新启用输入区
        self.input_bar.edit.setEnabled(True)
        self.input_bar.btn_send.setEnabled(True)
        self._teardown_panes()
        self._update_title()
        target = focus_tid or self._workspace.pick_start(root) or pres.new_session_id()
        self._switch_to(target)
        self.refresh_tree()

    def _on_tree_item_clicked(self, item, _col: int) -> None:
        if item.parent() is None:  # 项目节点 = 目的地
            self._do_switch_project(item.data(0, _PROJ_ROLE))
        else:  # 会话叶子
            tid = item.data(0, _TID_ROLE)
            proj = item.parent().data(0, _PROJ_ROLE)
            if Path(str(proj)) != Path(str(self._workspace.active_root())):
                self._do_switch_project(proj, focus_tid=tid)
            else:
                self._switch_to(tid)

    def _on_tree_item_double_clicked(self, item, _col: int) -> None:
        # 项目节点：单击已是「切进」目的地，双击不再重复/改名（改名走右键）
        if item.parent() is None:
            return
        self._rename_session_item(item.data(0, _TID_ROLE))

    def _on_tree_context(self, pos) -> None:
        item = self.project_tree.itemAt(pos)
        if item is None:
            return
        if item.parent() is None:
            menu = self._build_project_menu(item.data(0, _PROJ_ROLE))
        else:
            menu = self._build_session_menu(item.data(0, _TID_ROLE))
        menu.exec(self.project_tree.mapToGlobal(pos))

    def _on_show_archived_toggled(self, on: bool) -> None:
        self._show_archived = on
        self.refresh_sessions()

    # ---- 会话改名（工单 05：双击改名即时生效 + 持久化；右键菜单共用）
    def _rename_session_item(self, tid: str) -> None:
        from PySide6.QtWidgets import QInputDialog

        cur = self.presenter.session_label(tid)
        new_title, okk = QInputDialog.getText(self, "重命名会话", "新名称:", text=cur)
        if okk and new_title.strip():
            self.presenter.rename_session(tid, new_title.strip())

    # ---- 项目改名 / 移除（工单 04：项目节点双击改名、右键移除=只删登记）
    def _rename_project_item(self, root) -> None:
        from PySide6.QtWidgets import QInputDialog

        cur = self._workspace.project_name(Path(str(root)))
        new_name, okk = QInputDialog.getText(self, "重命名项目", "新名称:", text=cur)
        if okk and new_name.strip():
            self._workspace.rename_project(Path(str(root)), new_name.strip())
            self.refresh_tree()

    def _remove_project_item(self, root) -> None:
        """从列表移除 = 同时解除该项目的占用（关 runtime / 停调度器 / 取消回合 / 清队列；
        项目文件一律不碰，用户随后即可删除文件夹）。

        返回值 = 新的活动项目根：非 None → 跟随（移除非活动项目 = 当前活动根，
        _do_switch_project 早退无操作）；None → 落空态（与启动时无活动项目同款处理）。
        """
        new_active = self._workspace.remove_project(Path(str(root)))
        if new_active is None:
            self._enter_empty_state()
        else:
            self._do_switch_project(Path(str(new_active)))
        self.refresh_tree()

    def _enter_empty_state(self) -> None:
        """空态（无活动项目）：置灰输入区 / 自动压缩菜单，清 pane，标题回落 JARVIS；
        空态提示由 refresh_tree 里的 _refresh_empty_hint 显示。打开/新建项目时由 _do_switch_project 恢复。"""
        self.presenter = None
        self.active_tid = None
        self._compact_action.setEnabled(False)
        self.input_bar.edit.setEnabled(False)
        self.input_bar.btn_send.setEnabled(False)
        self._notifier.policy = self._active_policy()
        self._teardown_panes()
        self._update_title()

    # ---- 项目右键菜单（重命名 / 置顶 / 资源管理器打开 / 移除）
    def _build_project_menu(self, root):
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        name = menu.addAction("重命名")
        name.triggered.connect(lambda: self._rename_project_item(root))
        pin = menu.addAction("取消置顶" if self._workspace.project_pinned(Path(str(root)))
                             else "置顶")
        pin.triggered.connect(lambda: self._workspace.set_project_pinned(
            Path(str(root)), not self._workspace.project_pinned(Path(str(root)))))
        explorer = menu.addAction("在资源管理器打开")
        explorer.triggered.connect(lambda: self._open_project_in_explorer(Path(str(root))))
        menu.addSeparator()
        remove = menu.addAction("从列表移除（不删文件）")
        remove.triggered.connect(lambda: self._remove_project_item(root))
        return menu

    def _open_project_in_explorer(self, root) -> None:
        import subprocess
        import sys

        p = str(Path(str(root)))
        if sys.platform.startswith("win"):
            import os

            os.startfile(p)  # noqa: S606 — 本地资源管理器
        else:  # 非 Windows（仓库主目标为 Windows）：无 shell 拼接，避免注入
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.run([opener, p], check=False)

    # ---- 工单 05：打开项目 / 新建项目 菜单
    def _build_open_project_menu(self, menu) -> None:
        # QMenu.aboutToShow 是无参信号：直接连 1 参槽会在信号触发时
        # 因缺少 menu 位置参数抛 TypeError（启动即崩），用 lambda 包一层。
        menu.aboutToShow.connect(lambda: self._populate_open_menu(menu))
        self._populate_open_menu(menu)

    def _populate_open_menu(self, menu) -> None:
        menu.clear()
        for root, name in self._workspace.recent():
            act = menu.addAction(str(name))
            act.triggered.connect(lambda _on=False, r=root: self._do_switch_project(r))
        if menu.actions():
            menu.addSeparator()
        open_act = menu.addAction("打开文件夹…")
        open_act.triggered.connect(self._open_project_dialog)

    def _open_project_dialog(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        chosen = QFileDialog.getExistingDirectory(self, "选择项目文件夹")
        if chosen:
            self._open_project(chosen)

    def _open_project(self, chosen) -> None:
        from src.gui.workspace import resolve_open_root

        d = resolve_open_root(chosen)
        if d.needs_init and not self._confirm_init(d.root):
            return
        root = self._workspace.open_dir(chosen)  # 解析 + 骨架 + 登记
        self._do_switch_project(root)

    def _confirm_init(self, root) -> bool:
        from PySide6.QtWidgets import QMessageBox

        ans = QMessageBox.question(
            self, "初始化项目", f"此目录还不是 JARVIS 项目，要初始化它吗？\n{root}"
        )
        return ans == QMessageBox.StandardButton.Yes

    def _new_project_dialog(self) -> None:
        from PySide6.QtWidgets import QFileDialog, QInputDialog

        parent = QFileDialog.getExistingDirectory(self, "选择项目父目录")
        if not parent:
            return
        name, ok = QInputDialog.getText(self, "新建项目", "项目名:")
        if not ok or not name.strip():
            return
        root = self._workspace.new_dir(name.strip(), parent)
        self._do_switch_project(root)

    # ---- 工单 05：标题 / 状态 显示活动项目名
    def _active_project_name(self) -> str:
        root = self._workspace.active_root()
        return self._workspace.project_name(root) if root is not None else ""

    def _update_title(self) -> None:
        name = self._active_project_name()
        self.setWindowTitle(f"JARVIS — {name}" if name else "JARVIS")

    def _refresh_empty_hint(self) -> None:
        if hasattr(self, "_empty_hint"):
            # 空态（无关联项目）或注册表无有效项目：都显示提示
            self._empty_hint.setVisible(self.presenter is None or not self._workspace.projects())

    def _build_session_menu(self, tid: str):
        from PySide6.QtWidgets import QMenu

        reg = self.presenter.session_registry
        menu = QMenu(self)
        share = menu.addAction("分享（复制 Markdown 全文）")
        share.triggered.connect(lambda: self._share_session_markdown(tid))
        download = menu.addAction("下载 Markdown…")
        download.triggered.connect(lambda: self._download_session_markdown(tid))
        menu.addSeparator()
        rename = menu.addAction("重命名")
        rename.triggered.connect(lambda: self._rename_session_item(tid))
        pin_on = reg.is_pinned(tid)
        pin = menu.addAction("取消置顶" if pin_on else "置顶")
        pin.triggered.connect(lambda: self.presenter.pin_session(tid, not pin_on))
        clone = menu.addAction("克隆会话")
        clone.triggered.connect(lambda: self._clone_session(tid))
        arch_on = reg.is_archived(tid)
        arch = menu.addAction("取消归档" if arch_on else "归档")
        arch.triggered.connect(lambda: self._archive_session(tid, not arch_on))
        menu.addSeparator()
        if self.presenter.is_side(tid):
            del_side = menu.addAction("删除侧边会话（回主线）")
            del_side.triggered.connect(lambda: self._delete_side_session(tid))
        else:
            open_side_act = menu.addAction("开侧边会话")
            open_side_act.triggered.connect(lambda: self._open_side_session(tid))
        delete = menu.addAction("删除会话")
        delete.triggered.connect(lambda: self._delete_session(tid))
        return menu

    def _session_markdown_text(self, tid: str) -> str:
        from datetime import datetime

        from src.gui.session_export import session_markdown

        title = self.presenter.session_label(tid)
        return session_markdown(
            self.presenter.runtime.agent,
            tid,
            title,
            now_text=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )

    def _share_session_markdown(self, tid: str) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self._session_markdown_text(tid))
        self.status_label.setText(f"已复制「{self.presenter.session_label(tid)}」Markdown 全文到剪贴板")

    def _download_session_markdown(self, tid: str) -> None:
        from PySide6.QtWidgets import QFileDialog

        title = self.presenter.session_label(tid)
        path, _ok = QFileDialog.getSaveFileName(
            self, "下载会话 Markdown", f"{title or tid}.md", "Markdown 文件 (*.md)"
        )
        if not path:
            return
        Path(path).write_text(self._session_markdown_text(tid), encoding="utf-8")
        self.status_label.setText(f"已导出 {path}")

    def _clone_session(self, tid: str) -> None:
        note, _new_tid = self.presenter.clone_session(tid)
        self.status_label.setText(note)

    def _archive_session(self, tid: str, on: bool) -> None:
        self.presenter.archive_session(tid, on)  # presenter 已发 refresh_sessions 信号
        # 归档且当前隐藏归档项 → 活动会话被移出列表时切到新会话
        if on and not self._show_archived and tid == self.active_tid:
            self._switch_to(self.presenter.new_session_id())

    def _delete_session(self, tid: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        ans = QMessageBox.question(
            self, "删除会话",
            f"删除会话「{self.presenter.session_label(tid)}」的全部对话历史？（不可恢复）",
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        was_active = tid == self.active_tid
        note = self.presenter.delete_session(tid)
        self.status_label.setText(note)
        if was_active:
            self._switch_to(self.presenter.new_session_id())

    # ---- 侧边会话（side-chat 工单 03）
    def _open_side_session(self, tid: str) -> None:
        note, new_tid = self.presenter.open_side(tid)
        self.status_label.setText(note)
        if new_tid:
            self._switch_to(new_tid)
            self._expand_side_slot()  # gui-ux22 工单 02：右槽展开

    def _delete_side_session(self, tid: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        ans = QMessageBox.question(
            self, "删除侧边会话",
            f"删除侧边会话「{self.presenter.session_label(tid)}」并返回主线？（不可恢复）",
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        note, parent = self.presenter.close_side(tid)
        self.status_label.setText(note)
        if parent:
            # side 工单 03：先切换再折叠，折叠置后覆盖 _switch_to 重推可能复活的 stale side_child
            self._switch_to(parent)
            self._collapse_side_slot()
        else:
            # gui-ux22 工单 03：无 parent 兜底（孤儿 side 会话删除等）——焦点回左槽输入条
            self._collapse_side_slot()
            self.input_bar.edit.setFocus()

    def _on_side_pill_clicked(self) -> None:
        """pill = 关闭 side 会话（关了就没了：删除会话并回主线；右键菜单同语义）。

        gui-ux22 双槽路由修复：pill 跟随右槽实际持有的 _side_slot_tid（右槽持 side
        会话即可见），不再跟随 active_tid——消除「pill 标在主对话输入框上」的错位。"""
        if self.presenter is None:
            return
        tid = self._side_slot_tid
        if tid is None or not self.presenter.is_side(tid):
            return
        note, parent = self.presenter.close_side(tid)
        if parent:
            self.status_label.setText(note)
            # side 工单 03：先切换再折叠，折叠置后覆盖 _switch_to 重推可能复活的 stale side_child
            self._switch_to(parent)
            self._collapse_side_slot()
        else:
            # 内核拒绝：不折叠真实开着的右槽，仅提示
            self.status_label.setText(note)
            self.input_bar.edit.setFocus()

    def _refresh_side_pill(self) -> None:
        if not hasattr(self, "side_pill") or self.presenter is None:
            return
        # gui-ux22 双槽路由修复：显示判定跟随右槽持有的 side tid，不依赖 active_tid
        sid = getattr(self, "_side_slot_tid", None)
        show = sid is not None and self.presenter.is_side(sid)
        if not show:
            self.side_pill.setVisible(False)
            return
        parent = self.presenter.side_parent(sid)
        tip = (
            commands.side_parent_status(
                self.presenter.runtime.agent,
                parent,
                self.presenter.runtime.permission_state,
            )
            if parent
            else "主线状态未知"
        )
        self.side_pill.setToolTip(f"{tip}（点击回主线并删除本 side 会话）")
        self.side_pill.setVisible(True)

    # ---- 图片粘贴（工单 07）：剪贴板图 / 图片路径 → 附件条
    def _try_image_paste(self, slot: str = "main") -> bool:
        from PySide6.QtWidgets import QApplication

        imgs = self._slot_input_widgets(slot)[1]
        st = self._slot_status(slot)
        cb = QApplication.clipboard()
        img = cb.image()
        if img is not None and not img.isNull():
            path = save_clipboard_image_to_temp(img)
            if path:
                imgs.add_image(path)
                st.setText("已添加图片附件（发送前可 ✕ 移除）")
                return True
        p = clipboard_image.looks_like_image_path(cb.text() or "")
        if p:
            imgs.add_image(p)
            st.setText("已添加图片附件")
            return True
        return False  # 普通文本走原生粘贴

    # ---- 发送 / 回合
    def _submit(self, slot: str = "main") -> None:
        st = self._slot_status(slot)
        bar, imgs = self._slot_input_widgets(slot)
        if self.presenter is None:
            st.setText("还没有关联项目，请先「打开项目 / 新建项目」")
            return
        # InputBar 已清空编辑框并 emit 原始多行文本（含换行，走 build_submission）
        raw = self._last_side_input_text if slot == "side" else self._last_input_text
        payload, note = commands.build_submission(
            raw, tuple(commands.virtual_path_mappings(self.presenter.runtime.config))
        )
        if note:
            st.setText(note)
            return
        if payload is None:
            return
        if self._route_slash(payload, slot):
            return
        images = imgs.paths()
        user_input, user_input_fallback, _ = build_image_submit(payload, images)
        tid = self._slot_tid(slot)
        if slot == "side" and (tid is None or not self.presenter.is_side(tid)):
            # 双槽路由修复：侧槽无（合法）side 会话时拒收——不回落到主线对话
            st.setText("还没有侧边会话，先在主对话 /side 开一个")
            return
        verdict = self.presenter.start_turn(
            tid, payload,
            user_input=user_input, user_input_fallback=user_input_fallback,
            images=images,  # #2: 排队载荷带图，回合结束重投时图片不丢
        )
        bar.set_cancel_enabled(verdict == "started")
        if verdict == "started":
            p = self._ensure_pane(tid)
            p.append_user(payload, images or None)
            st.setText("已发送，执行中…")
        else:
            # 排队：用户气泡等回合真正开跑（queued_flush）才进窗，期间固定在队列条
            st.setText("已排队，回合结束后自动续发")
        # #2 根因修复：提交后无条件清空图片条——排队载荷的图已存进队列 tuple（清空无损）；
        # 旧图片条残留到「切会话再提交」是图片发到错误对话的泄漏路径
        imgs.clear()
        self._refresh_queue_strip()

    # ---- slash 命令路由（工单 07）：输入框 /xxx 走本地命令，不再发给 AI
    def _route_slash(self, payload: str, slot: str = "main") -> bool:  # noqa: C901
        stripped = payload.lstrip()
        if not stripped.startswith('/'):
            return False
        # 空态守卫（同 _submit）：未关联项目时 /xxx 不进 dispatch（守卫最先 + 写 status_label：__new__ 空态测试面）
        if self.presenter is None:
            self.status_label.setText("还没有关联项目，请先「打开项目 / 新建项目」")
            return True
        st = self._slot_status(slot)
        cfg = self.presenter.runtime.config
        # 虚拟路径引用（/workspace/、/skills/ 等）仍发模型，不走命令
        if commands.is_virtual_path_reference(payload, commands.virtual_path_mappings(cfg)):
            return False
        first = stripped.split(None, 1)[0]
        tid = self._slot_tid(slot)
        if first == '/help':
            # GUI 专属：dispatch 命令表不含 /help（CLI/TUI 在分发前特判），走对话框（可滚动/可选中），不进状态栏
            self._show_text("命令帮助", commands.GUI_HELP)
            return True
        if first == '/exit':
            # 关窗退出；gui_main.main 的 finally 里 controller.shutdown() 兜底清理（checkpointer DB + 调度器）
            self.status_label.setText("正在退出…")
            self.close()
            return True
        if first == '/use':
            msg, err = commands.expand_use_command(cfg, payload)
            if err:
                st.setText(err)
                return True
            if tid is None:
                # 双槽路由修复：侧槽无（合法）side 会话时拒收，不建 None pane
                st.setText("还没有侧边会话，先在主对话 /side 开一个")
                return True
            p = self._ensure_pane(tid)
            p.append_user(payload, None)
            verdict = self.presenter.start_turn(tid, msg)
            self._slot_input_widgets(slot)[0].set_cancel_enabled(verdict == 'started')
            st.setText('使用 skill…')
            return True
        if first == '/doctor':
            # 自检走对话框（可滚动/可选中），不塞状态栏（多行文本会顶爆布局、把输入框挤出屏）
            self._on_doctor()
            return True
        if first == '/undo':
            # gui-ux16：输入框/菜单 /undo 与 Esc 级联统一走 _on_undo——检查点撤回 + pane
            # 重建 + 输入框回填一体；不再落入 _execute_slash（该路径只 notify 不重建 pane）
            if len(stripped.split(None, 1)) > 1:
                st.setText(
                    "用法: /undo（无参）；/undo 只撤回最近 1 条，多轮请反复调用"
                )
                return True
            self._on_undo_for(tid)  # gui-ux22 工单 03：按槽 tid（侧槽 /undo 作用于 side tid）
            return True
        if first == '/side':
            # gui-ux22 双槽路由修复：/side 与 /side close 走主线程直调 presenter
            #（镜像树右键路径），不再落 worker 跨线程 emit——右槽展开与
            # pane 重定位同帧完成，消除 slot 归属错位（pill 标错对话）
            parts = stripped.split(None, 1)
            if len(parts) > 1 and parts[1].lower() != 'close':
                st.setText('用法: /side 或 /side close')
                return True
            if len(parts) > 1:
                # /side close：右槽折叠清 stale tid；仅内核成功（parent 非空）才折叠
                stid = self._slot_tid('side')
                if stid is None:
                    st.setText('还没有侧边会话，无需关闭')
                    return True
                note, parent = self.presenter.close_side(stid)
                st.setText(note)
                if parent:
                    # side 工单 03：先切换再折叠，折叠置后覆盖 _switch_to 重推可能复活的 stale side_child
                    self._switch_to(parent)
                    self._collapse_side_slot()
                else:
                    # 内核拒绝（如 tid 已失 side 身份）：不折叠真实开着的右槽
                    self.input_bar.edit.setFocus()
                return True
            # /side：从主槽 tid 开侧边会话
            mtid = self._slot_tid('main') or tid
            note, new_sid = self.presenter.open_side(mtid)
            st.setText(note)
            if new_sid:
                self._switch_to(new_sid)
                self._expand_side_slot()
            return True
        self._execute_slash(payload, tid=tid)  # gui-ux22 工单 03：按槽 tid（缺省回落 active_tid）
        return True

    def _on_input_submit(self, raw: str) -> None:
        self._last_input_text = raw
        self._submit()

    def _on_side_input_submit(self, raw: str) -> None:
        # gui-ux22 工单 03：侧槽提交（独立草稿字段；slot 路由进 _submit）
        self._last_side_input_text = raw
        self._submit("side")

    def _cancel_active(self) -> None:
        # gui-ux22 工单 03：零参名保留（L261 主条 cancel_requested 连线语义逐字等价）
        self._cancel_slot("main")

    # ---- 工单 13：Esc 三级（补全弹层 / 运行中取消 / 取消后或空闲撤回；gui-ux15 取消→撤回级联，对标 TUI tui-ux15）
    ESC_UNDO_WINDOW = 1.5

    def _esc_run_disarm(self) -> None:
        self._esc_run_primed = False

    def _esc_undo_disarm(self) -> None:
        self._esc_undo_primed = False

    def _on_esc_pressed(self, slot: str = "main") -> bool:
        """裸 Esc 统一入口（主条 esc_hook + 窗口 keyPressEvent 兜底 + 侧条窗口 eventFilter，工单 03）。

        True=已消费；False=不处理（原生无操作；单 Esc 永不退 app）。

        gui-ux15 Esc 级联（对标 TUI tui-ux15 三段）+ gui-ux22 工单 03 逐槽化：
        primed 时间戳/状态行/取消/撤回均按槽独立（主槽零参调用语义逐字等价）。"""
        import time as _time

        # ① 本槽补全弹层开着 → 先关弹层（主槽必经 _completion_esc_dismiss，保留 monkeypatch 面）
        if self._esc_slot_esc_dismiss(slot):
            return True
        now = _time.monotonic()
        tid = self._slot_tid(slot)
        running = bool(tid and self.presenter.gate.is_running(tid))
        # drain：取消已请求、worker 收尾中（gate 未释放）——不再重新武装「取消」，落入撤回段
        draining = running and self.presenter.gate.peek_cancelled(tid)
        pfx = self._esc_attr(slot)  # 逐槽属性前缀（裸名四件套共享）
        # ② 回合进行中且未取消：1.5s 内二 Esc → 取消；取消成功即 prime 撤回（级联第三击）
        if running and not draining:
            self._esc_disarm(slot, "undo")
            if getattr(self, pfx + "esc_run_primed") and now - getattr(self, pfx + "esc_run_primed_at") < self.ESC_UNDO_WINDOW:
                setattr(self, pfx + "esc_run_primed", False)
                self._esc_timers(slot)["run"].stop()
                self._cancel_slot(slot)
                # gui-ux15：取消完成 → 直接进撤回 prime，第三击 Esc（drain 中或空闲）即撤回
                setattr(self, pfx + "esc_undo_primed", True)
                setattr(self, pfx + "esc_undo_primed_at", now)
                self._esc_timers(slot)["undo"].start(int(self.ESC_UNDO_WINDOW * 1000))
                self._esc_slot_banner(
                    slot,
                    f"已取消；{self.ESC_UNDO_WINDOW:g}s 内再按一次 Esc 可撤回上一轮",
                )
                return True
            setattr(self, pfx + "esc_run_primed", True)
            setattr(self, pfx + "esc_run_primed_at", now)
            self._esc_timers(slot)["run"].start(int(self.ESC_UNDO_WINDOW * 1000))
            self._esc_slot_banner(slot, "再按一次 Esc 取消执行")
            return True
        # ③ 空闲或取消收尾（drain）：1.5s 内二 Esc → 撤回最近一轮（对标 TUI 双 Esc 撤回）
        if tid:
            self._esc_disarm(slot, "run")
            if getattr(self, pfx + "esc_undo_primed") and now - getattr(self, pfx + "esc_undo_primed_at") < self.ESC_UNDO_WINDOW:
                setattr(self, pfx + "esc_undo_primed", False)
                self._esc_timers(slot)["undo"].stop()
                self._on_undo_for(tid)
                self._esc_slot_banner(slot, "已撤回最近一轮")
                return True
            setattr(self, pfx + "esc_undo_primed", True)
            setattr(self, pfx + "esc_undo_primed_at", now)
            self._esc_timers(slot)["undo"].start(int(self.ESC_UNDO_WINDOW * 1000))
            self._esc_slot_banner(slot, "再按一次 Esc 撤回最近一轮")
            return True
        return False

    def keyPressEvent(self, event):  # noqa: N802 — 非输入焦点路径的裸 Esc 兜底
        from PySide6.QtGui import QKeyEvent

        if isinstance(event, QKeyEvent) and event.key() == Qt.Key_Escape and not event.modifiers():
            # gui-ux22 工单 03：逐槽兜底——键盘焦点在右槽（pane/输入条/图片条）走侧槽，否则主槽
            slot = self._focus_slot()
            if self._on_esc_pressed(slot):
                event.accept()
                return
        super().keyPressEvent(event)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        # gui-ux22 工单 03（c5 侧编辑裸 Esc 无双触发）：侧条**不**接 esc_hook（InputBar 自身
        # filter 在 hook=None 时放行裸 Esc），窗口级 filter 后装、只匹配 side_input_bar.edit，
        # 消费后链上无第二处处理；非 Esc 事件走原生链。主编辑条保持 esc_hook 路径（工单 13 语义不变）。
        from PySide6.QtGui import QKeyEvent

        if (
            obj is self.side_input_bar.edit
            and isinstance(event, QKeyEvent)
            and event.key() == Qt.Key_Escape
            and not event.modifiers()
        ):
            if self._on_esc_pressed("side"):
                event.accept()
                return True
        return super().eventFilter(obj, event)

    def _focus_slot(self) -> str:
        """gui-ux22 工单 03：当前键盘焦点属哪槽（右槽任意子件 → side；否则 main）。"""
        from PySide6.QtWidgets import QApplication

        w = QApplication.focusWidget()
        if w is None:
            return "main"
        cur = w
        while cur is not None:
            if cur is self.side_stack or cur is self.side_input_bar or cur is self.side_image_strip:
                return "side"
            cur = cur.parentWidget()
        return "main"

    def _flush_all_dirty(self) -> None:
        for p in self.panes.values():
            p.flush_dirty()

    # ---- 桥接（worker → 主线程渲染）
    def _wire_bridge(self) -> None:
        b = self.bridge
        b.message_delta.connect(self._on_delta)
        b.message_end.connect(self._on_msg_end)
        b.fallback.connect(self._on_fallback)
        b.tool_call.connect(self._on_tool)
        b.subagent.connect(self._on_subagent)
        b.thinking.connect(self._on_thinking)
        b.status.connect(self._on_status)
        b.turn_started.connect(self._on_turn_started)
        b.turn_done.connect(self._on_turn_done)
        b.refresh_sessions.connect(self.refresh_sessions)
        b.notify.connect(self._on_notify)
        b.create_card.connect(self._on_create_card)
        b.focus_input.connect(self._on_focus_input)
        b.rebuild_pane.connect(self._rebuild_pane)
        b.input_set.connect(self._on_input_set)
        b.switch_session.connect(self._on_switch_session)
        b.task_done.connect(self._on_task_done)
        b.queued_flush.connect(self._on_queued_flush)
        b.sync_modes.connect(self._on_sync_modes)

    def _on_create_card(self, tid: str, payload, card_id: str) -> None:
        from src.gui.cards import card_widget_from_payload

        p = self.panes.get(tid)
        if p is None:
            p = self._ensure_pane(tid)
        p.append_card(card_widget_from_payload(payload))
        p.awaiting_card = True
        self._refresh_running_badge()

    def _on_focus_input(self, tid: str) -> None:
        p = self.panes.get(tid)
        if p is not None:
            p.awaiting_card = False
        self._slot_input_widgets(self._slot_of_tid(tid))[0].edit.setFocus()
        self._refresh_queue_strip()
        self._refresh_running_badge()

    def _on_delta(self, tid: str, delta: str) -> None:
        p = self.panes.get(tid)
        if p is not None:
            p.ai_delta(delta)

    def _on_msg_end(self, tid: str, text: str) -> None:
        p = self.panes.get(tid)
        if p is not None:
            p.ai_end(text)

    def _on_fallback(self, tid: str, text: str) -> None:
        p = self.panes.get(tid)
        if p is not None:
            p.append_fallback(text)

    def _on_tool(self, tid, name, args, err, output, depth) -> None:
        p = self.panes.get(tid)
        if p is not None:
            p.append_tool(name, args, err, output, depth)

    def _on_subagent(self, tid, name, status, depth) -> None:
        p = self.panes.get(tid)
        if p is not None:
            p.append_subagent(name, status, depth)

    def _on_thinking(self, tid: str, delta: str) -> None:
        p = self.panes.get(tid)
        if p is not None:
            p.thinking_delta(delta)

    def _on_status(self, tid: str, text: str) -> None:
        p = self.panes.get(tid)
        if p is not None and text.startswith("已停止"):
            p.stopped = True
        if tid == self.active_tid:
            self._slot_status(self._slot_of_tid(tid)).setText(text)
            self._refresh_running_badge()

    def _on_turn_started(self, tid: str) -> None:
        p = self.panes.get(tid)
        if p is not None:
            p.running = True
            p.stopped = False
        self._slot_input_widgets(self._slot_of_tid(tid))[0].set_cancel_enabled(True)
        arn = self._workspace.active_root()
        if arn is not None:
            self._sess_done.pop((normalize_root_key(arn), tid), None)
        self.refresh_sessions()
        self._refresh_queue_strip()
        self._refresh_running_badge()

    def _on_turn_done(self, tid: str, ok: bool) -> None:
        p = self.panes.get(tid)
        if p is not None:
            p.running = self.presenter.gate.is_running(tid)
        # gui-ux22 工单 02：左右输入条各按自身槽 tid 判定（弃 running_threads() 全局判定——
        # side 回合结束不应误关主线取消钮，反之亦然）
        gate = self.presenter.gate
        self.input_bar.set_cancel_enabled(bool(self._main_slot_tid) and gate.is_running(self._main_slot_tid))
        self.side_input_bar.set_cancel_enabled(bool(self._side_slot_tid) and gate.is_running(self._side_slot_tid))
        self.refresh_sessions()
        self._refresh_queue_strip()
        self._refresh_running_badge()
        # #goal 06: 有 goal 记录的会话回合结束 → 槽状态行显示目标进度
        from src import goals as _goals
        if _goals.goal_status(thread_id=tid) is not None:
            from src import commands as _commands
            self._slot_status(self._slot_of_tid(tid)).setText(_commands.goal_text(tid))

    def _on_notify(self, text: str) -> None:
        # 状态栏保留换行：StatusView 自动换行 + 限高内滚 + 可复制，不再压平多行长文本
        self.status_label.setText(text.replace("\r\n", "\n"))

    def _on_sync_modes(self) -> None:
        # 命令 worker 完成后的模式面重同步（/yolo 等改 permission_state 的命令）：
        # 菜单勾选 + [YOLO] 徽标以共享 state 为唯一事实源（_refresh_mode_badges 单一同步点）
        self._refresh_mode_badges()

    def _on_task_done(self, ev) -> None:
        """任务完成（会话回合/定时任务，含后台项目）→ 树标记 + 三通道通知（主线程 queued 信号端）。"""
        rn = normalize_root_key(ev.root)
        status = "ok" if ev.ok else "fail"
        self._sess_done[(rn, ev.thread_id)] = status
        self._proj_done[rn] = status
        self._notifier.fire(ev)
        self.refresh_tree()


    # ---- 待发队列条（gui15 G5）：排队消息固定在输入框上方，回合真正开跑时才入窗
    def _slot_queued_items(self, slot: str) -> list:
        """指定槽队列条应显示的排队条目（各槽按自身 tid；无 tid → 空条）。gui-ux22 工单 02。"""
        tid = self._side_slot_tid if slot == "side" else self._main_slot_tid
        if not (self.presenter and tid):
            return []
        return self.presenter.gate.queued_texts(tid)

    def _refresh_queue_strip(self) -> None:
        self.queue_strip.set_items(self._slot_queued_items("main"))
        self.side_queue_strip.set_items(self._slot_queued_items("side"))

    def _on_queued_flush(self, tid: str, text: str, images: list[str] | None) -> None:
        """排队消息重投入门 → 用户气泡此刻才进对话窗（随附图片不丢）。"""
        self._ensure_pane(tid).append_user(text, images or None)
        self._refresh_queue_strip()

    def _on_queue_jump(self, text: str, side: bool = False) -> None:
        """插队（codex queued-chip Steer 语义）：撤出 FIFO 队列 → 立即注入插队缓存
        （JumpInRegistry），当前回合的下一步模型调用前由
        MessageQueueJumpInMiddleware drain 注入——不等回合结束。带图条目以
        路径引用 fallback 文本形式入缓存（registry 只存 str）。
        gui-ux22 工单 02：side 参数路由到右槽（右槽队列条信号带 side=True）。"""
        if not self.presenter:
            return
        tid = self._side_slot_tid if side else self._main_slot_tid
        if not tid:
            return
        item = self.presenter.gate.pull_out_full(tid, text)
        if item is None:
            # 竞态：点击到处理之间条目已被重投/消费 → 只刷新条
            self._refresh_queue_strip()
            return
        raw, images = item
        if not self.presenter.gate.is_running(tid):
            # 边界兜底（正常不可达：有排队项即有 running 回合）：回合已结束 →
            # 撤出队列等价于立即重投
            self.presenter.start_turn(tid, raw, images=images or None)
            self._ensure_pane(tid).append_user(raw, images or None)
            self._slot_status("side" if side else "main").setText("已发送，执行中…")
        else:
            payload = raw
            if images:
                _, fallback, _ = build_image_submit(raw, images)
                payload = fallback or raw
            self.presenter.runtime.registry.push(tid, payload)
            self._ensure_pane(tid).append_user(raw, images or None)
            self._slot_status("side" if side else "main").setText("已插队：注入当前回合的下一步（图片以路径引用）" if images else "已插队：注入当前回合的下一步")
        self._refresh_queue_strip()

    def _on_queue_pull_out(self, text: str, side: bool = False) -> None:
        """gui-ux22 工单 02：side 参数路由到右槽（撤出后回填对应槽输入件）。"""
        tid = self._side_slot_tid if side else self._main_slot_tid
        res = (
            self.presenter.gate.pull_out_full(tid, text)
            if self.presenter and tid
            else None
        )
        bar, imgs = self._slot_input_widgets("side" if side else "main")
        if res is not None:
            bar.edit.setPlainText(res[0])
            imgs.clear()
            for _img in res[1]:
                imgs.add_image(_img)
            bar.edit.setFocus()
            self._slot_status("side" if side else "main").setText("已撤出队列，返回输入框")
        self._refresh_queue_strip()
