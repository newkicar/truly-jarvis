"""工单 02 — LLM 首启向导（offscreen）：5 步走通 + 跳过 + 本地推理 + 悬空重入。"""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from src.gui import llm_config
from src.gui.llm_config import InMemoryKeyStore
from src.gui.wizard import LlmWizard


@pytest.fixture()
def home_dir():
    import uuid

    from tests.gui_fakes import TEST_ROOT

    d = TEST_ROOT / f"wizard-{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True)
    yield d


@pytest.fixture(autouse=True)
def _fake_install_root(monkeypatch):
    """gui-ux26 防护：LlmWizard.save() 会真调 sync_install_env → CPython 下 install_root()
    解析到真实 repo 根，会污染开发者真 .env；钉到 scratch 目录（全部既有用例免疫）。"""
    import shutil
    import uuid

    import src.project_paths as pp
    from tests.gui_fakes import TEST_ROOT

    d = TEST_ROOT / f"instroot-{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True)
    monkeypatch.setattr(pp, "install_root", lambda: d)
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_wizard_full_flow_saves_keyref_not_plaintext(qapp, home_dir):
    store = InMemoryKeyStore()
    w = LlmWizard(key_store=store, home=home_dir, start_page_index=1)
    # provider 默认 gw；填端点
    w._endpoint.base_url_edit.setText("https://gw.example.com/v1")
    w._endpoint.api_key_edit.setText("sk-real-key")
    w._probe_fn = lambda b, k: (200, '{"data": []}')
    w.start_probe_sync()
    assert "连接成功" in w._probe.result_label.text()
    w._model.model_edit.setText("mimo-v2.5")
    w.accept()

    path = home_dir / "config.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["llm"]["key_ref"] == llm_config.KEY_REF
    assert "sk-real-key" not in json.dumps(data)  # 明文不落盘
    assert store.get(llm_config.KEY_REF) == "sk-real-key"


def test_wizard_local_provider_prefills_no_key(qapp, home_dir):
    store = InMemoryKeyStore()
    w = LlmWizard(key_store=store, home=home_dir, start_page_index=1)
    w._provider.local_radio.setChecked(True)
    w._endpoint.base_url_edit.setText("http://localhost:11434/v1")
    assert w._endpoint.api_key_edit.text() == "sk-no-key"
    assert not w._endpoint.api_key_edit.isEnabled()
    w._model.model_edit.setText("bge-small-zh-v1.5")
    w.accept()
    data = json.loads((home_dir / "config.json").read_text(encoding="utf-8"))
    assert data["llm"]["provider"] == "local"
    assert data["llm"]["key_ref"] == llm_config.KEY_REF


def test_wizard_skip_writes_nothing(qapp, home_dir):
    w = LlmWizard(key_store=InMemoryKeyStore(), home=home_dir)
    w.reject()  # 跳过
    assert not (home_dir / "config.json").exists()


def test_wizard_dangling_key_reenters_at_endpoint_page(qapp, home_dir):
    w = LlmWizard(key_store=InMemoryKeyStore(), home=home_dir, start_page_index=2)
    w.show()
    qapp.processEvents()
    assert w.currentPage() is w._endpoint
    w.close()


def test_wizard_unsupported_probe_allows_empty_model(qapp, home_dir):
    store = InMemoryKeyStore()
    w = LlmWizard(key_store=store, home=home_dir, start_page_index=1)
    w._endpoint.base_url_edit.setText("https://gw/v1")
    w._endpoint.api_key_edit.setText("sk-x")
    # 内网网关无 /models → 404 + 勾「手填」后可保存
    w._probe._probe_fn = lambda b, k: (404, "not found")
    w._probe_fn = w._probe._probe_fn
    w.start_probe_sync()
    w._model.no_probe_check.setChecked(True)
    w.accept()
    data = json.loads((home_dir / "config.json").read_text(encoding="utf-8"))
    assert data["llm"]["probe_supported"] is False


def test_wizard_result_enum_contract(qapp, home_dir):
    """PySide6 6.x 起枚举不在实例上暴露（wiz.Accepted 报 AttributeError）：
    结果比较必须走 QDialog.DialogCode（gui_main._run_wizard 契约）。"""
    from PySide6.QtWidgets import QDialog

    w = LlmWizard(key_store=InMemoryKeyStore(), home=home_dir)
    w.show()
    qapp.processEvents()
    assert not hasattr(w, "Accepted"), "PySide6 实例级枚举已移除，勿依赖"
    w.done(QDialog.DialogCode.Accepted)
    assert w.result() == QDialog.DialogCode.Accepted


def test_wizard_save_generates_install_env(qapp, home_dir, _fake_install_root):
    """gui-ux26：保存 LLM 配置时自动生成 install_root()/.env（便携版兜底面）。"""
    w = LlmWizard(key_store=InMemoryKeyStore(), home=home_dir, start_page_index=1)
    w._endpoint.base_url_edit.setText("https://gw.example.com/v1")
    w._endpoint.api_key_edit.setText("sk-wiz")
    w._probe_fn = lambda b, k: (200, "{}")
    w.start_probe_sync()
    w._model.model_edit.setText("mimo-v2.5")
    w.accept()

    p = _fake_install_root / ".env"
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "BASE_URL=https://gw.example.com/v1" in text
    assert "API_KEY=sk-wiz" in text
    assert "MODEL_ID=mimo-v2.5" in text


def test_wizard_skip_generates_no_env(qapp, home_dir, _fake_install_root):
    """跳过向导（reject）不生成安装目录 .env。"""
    w = LlmWizard(key_store=InMemoryKeyStore(), home=home_dir)
    w.reject()
    assert not (_fake_install_root / ".env").exists()
