"""#03 剪贴板图片粘贴支持（零新依赖）。

codex 同款思路：剪贴板有图片时落盘临时 PNG，输入框插 [Image #N] 原子占位符，
提交时读文件 → base64 data URL 注入 OpenAI 兼容端点的多模态 content。
"""
from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
import tempfile
import time

IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"})

_DATA_URL_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}

# 不做图片缩放（零新依赖原则）：>4MB 直接提示过大。
IMAGE_MAX_BYTES = 4 * 1024 * 1024

_PLACEHOLDER_RE = re.compile(r"\[Image #(\d+)\]")


def looks_like_image_path(text: str) -> str | None:
    """text 为单个已存在的图片文件路径时返回其绝对路径，否则 None。

    允许路径含空格（Windows 目录名常态）；只排除换行（多行文本不是路径）
    与无法解析为文件的 token（整句误判兜底：isfile 为假 → None）。
    """
    token = (text or "").strip()
    if not token or "\n" in token or "\r" in token:
        return None
    ext = os.path.splitext(token)[1].lower()
    if ext not in IMAGE_EXTS:
        return None
    p = os.path.abspath(token)
    return p if os.path.isfile(p) else None


def _new_temp_target() -> str:
    return os.path.join(
        tempfile.gettempdir(),
        f"jarvis-clipboard-{int(time.time() * 1000)}.png",
    )


def try_copy_clipboard_image() -> str | None:
    """读 OS 剪贴板中的图片并落盘为临时 PNG，返回路径；无图片/失败返回 None。

    Windows：PowerShell WinForms [System.Windows.Forms.Clipboard]::GetImage()
    + Bitmap.Save（零新依赖）。不用 Get-Clipboard -Format Image——该参数依赖
    PowerShell 7.3+ 的 Management 模块，低版本/企业策略裁剪下报
    「找不到参数 Format」（本机 PS 7.6.7 但 Management 7.0.0.0 实测不可用）；
    WinForms GetImage 本机实证：图片独占剪贴板时写出 PNG，纯文本剪贴板
    返回 $null（无误报）。单参 Save 按 .png 扩展名推 PNG。
    目标路径经 JARVIS_CLIP_FILE 环境变量传入，避免命令行引号问题。
    Unix：尽力 wl-paste / xclip，不可用返回 None。
    """
    target = _new_temp_target()
    if sys.platform == "win32":
        script = (
            "Add-Type -AssemblyName System.Windows.Forms\n"
            "$img = [System.Windows.Forms.Clipboard]::GetImage()\n"
            "if ($img) { $img.Save([System.IO.Path]::GetFullPath($env:JARVIS_CLIP_FILE)) }"
        )
        env = {**os.environ, "JARVIS_CLIP_FILE": target}
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                env=env,
                timeout=10,
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:  # noqa: BLE001
            return None
        if os.path.isfile(target) and os.path.getsize(target) > 0:
            return target
        return None
    for args in (
        ["wl-paste", "-t", "image/png", "-o", target],
        ["xclip", "-selection", "clipboard", "-t", "image/png", "-o", target],
    ):
        try:
            subprocess.run(args, timeout=10, capture_output=True)
        except (FileNotFoundError, subprocess.SubprocessError):
            continue
        if os.path.isfile(target) and os.path.getsize(target) > 0:
            return target
    return None


def image_to_data_url(path: str) -> str | None:
    """图片文件 → base64 data URL（mime 按扩展名）；读失败返回 None。"""
    mime = _DATA_URL_MIME.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def build_multimodal_content(
    text: str,
    attachments: dict[int, str],
    data_url_fn=None,
) -> list[dict]:
    """按 [Image #N] 占位符切分 text，生成 OpenAI 多模态 content parts。

    - 空文本段跳过；
    - 占位符缺附件 → 保留占位文字；
    - 文件 >IMAGE_MAX_BYTES 或 data_url_fn 返回 None → 跳过该图并加文字说明。
    """
    fn = data_url_fn or image_to_data_url
    parts: list[dict] = []
    last = 0
    for m in _PLACEHOLDER_RE.finditer(text):
        seg = text[last:m.start()].strip()
        if seg:
            parts.append({"type": "text", "text": seg})
        idx = int(m.group(1))
        path = attachments.get(idx)
        if path is None:
            parts.append({"type": "text", "text": m.group(0)})
            last = m.end()
            continue
        try:
            too_big = os.path.getsize(path) > IMAGE_MAX_BYTES
        except OSError:
            too_big = False
        if too_big:
            parts.append({"type": "text", "text": f"图片 #{idx} 超过 4MB，已省略（路径: {path}）"})
        else:
            data_url = fn(path)
            if data_url is None:
                parts.append({"type": "text", "text": f"图片 #{idx} 读取失败（路径: {path}）"})
            else:
                parts.append({"type": "image_url", "image_url": {"url": data_url}})
        last = m.end()
    tail = text[last:].strip()
    if tail:
        parts.append({"type": "text", "text": tail})
    return parts


def image_fallback_text(text: str, attachments: dict[int, str]) -> str:
    """占位符替换为「图片 #N 路径: <abs>」，供 image_input off/auto 回落。"""

    def _sub(m: "re.Match[str]") -> str:
        idx = int(m.group(1))
        path = attachments.get(idx)
        return f"图片 #{idx} 路径: {path}" if path else m.group(0)

    return _PLACEHOLDER_RE.sub(_sub, text)


__all__ = [
    "IMAGE_EXTS",
    "IMAGE_MAX_BYTES",
    "build_multimodal_content",
    "image_fallback_text",
    "image_to_data_url",
    "looks_like_image_path",
    "try_copy_clipboard_image",
]