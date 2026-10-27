"""图片附件条（工单 07）：粘贴/缩略图/放大/移除 → 多模态提交。

GUI 原生形态（不做 TUI 的 [Image #N] 文本占位符）：
- Ctrl+V（剪贴板图）或粘贴图片路径文本 → 附件条出现缩略图 chip（≈56 圆角 + ✕）。
- 点缩略图 → 无边框放大窗（等比 ≤80% 屏，Esc/点击关闭）。
- 有附件才显示附件条。
- 提交：附件随消息发——用户气泡同样带缩略图；载荷走
  build_multimodal_content（OpenAI 多模态 parts）作 user_input +
  image_fallback_text（路径引用）作 user_input_fallback；
  run_agent_turn 既有 model_image_input="auto" 拒图回落语义不变。

build_image_submit = 纯函数（无 Qt，可单测）；ImageStrip / ImagePreview = Qt 部件。
"""
from __future__ import annotations

import time
from pathlib import Path

from src import clipboard_image


def build_image_submit(
    raw_text: str,
    image_paths: list[str],
    data_url_fn=None,
) -> tuple[list | None, str | None, str]:
    """纯函数：有附件 → (user_input 多模态 parts, user_input_fallback 路径引用, 展示文本)；
    无附件 → (None, None, raw_text)。附件顺序 = image_paths 顺序（#1..#N 在前）。"""
    if not image_paths:
        return None, None, raw_text
    idx = {i + 1: p for i, p in enumerate(image_paths)}
    placeholders = "".join(f"[Image #{i + 1}]\n" for i in range(len(image_paths)))
    combined = placeholders + raw_text
    user_input = clipboard_image.build_multimodal_content(combined, idx, data_url_fn)
    user_input_fallback = clipboard_image.image_fallback_text(combined, idx)
    return user_input, user_input_fallback, raw_text


def save_clipboard_image_to_temp(qimage) -> str | None:
    """Qt QImage → 临时 PNG 路径（供附件条用）；空图/失败 None。纯逻辑分离便于测试。"""
    if qimage is None or getattr(qimage, "isNull", lambda: True)():
        return None
    target = Path(clipboard_image._new_temp_target())
    ok = qimage.save(str(target))
    return str(target) if ok else None


def new_temp_image_target() -> str:
    """无 Qt 的纯路径生成（测试 / 非剪贴板来源的图片落盘）。"""
    return f"jarvis-attach-{int(time.time() * 1000)}.png"
