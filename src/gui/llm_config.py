"""LLM 用户自配层（工单 02）：用户全局配置 + 凭据管理 + 端点探测（纯逻辑，可单测）。

- 配置落 %APPDATA%\\Jarvis\\config.json（与安装目录分离；多用户隔离；损坏自愈回退
  最近 backup + version 单调迁移）。
- API key 走 keyring（Windows Credential Manager），config 只存 key_ref 不落明文；
  组策略禁写 CM 时降级 DPAPI user-scope（CryptProtectData）。
- 端点探测五档（Jan 先例，纯函数状态表）：ok / unauthorized / forbidden /
  ratelimited / network / url_missing_v1。probe_supported=False（内网网关无
  /models）允许手填 model id，保存成功不算失败。
- key_ref 悬空（域账号重置）→ 启动校验状态 dangling，GUI 回向导第 3 步，不崩。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

VERSION = 1
KEY_REF = "jarvis-llm"
ENV_HOME_OVERRIDE = "JARVIS_GUI_HOME"

# 内网网关的 /models 端点不可用时的探测标记
PROBE_SUPPORTED_DEFAULT = True


# ---------------------------------------------------------------- 探测（纯函数）


@dataclass
class ProbeResult:
    code: str  # ok / unauthorized / forbidden / ratelimited / network / url_missing_v1
    message: str
    action: str  # 给用户的下一步动作
    probe_supported: bool = True


def classify_probe(status: int | None, text: str, base_url: str) -> ProbeResult:
    """五档端点探测判定（纯函数；status=None = 网络层失败）。"""
    url = (base_url or "").rstrip("/")
    if status is None:
        if "refused" in (text or "").lower() or "connect" in (text or "").lower():
            return ProbeResult(
                "network",
                f"连接被拒绝：{url} 服务可能未启动。",
                "确认服务已启动 / 地址端口正确；内网 VPN 连上后重试。",
            )
        return ProbeResult(
            "network", f"连不上服务（{text or '网络错误'}）。", "检查网络 / 代理 / 服务可用性。"
        )
    if status == 200:
        return ProbeResult("ok", "连接成功", "选择或填写默认模型。")
    if status == 401:
        return ProbeResult("unauthorized", "密钥无效（401）", "重新填写 API Key。")
    if status == 403:
        return ProbeResult("forbidden", "无访问权限（403）", "联系管理员开通该端点权限。")
    if status == 429:
        return ProbeResult("ratelimited", "限流（429）", "稍后重试；持续限流请找管理员。")
    if status == 404:
        missing_v1 = not url.endswith("/v1")
        # URL 已有 /v1 仍 404 = 网关无 /models 端点 → 探测不可用（手填模型）；
        # URL 缺 /v1 = 提示补全后重试（探测仍可用）。
        return ProbeResult(
            "url_missing_v1",
            "端点不存在（404）" + ("，URL 缺 /v1" if missing_v1 else "，网关可能不支持 /models 探测"),
            "补全 URL（如 https://host/v1）" if missing_v1 else "手填模型 ID 后直接保存（该网关跳过探测）",
            probe_supported=missing_v1,
        )
    return ProbeResult("network", f"未知响应（HTTP {status}）", "联系管理员；或跳过探测直接保存。")


def default_home() -> Path:
    env = os.environ.get(ENV_HOME_OVERRIDE)
    if env:
        return Path(env)
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    return Path(appdata) / "Jarvis"


# ---------------------------------------------------------------- 凭据存储


class KeyStore(Protocol):
    def set(self, ref: str, secret: str) -> None: ...

    def get(self, ref: str) -> str | None: ...

    def delete(self, ref: str) -> None: ...


class InMemoryKeyStore:
    """测试 / 非 Windows 兜底。"""

    def __init__(self) -> None:
        self._d: dict[str, str] = {}

    def set(self, ref: str, secret: str) -> None:
        self._d[ref] = secret

    def get(self, ref: str) -> str | None:
        return self._d.get(ref)

    def delete(self, ref: str) -> None:
        self._d.pop(ref, None)


class DpapiKeyStore:
    """Windows DPAPI user-scope（组策略禁写 Credential Manager 时的降级路径）。"""

    def __init__(self, secret_dir: Path | None = None) -> None:
        self._dir = secret_dir or (default_home() / "secrets")

    def _protect(self, secret: str) -> bytes:
        """CryptProtectData（user-scope）。

        注意两个坑（本机实测）：
        - 第 1 参是 PDATA_BLOB 结构指针（cbData+pbData），不是裸 buffer——
          传裸 buffer/None 会报 Win32 87（ERROR_INVALID_PARAMETER）；
        - szDataDescription 是 LPCWSTR：声明 c_char_p 传 bytes 同样 87。
        """
        import ctypes
        from ctypes import c_char, c_uint32, c_void_p

        class _BLOB(ctypes.Structure):
            _fields_ = [("cbData", c_uint32), ("pbData", ctypes.POINTER(c_char))]

        data = secret.encode("utf-8")
        buf = ctypes.create_string_buffer(data, len(data))
        inb = _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(c_char)))
        out = _BLOB(0, None)
        crypt = ctypes.windll.crypt32
        crypt.CryptProtectData.argtypes = [
            ctypes.POINTER(_BLOB), ctypes.c_wchar_p, ctypes.POINTER(_BLOB),
            c_void_p, c_void_p, c_uint32, ctypes.POINTER(_BLOB),
        ]
        crypt.CryptProtectData.restype = c_uint32
        crypt.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_BLOB), ctypes.POINTER(ctypes.c_wchar_p), ctypes.POINTER(_BLOB),
            c_void_p, c_void_p, c_uint32, ctypes.POINTER(_BLOB),
        ]
        crypt.CryptUnprotectData.restype = c_uint32
        if not crypt.CryptProtectData(ctypes.byref(inb), "jarvis-llm", None, None, None, 0, ctypes.byref(out)):
            raise OSError(f"CryptProtectData 失败（Win32 {ctypes.GetLastError()}）")
        return ctypes.string_at(out.pbData, out.cbData)

    def _unprotect(self, blob: bytes) -> str:
        import ctypes
        from ctypes import c_char, c_uint32, c_void_p

        class _BLOB(ctypes.Structure):
            _fields_ = [("cbData", c_uint32), ("pbData", ctypes.POINTER(c_char))]

        inb = _BLOB(len(blob), ctypes.cast(ctypes.create_string_buffer(blob, len(blob)), ctypes.POINTER(c_char)))
        out = _BLOB(0, None)
        crypt = ctypes.windll.crypt32
        crypt.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_BLOB), ctypes.POINTER(ctypes.c_wchar_p), ctypes.POINTER(_BLOB),
            c_void_p, c_void_p, c_uint32, ctypes.POINTER(_BLOB),
        ]
        crypt.CryptUnprotectData.restype = c_uint32
        if not crypt.CryptUnprotectData(ctypes.byref(inb), None, None, None, None, 0, ctypes.byref(out)):
            raise OSError(f"CryptUnprotectData 失败（Win32 {ctypes.GetLastError()}）")
        return ctypes.string_at(out.pbData, out.cbData).decode("utf-8")

    def set(self, ref: str, secret: str) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        (self._dir / f"{ref}.bin").write_bytes(self._protect(secret))

    def get(self, ref: str) -> str | None:
        p = self._dir / f"{ref}.bin"
        if not p.exists():
            return None
        return self._unprotect(p.read_bytes())

    def delete(self, ref: str) -> None:
        p = self._dir / f"{ref}.bin"
        if p.exists():
            p.unlink()


def make_key_store(home: Path | None = None) -> KeyStore:
    """优先 keyring（Credential Manager）；不可用 → DPAPI（仅 win32）；再不行 → 内存（警告）。"""
    try:
        import keyring  # noqa: F401

        return _KeyringStore()
    except ImportError:
        pass
    if os.name == "nt":
        return DpapiKeyStore(home)
    return InMemoryKeyStore()


class _KeyringStore:
    """Windows Credential Manager（keyring 原生后端）；写失败（组策略禁写）降级 DPAPI。"""

    SERVICE = "Jarvis"

    def __init__(self, home: Path | None = None) -> None:
        import keyring

        self._kr = keyring
        self._fallback = DpapiKeyStore(home) if os.name == "nt" else None

    def set(self, ref: str, secret: str) -> None:
        try:
            self._kr.set_password(self.SERVICE, ref, secret)
            self._kr.get_password(self.SERVICE, ref)  # 读回校验（禁写组策略下 set 可能静默失败）
        except Exception:
            if self._fallback is not None:
                self._fallback.set(ref, secret)
            else:
                raise

    def get(self, ref: str) -> str | None:
        try:
            v = self._kr.get_password(self.SERVICE, ref)
            if v is not None:
                return v
        except Exception:
            pass
        if self._fallback is not None:
            return self._fallback.get(ref)
        return None

    def delete(self, ref: str) -> None:
        try:
            self._kr.delete_password(self.SERVICE, ref)
        except Exception:
            pass
        if self._fallback is not None:
            self._fallback.delete(ref)


# ---------------------------------------------------------------- 配置存取


@dataclass
class LlmConfig:
    base_url: str
    api_key: str
    model_id: str
    provider: str = "openai-compatible"  # openai-compatible / local
    probe_supported: bool = PROBE_SUPPORTED_DEFAULT


@dataclass
class LoadResult:
    config: LlmConfig | None
    key_status: str  # ok / dangling / missing
    raw: dict = field(default_factory=dict)


def _atomic_write_json(path: Path, data: dict) -> None:
    """原子写 + 事后备份：先 tmp→replace 落 config.json（全成功/全旧），
    再把当前好版本复制到 .bak。这样 .bak 恒为「最近一次成功写」的版本，
    config.json 事后损坏时回退 .bak 即得最近好版本（spec：损坏自愈回退 backup）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    json.loads(text)  # 校验可回读，坏数据不落盘
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    bak = path.with_suffix(".json.bak")
    try:
        bak.write_bytes(path.read_bytes())
    except OSError:
        pass


def save_llm_config(cfg: LlmConfig, key_store: KeyStore, home: Path | None = None) -> Path:
    key_store.set(KEY_REF, cfg.api_key)
    path = (home or default_home()) / "config.json"
    _atomic_write_json(path, {
        "version": VERSION,
        "llm": {
            "base_url": cfg.base_url,
            "model_id": cfg.model_id,
            "provider": cfg.provider,
            "key_ref": KEY_REF,
            "probe_supported": cfg.probe_supported,
        },
    })
    return path


def load_llm_config(key_store: KeyStore, home: Path | None = None) -> LoadResult:
    path = (home or default_home()) / "config.json"
    raw = _read_config_or_backup(path)
    if raw is None:
        return LoadResult(None, "missing", {})
    llm = raw.get("llm") or {}
    key_ref = llm.get("key_ref", KEY_REF)
    api_key = key_store.get(key_ref)
    status = "ok" if api_key else "dangling"
    if api_key is None and not llm:
        return LoadResult(None, "missing", raw)
    cfg = LlmConfig(
        base_url=str(llm.get("base_url", "")),
        api_key=api_key or "",
        model_id=str(llm.get("model_id", "")),
        provider=str(llm.get("provider", "openai-compatible")),
        probe_supported=bool(llm.get("probe_supported", True)),
    )
    return LoadResult(cfg, status, raw)


def _read_config_or_backup(path: Path) -> dict | None:
    """损坏自愈：主文件 JSON 解析失败 → 回退 .bak；版本单调（旧 version 保留兼容读）。"""
    candidates = [path, path.with_suffix(".json.bak")]
    for c in candidates:
        if not c.exists():
            continue
        try:
            data = json.loads(c.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        v = data.get("version", 0)
        if v > VERSION:
            # 更高版本写入（前向不兼容）——保留可读字段，不覆盖
            data.setdefault("version", VERSION)
        return data
    return None


def key_ref_status(cfg: LlmConfig, key_store: KeyStore) -> str:
    """启动校验：key_ref 悬空（域账号重置 / CM 被清）= dangling。"""
    return "ok" if key_store.get(KEY_REF) else "dangling"


def ensure_configured(key_store: KeyStore | None = None, home: Path | None = None) -> LoadResult:
    store = key_store or make_key_store(home)
    return load_llm_config(store, home)


# ---------------------------------------------------------------- 探测执行（httpx，可注入）


def make_probe_fn(timeout: float = 8.0):
    """GET {base_url}/models（Bearer）→ (status|None, text)。网络注入 fake 用于单测。"""
    def probe(base_url: str, api_key: str) -> tuple[int | None, str]:
        import httpx

        url = (base_url or "").rstrip("/")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        try:
            r = httpx.get(f"{url}/models", headers=headers, timeout=timeout)
            return r.status_code, r.text[:300]
        except Exception as exc:  # noqa: BLE001 — 网络层全捕获，归 network 档
            return None, str(exc)
    return probe


# ---------------------------------------------------------------- ChatOpenAI 构造


def to_chat_model(cfg: LlmConfig):
    """自配 LLM → ChatOpenAI（OpenAI 兼容端点；模型名不加前缀，经 MODEL 语义与 .env 等价）。"""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        base_url=cfg.base_url,
        api_key=cfg.api_key,
        model=cfg.model_id,
        max_retries=3,
        timeout=120,
    )


_VALID_URL = re.compile(r"^https?://\S+$")


def validate_wizard(cfg: LlmConfig) -> tuple[bool, str]:
    """向导保存前校验（纯函数）。本地推理允许空 key（sk-no-key 占位由向导填入）。"""
    if not _VALID_URL.match((cfg.base_url or "").strip()):
        return False, "端点地址须为 http:// 或 https:// 开头的完整 URL。"
    if not (cfg.model_id or "").strip() and cfg.probe_supported:
        return False, "请填模型 ID（或勾选「该网关不支持 /models，手填模型」）。"
    if not (cfg.api_key or "").strip():
        return False, "API Key 不能为空（本地推理填 sk-no-key）。"
    return True, ""
