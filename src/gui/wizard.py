"""LLM 首启 5 步向导（工单 02）：欢迎+安全承诺 → 选 provider → 填地址密钥 → 测试连接 → 选默认模型。

可跳过（欢迎页）；key_ref 悬空启动时从第 3 步（EndpointPage）重入。
保存 = save_llm_config（key 进 Credential Manager/DPAPI，config.json 只存 key_ref）。
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QWizard,
    QWizardPage,
)

from src.gui import llm_config


class _ProbeEvents(QObject):
    done = Signal(object)  # llm_config.ProbeResult


class LlmWizard(QWizard):
    """5 步向导。save_fn(cfg) 由调用方注入（默认 save_llm_config）；skip 不保存。"""

    def __init__(
        self,
        key_store=None,
        home=None,
        start_page_index: int = 0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("配置 LLM 端点")
        self.setWizardStyle(QWizard.WizardStyle.ClassicStyle)
        self._key_store = key_store or llm_config.make_key_store(home)
        self._home = home
        self._probe_fn = llm_config.make_probe_fn()
        self._events = _ProbeEvents()
        self._events.done.connect(self._on_probe_done)
        self._model_options: list[str] = []

        self._welcome = WelcomePage(self)
        self._provider = ProviderPage(self)
        self._endpoint = EndpointPage(self, self._provider)
        self._probe = ProbePage(self, self._events, self._probe_fn)
        self._model = ModelPage(self, self._endpoint, self._provider)

        self._pages = [self._welcome, self._provider, self._endpoint, self._probe, self._model]
        self._page_ids: list[int] = []
        for pg in self._pages:
            self._page_ids.append(self.addPage(pg))
        self._welcome.setFinalPage(False)
        self._model.setFinalPage(True)

        self.button(QWizard.WizardButton.CommitButton).setText("保存并连接")
        self.button(QWizard.WizardButton.CancelButton).setText("跳过（稍后配置）")
        self._pending_start = start_page_index if start_page_index > 0 else None

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # QWizard 只在 show 后初始化页栈；重入页（如悬空 key 回第 3 步）须延迟设置
        if self._pending_start is not None:
            self.setCurrentId(self._page_ids[self._pending_start])
            self._pending_start = None

    def accept(self) -> None:
        """「保存并连接」：校验通过才落盘（key 进凭据管理器）；跳过（reject）不保存。"""
        cfg = self.current_config()
        ok, msg = llm_config.validate_wizard(cfg)
        if not ok:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, "无法保存", msg)
            return
        self.save()
        super().accept()

    # ---- 探测（worker 线程跑，信号回主线程）
    def start_probe(self) -> None:
        probe_fn = self._probe_fn
        e = self._endpoint

        def run():
            base = e.base_url_edit.text().strip()
            key = e.api_key_edit.text().strip()
            status, text = probe_fn(base, key)
            result = llm_config.classify_probe(status, text, base)
            self._events.done.emit(result)

        threading.Thread(target=run, daemon=True, name="jarvis-gui-probe").start()

    def start_probe_sync(self) -> None:
        """测试用：同步跑探测（offscreen 无事件循环）。"""
        self._on_probe_done(self._probe_result())

    def _probe_result(self) -> llm_config.ProbeResult:
        base = self._endpoint.base_url_edit.text().strip()
        key = self._endpoint.api_key_edit.text().strip()
        status, text = self._probe_fn(base, key)
        return llm_config.classify_probe(status, text, base)

    def _on_probe_done(self, result: llm_config.ProbeResult) -> None:
        self._probe.show_result(result)

    # ---- 保存
    def current_config(self) -> llm_config.LlmConfig:
        p = self._provider
        e = self._endpoint
        m = self._model
        local = p.local_radio.isChecked()
        return llm_config.LlmConfig(
            base_url=e.base_url_edit.text().strip(),
            api_key=("sk-no-key" if local else e.api_key_edit.text().strip()),
            model_id=m.model_edit.text().strip(),
            provider="local" if local else "openai-compatible",
            probe_supported=not m.no_probe_check.isChecked(),
        )

    def save(self) -> llm_config.LlmConfig:
        cfg = self.current_config()
        llm_config.save_llm_config(cfg, self._key_store, self._home)
        return cfg


# ---------------------------------------------------------------- 各页


class WelcomePage(QWizardPage):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("欢迎")
        body = QLabel(
            "接下来 5 步配置 JARVIS 的 LLM 端点（公司网关 / 第三方 OpenAI 兼容 / 本地推理）。\n\n"
            "安全承诺：API Key 存入 Windows 凭据管理器（Credential Manager），"
            "配置文件只留一个引用（key_ref），不落明文；"
            "配置存于 %APPDATA%\\Jarvis，与安装目录分离，卸载/重装不丢。"
        )
        body.setWordWrap(True)
        self.setLayout(_form(body))


class ProviderPage(QWizardPage):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("选择服务商类别")
        self.gw_radio = QRadioButton("公司 / 自建网关（OpenAI 兼容端点）")
        self.third_radio = QRadioButton("第三方 OpenAI 兼容服务")
        self.local_radio = QRadioButton("本地推理（Ollama / LM Studio 等）")
        self.gw_radio.setChecked(True)
        self.setLayout(
            _form(
                self.gw_radio,
                self.third_radio,
                self.local_radio,
                QLabel("本地推理的 Key 填 sk-no-key 占位（向导自动处理）。"),
            )
        )


class EndpointPage(QWizardPage):
    def __init__(self, wizard, provider: ProviderPage) -> None:
        super().__init__(wizard)
        self.setTitle("端点与密钥")
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("https://your-gateway.example.com/v1")
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("sk-...（存入凭据管理器）")
        self.provider = provider
        f = QFormLayout()
        f.addRow("端点地址（base_url）", self.base_url_edit)
        f.addRow("API Key", self.api_key_edit)
        self.setLayout(f)
        self.registerField("base_url*", self.base_url_edit)
        self.registerField("api_key*", self.api_key_edit)
        provider.local_radio.toggled.connect(self._sync_local)
        self._sync_local(provider.local_radio.isChecked())

    def _sync_local(self, local: bool) -> None:
        self.api_key_edit.setEnabled(not local)
        if local:
            self.api_key_edit.setText("sk-no-key")

    def isComplete(self) -> bool:
        return bool(self.base_url_edit.text().strip()) and bool(self.api_key_edit.text().strip())


class ProbePage(QWizardPage):
    def __init__(self, wizard, events: _ProbeEvents, probe_fn) -> None:
        super().__init__(wizard)
        self.setTitle("测试连接")
        self.result_label = QLabel("尚未测试。")
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet("color:#888888;")
        self.result_detail = QPlainTextEdit()
        self.result_detail.setReadOnly(True)
        self.result_detail.setFixedHeight(90)
        self.result_detail.setPlaceholderText("（探测明细）")
        self.btn_probe = QPushButton("测试连接")
        self.btn_probe.clicked.connect(lambda: wizard.start_probe())
        self.setLayout(_form(self.btn_probe, self.result_label, self.result_detail))

    def show_result(self, r: llm_config.ProbeResult) -> None:
        color = {"ok": "green", "unauthorized": "red", "forbidden": "orange"}.get(r.code, "#e8a33d")
        self.result_label.setTextFormat(Qt.RichText)
        self.result_label.setText(
            f"<span style='color:{color};font-weight:bold;'>{r.message}</span> — {r.action}"
        )
        self._last_result = r
        self.result_detail.setPlainText(r.message + "（" + r.code + "）")


class ModelPage(QWizardPage):
    def __init__(self, wizard, endpoint: EndpointPage, provider: ProviderPage) -> None:
        super().__init__(wizard)
        self.setTitle("默认模型")
        self._endpoint = endpoint
        self._provider = provider
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("模型 ID（不加前缀，如 mimo-v2.5）")
        self.no_probe_check = QCheckBox("该网关不支持 /models 探测（手填模型 ID）")
        f = QFormLayout()
        f.addRow(self.model_edit)
        f.addRow(self.no_probe_check)
        self.setLayout(f)
        self.registerField("model*", self.model_edit)

    def isComplete(self) -> bool:
        if self.no_probe_check.isChecked():
            return True
        ok, _ = llm_config.validate_wizard(
            llm_config.LlmConfig(
                base_url=self._endpoint.base_url_edit.text().strip(),
                api_key="x",
                model_id=self.model_edit.text().strip(),
                probe_supported=True,
            )
        )
        return ok


def _form(*widgets) -> QFormLayout:
    from PySide6.QtWidgets import QFormLayout

    f = QFormLayout()
    for w in widgets:
        f.addRow(w)
    return f
