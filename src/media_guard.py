"""媒体内容守卫（media guard）：文本-only 模型下的二进制/多模态 ToolMessage 降级。

根因（deepagents 0.7.x 上游缺口）：
filesystem 工具 read_file 读到 .docx/.xlsx/.png 等二进制时，deepagents
（deepagents/middleware/filesystem.py）会按后缀推 mime 生成 image/video/audio/file
多模态 block 放进 ToolMessage；上游 scrub 只对「已知能容忍 provider + models.dev
profile 数据」生效——mimo-v2.5 这类未知模型 profile 为空、全字段默认「支持」，
ChatOpenAI 又被列为「对非 PDF file block 宽容」的硬编码例外，base64 媒体块
原样透传到网关 → 400「Unsupported content part」（整轮死亡）。
上游文档建议（deepagents multimodal 页）：工具产出大二进制时「存到 backend 并回传
简短文本描述 + 路径」——本模块即该缺口的项目侧补齐（对标 codex 的文件内容过滤层）。

行为：模型调用前把 ToolMessage 里的媒体 block（image/file/audio/video）替换为
中文占位文本（含 read_file 路径与 mime 提示），Human/AI/System 消息与字符串
content 零改动；无改动时按原 list 对象返回（零开销路径）。
无状态 → 一份实例共享主代理 + 全部子代理（SanitizeHistoryMiddleware 同款纪律）。
仅当 config.model_image_input != "on"（auto/off）时挂载；"on" 表示模型真多模态，
媒体块保留原样。
"""
from __future__ import annotations

from langchain.agents.middleware import AgentMiddleware

# deepagents filesystem 工具产出 ToolMessage 里使用的媒体 block type
_MEDIA_BLOCK_TYPES = frozenset({"image", "file", "audio", "video"})

_PLACEHOLDER_FMT = (
    "[read_file: {path} 为二进制/当前模型不支持的内容格式（{mime}），"
    "内容已略过；如需处理请改用文本方式（如 execute 运行解析脚本）而不是直接读取。]"
)


def scrub_unsupported_media_blocks(messages: list) -> list:
    """把 ToolMessage 里的媒体 block 降级为中文占位文本；无改动按引用原样返回。"""
    scrubbed: list = []
    changed = False
    for msg in messages:
        content = getattr(msg, "content", None)
        if isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") in _MEDIA_BLOCK_TYPES for b in content
        ):
            kwargs = getattr(msg, "additional_kwargs", None) or {}
            path = kwargs.get("read_file_path")
            new_blocks = [
                {
                    "type": "text",
                    "text": _PLACEHOLDER_FMT.format(
                        path=path or "the file",
                        mime=(b.get("mime_type") or "unknown")
                        if isinstance(b, dict)
                        else "unknown",
                    ),
                }
                if isinstance(b, dict) and b.get("type") in _MEDIA_BLOCK_TYPES
                else b
                for b in content
            ]
            scrubbed.append(msg.model_copy(update={"content": new_blocks}))
            changed = True
        else:
            scrubbed.append(msg)
    return scrubbed if changed else messages


class MediaGuardMiddleware(AgentMiddleware):
    """模型调用前清洗不支持的媒体 block（文本-only 模型 400 防护）。"""

    @property
    def name(self) -> str:
        return "media-guard"

    def wrap_model_call(self, request, handler):
        messages = getattr(request, "messages", None) or []
        scrubbed = scrub_unsupported_media_blocks(messages)
        if scrubbed is not messages:
            request = request.override(messages=scrubbed)
        return handler(request)

    async def awrap_model_call(self, request, handler):
        messages = getattr(request, "messages", None) or []
        scrubbed = scrub_unsupported_media_blocks(messages)
        if scrubbed is not messages:
            request = request.override(messages=scrubbed)
        return await handler(request)
