"""工单 02 — LLM 自配层：五档探测纯函数 + config.json 存取 + key_ref 悬空 + 损坏自愈。"""
import json

import pytest

from src.gui import llm_config
from src.gui.llm_config import (
    InMemoryKeyStore,
    LlmConfig,
    classify_probe,
    load_llm_config,
    save_llm_config,
)


# ---------------------------------------------------------------- 五档探测表


def test_probe_ok():
    r = classify_probe(200, "{}", "https://gw.example.com/v1")
    assert r.code == "ok" and "连接成功" in r.message


def test_probe_401_key_invalid():
    r = classify_probe(401, "unauthorized", "https://gw/v1")
    assert r.code == "unauthorized" and "密钥无效" in r.message and "重新填写" in r.action


def test_probe_403_forbidden():
    r = classify_probe(403, "forbidden", "https://gw/v1")
    assert r.code == "forbidden" and "管理员" in r.action


def test_probe_429_ratelimited():
    r = classify_probe(429, "", "https://gw/v1")
    assert r.code == "ratelimited" and "稍后" in r.action


def test_probe_network_refused_gets_specific_hint():
    r = classify_probe(None, "[Errno 111] Connection refused", "https://gw:8443/v1")
    assert r.code == "network"
    assert "服务" in r.message or "拒绝" in r.message
    assert "网络" in r.action or "服务" in r.action


def test_probe_network_generic():
    r = classify_probe(None, "timeout", "https://gw/v1")
    assert r.code == "network"


def test_probe_404_missing_v1_suggests_fix():
    r = classify_probe(404, "not found", "https://gw")
    assert r.code == "url_missing_v1"
    assert "/v1" in r.action


def test_probe_404_supported_gateway_manual_model():
    r = classify_probe(404, "not found", "https://gw/v1")
    assert r.code == "url_missing_v1"
    assert r.probe_supported is False  # 网关无 /models → 手填 model id
    assert "手填" in r.action


# ---------------------------------------------------------------- 存取 + key_ref


@pytest.fixture()
def tmp_home_dir():
    """自建目录纪律（本机 pytest tmp 中毒，禁用 tmp_path）：.scratch/gui-test-tmp/。"""
    import uuid

    from pathlib import Path

    from tests.gui_fakes import TEST_ROOT

    d = TEST_ROOT / f"llm-{uuid.uuid4().hex[:10]}"
    d.mkdir(parents=True)
    yield str(d)


def _home(tmp_home: str) -> "object":
    from pathlib import Path

    p = Path(tmp_home)
    p.mkdir(parents=True, exist_ok=True)
    return p


def test_save_load_roundtrip_keeps_key_out_of_json(tmp_home_dir):
    home = _home(tmp_home_dir)
    store = InMemoryKeyStore()
    cfg = LlmConfig("https://gw.example/v1", "sk-secret-123", "mimo-v2.5")
    path = save_llm_config(cfg, store, home)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "sk-secret-123" not in json.dumps(data)  # 明文不落盘
    assert data["llm"]["key_ref"] == llm_config.KEY_REF
    assert data["version"] == llm_config.VERSION

    res = load_llm_config(store, home)
    assert res.key_status == "ok"
    assert res.config.api_key == "sk-secret-123"
    assert res.config.model_id == "mimo-v2.5"


def test_dangling_key_ref(tmp_home_dir):
    home = _home(tmp_home_dir)
    store = InMemoryKeyStore()
    save_llm_config(LlmConfig("https://gw/v1", "sk-x", "m"), store, home)
    # 模拟域账号重置：CM 里的秘密没了
    res = load_llm_config(InMemoryKeyStore(), home)
    assert res.key_status == "dangling"
    assert res.config is not None  # 配置还在，回向导第 3 步重填 key


def test_missing_config(tmp_home_dir):
    home = _home(tmp_home_dir)
    res = load_llm_config(InMemoryKeyStore(), home)
    assert res.key_status == "missing" and res.config is None


def test_corrupt_json_falls_back_to_backup(tmp_home_dir):
    home = _home(tmp_home_dir)
    store = InMemoryKeyStore()
    save_llm_config(LlmConfig("https://gw/v1", "sk-a", "m1"), store, home)
    save_llm_config(LlmConfig("https://gw/v1", "sk-b", "m2"), store, home)
    # 主文件写坏
    (home / "config.json").write_text("{not-json", encoding="utf-8")
    res = load_llm_config(store, home)
    assert res.key_status == "ok"
    assert res.config.model_id == "m2"  # 回退到 .bak（最近一次好版本）


def test_wizard_validation(tmp_home_dir):
    ok, msg = llm_config.validate_wizard(LlmConfig("https://gw/v1", "sk", "m1"))
    assert ok
    ok, msg = llm_config.validate_wizard(LlmConfig("gw/v1", "sk", "m1"))
    assert not ok and "http" in msg
    ok, msg = llm_config.validate_wizard(LlmConfig("https://gw/v1", "", "m1"))
    assert not ok and "Key" in msg
    # 探测不支持的网关允许空模型（勾选手填后 model 必填，此处未勾 → 报错）
    ok, msg = llm_config.validate_wizard(LlmConfig("https://gw/v1", "sk", ""))
    assert not ok
