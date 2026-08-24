"""执行韧性层：错误分类学 + 重试 + 步数软着陆 + doom-loop 防御。

对标 codex / opencode harness 的可靠性工程：
- 错误类型 = 决策表（分诊优先于行动，switch(类型) 而非字符串猜测）；
- 重试四要素：致命白名单、retry-after 优先、指数退避 ± 抖动、状态事件全程知情；
- 失败是数据不是异常（工具错误回给模型自纠，只有崩溃才中断回合）；
- 检测器保持愚蠢，处置权交给策略层（doom-loop 只附加引导，不擅自掐断）。
"""
from __future__ import annotations

import json
import random
import time
from collections import deque
from collections.abc import Callable

from langchain.agents.middleware.types import AgentMiddleware

RETRY_INITIAL_DELAY = 2.0
RETRY_BACKOFF_FACTOR = 2.0
RETRY_JITTER = 0.25
RETRY_MAX_DELAY = 30.0
RETRY_MAX_ATTEMPTS = 5

# 致命白名单：重试必然再失败（病因未除），绝不烧钱重试。
NEVER_RETRY_MARKERS = (
    "context_length_exceeded",
    "invalid_api_key",
    "insufficient_quota",
    "maximum context length",
)

# retryable：网络抖动、限流、5xx、流损坏、opencode 端点偶发 400。
_RETRYABLE_MARKERS = (
    "rate limit",
    "ratelimit",
    "429",
    "500",
    "502",
    "503",
    "504",
    "timeout",
    "timed out",
    "connection",
    "temporarily unavailable",
    "overloaded",
    "bad gateway",
    "stream disconnected",
    "stream ended unexpectedly",
)

_AUTH_MARKERS = ("401", "403", "unauthorized", "forbidden", "invalid_api_key", "authentication")
_OVERFLOW_MARKERS = (
    "context_length_exceeded",
    "maximum context length",
    "context window",
    "too many tokens",
)

ERROR_CATEGORIES = ("aborted", "auth", "context_overflow", "retryable", "fatal")


def _matches(msg: str, markers: tuple[str, ...]) -> bool:
    return any(m in msg for m in markers)


def classify_error(exc: BaseException) -> str:
    """错误分诊：返回 ERROR_CATEGORIES 之一。

    决策表（对标 opencode 错误分类学）：
      aborted          → 用户取消，正常收尾不重试
      auth             → key 失效/无权限，提示用户，不重试
      context_overflow → 必然复发，路由压缩/终止，绝不原样重试
      retryable        → 5xx/网络/限流/流断/opencode 偶发 400，退避重试
      fatal            → 其余，正式失败上抛
    """
    name = type(exc).__name__
    lower_name = name.lower()
    msg = str(exc).lower()

    if isinstance(exc, KeyboardInterrupt) or "cancel" in lower_name or "interrupt" in lower_name:
        return "aborted"
    if _matches(msg, _OVERFLOW_MARKERS):
        return "context_overflow"
    if "auth" in lower_name or _matches(msg[:200], _AUTH_MARKERS):
        return "auth"
    if _matches(msg, NEVER_RETRY_MARKERS):
        # invalid_api_key 已被 auth 分支接住；这里兜住其余致命项。
        return "fatal" if "insufficient_quota" in msg else "context_overflow"
    if "badrequest" in lower_name:
        return "retryable"  # opencode 端点偶发 400 可重试
    if "ratelimit" in lower_name or "apiconnection" in lower_name or "apitimeout" in lower_name:
        return "retryable"
    if _matches(msg, _RETRYABLE_MARKERS):
        return "retryable"
    return "fatal"


def extract_retry_after(exc: BaseException) -> float | None:
    """从 RateLimitError 等异常取服务器指示的等待秒数（retry-after 头）。"""
    body = getattr(exc, "response", None)
    headers = getattr(body, "headers", None) if body is not None else None
    if not headers:
        return None
    for key in ("retry-after", "retry_after"):
        try:
            raw = headers.get(key)
        except Exception:
            raw = None
        if raw is None:
            continue
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            continue
    return None


def backoff_delay(attempt: int, *, retry_after: float | None = None) -> float:
    """第 attempt 次（0 起）重试前的等待秒数。

    retry-after 优先于本地策略——服务器比我们懂它什么时候有空。
    本地策略：initial × factor^attempt，封顶 MAX_DELAY，再乘 ±JITTER 抖动防雪崩。
    """
    base = min(RETRY_INITIAL_DELAY * RETRY_BACKOFF_FACTOR**attempt, RETRY_MAX_DELAY)
    delay = base * (1 + random.uniform(-RETRY_JITTER, RETRY_JITTER))
    if retry_after is not None:
        delay = max(delay, min(retry_after, RETRY_MAX_DELAY))
    return delay


def with_retry(
    fn: Callable[[], object],
    *,
    attempts: int = RETRY_MAX_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
    on_status: Callable[[int, int, float], None] | None = None,
    should_stop: Callable[[], bool] = lambda: False,
) -> object:
    """带退避的同步重试。on_status(attempt, total, wait) 驱动 UI 倒计时。"""
    last_exc: BaseException | None = None
    for attempt in range(attempts):
        if should_stop():
            raise last_exc if last_exc is not None else RuntimeError("retry cancelled")
        try:
            return fn()
        except Exception as exc:
            category = classify_error(exc)
            if category != "retryable" or attempt == attempts - 1:
                raise
            last_exc = exc
            wait = backoff_delay(attempt, retry_after=extract_retry_after(exc))
            if on_status is not None:
                on_status(attempt + 1, attempts - 1, wait)
            sleep(wait)
    raise last_exc if last_exc is not None else RuntimeError("unreachable")


# ---------------------------------------------------------------- 中间件


SOFT_LAND_STEPS = 3

SOFT_LAND_REMINDER = (
    "[系统提醒] 步数预算即将用尽。请立即停止开启新工作："
    "收敛当前进度，核对已有结果，输出交付总结"
    "（已完成什么、未完成什么、下一步建议）。不要再发起新的工具调用链。"
)

HARD_STOP_REMINDER = (
    "[系统提醒] 步数预算已用尽。本轮必须立即以纯文本总结收尾，禁止任何工具调用。"
)


def _count_model_steps(messages) -> int:
    """已发生的模型步数 = 历史中 AIMessage 数（每次模型响应记一步）。"""
    from langchain_core.messages import AIMessage

    return sum(1 for m in messages if isinstance(m, AIMessage))


class StepBudgetMiddleware(AgentMiddleware):
    """接近步数预算时注入一次性软着陆提醒（对标 opencode MAX_STEPS_PROMPT）。

    到预算不是硬掐：最后几步改为「禁开新工作、总结交付」，模型有机会交代状态。
    提醒拼进本次请求的 system 尾部（ModelRequest.override），不写入持久历史。
    """

    def __init__(self, max_steps: int = 200):
        super().__init__()
        self.max_steps = max(1, int(max_steps))

    @property
    def name(self) -> str:
        return "step-budget"

    def _with_reminder(self, request, reminder: str):
        from langchain_core.messages import SystemMessage

        base = getattr(request, "system_message", None)
        text = str(getattr(base, "text", None) or getattr(base, "content", "") or "")
        merged = f"{text}\n\n{reminder}" if text else reminder
        return request.override(system_message=SystemMessage(content=merged))

    def wrap_model_call(self, request, handler):
        messages = list(getattr(request, "messages", None) or [])
        remaining = self.max_steps - _count_model_steps(messages)
        if 0 < remaining <= SOFT_LAND_STEPS:
            request = self._with_reminder(request, SOFT_LAND_REMINDER)
        elif remaining <= 0:
            # 兜底：软着陆被忽略时给出最终通牒（下一跳 recursion_limit 才会硬断）。
            request = self._with_reminder(request, HARD_STOP_REMINDER)
        return handler(request)

    async def awrap_model_call(self, request, handler):
        return self.wrap_model_call(request, lambda r: handler(r))


DOOM_LOOP_THRESHOLD = 3

DOOM_LOOP_GUIDANCE = (
    "\n\n[系统提示] 该调用已连续 {n} 次以相同参数失败。禁止原样重试。"
    "请先诊断根因（读报错信息、检查前置条件），再换一种方案；"
    "若连续换方案仍失败，停下向用户报告已尝试清单与卡点。"
)

TOOL_ERROR_GUIDANCE = (
    "\n\n[系统提示] 工具执行抛出了异常（不是正常错误返回）。"
    "把上面的报错当作数据：先诊断根因，再换一种合法方案；不要原样重试。"
)


def _tool_signature(request) -> tuple[str, str]:
    tool_call = getattr(request, "tool_call", None) or {}
    args = tool_call.get("args") or {}
    try:
        canonical = json.dumps(args, sort_keys=True, default=str)
    except (TypeError, ValueError):
        canonical = repr(args)
    return str(tool_call.get("name", "?")), canonical


class ToolErrorBoundaryMiddleware(AgentMiddleware):
    """工具异常兜底：任何工具抛出的异常都转为错误 ToolMessage（失败是数据）。

    框架的工具边界只保护部分校验路径（如 utils.validate_path）；backend 层
    抛出的异常（如越界路径 ValueError）会击穿工具函数直达 graph，把整轮
    对话炸死——模型连第三次尝试的机会都没有。本中间件保证：无论异常从
    哪一层冒出，模型收到的都是可读的错误数据 + 换方案引导。
    """

    @property
    def name(self) -> str:
        return "tool-error-boundary"

    def _to_error_message(self, request, exc: BaseException):
        from langchain_core.messages import ToolMessage

        tool_call = getattr(request, "tool_call", None) or {}
        content = (
            f"Error: {type(exc).__name__}: {exc}"
            f"{TOOL_ERROR_GUIDANCE}"
        )
        return ToolMessage(
            content=content,
            name=str(tool_call.get("name", "?")),
            tool_call_id=str(tool_call.get("id", "")),
            status="error",
        )

    def wrap_tool_call(self, request, handler):
        try:
            return handler(request)
        except Exception as exc:  # noqa: BLE001 — 工具边界：异常必须变成数据，不能逃逸
            return self._to_error_message(request, exc)

    async def awrap_tool_call(self, request, handler):
        try:
            return await handler(request)
        except Exception as exc:  # noqa: BLE001
            return self._to_error_message(request, exc)


class DoomLoopMiddleware(AgentMiddleware):
    """复读机防御（对标 opencode doom_loop）：同名同参且失败连续 N 次 → 注入引导。

    检测器保持愚蠢：只认「完全相同的失败调用」；成功或参数变化即清零，
    不误伤合法轮询。处置是附加引导文本（失败是数据），不擅自中断回合。
    """

    def __init__(self, threshold: int = DOOM_LOOP_THRESHOLD):
        super().__init__()
        self.threshold = max(2, int(threshold))
        self._streaks: dict[tuple[str, str], int] = {}

    @property
    def name(self) -> str:
        return "doom-loop"

    def _augment(self, request, result):
        sig = _tool_signature(request)
        failed = getattr(result, "status", None) == "error"
        if not failed:
            self._streaks.pop(sig, None)
            return result
        count = self._streaks.get(sig, 0) + 1
        self._streaks[sig] = count
        if count < self.threshold:
            return result
        content = getattr(result, "content", "")
        result.content = f"{content}{DOOM_LOOP_GUIDANCE.format(n=count)}"
        return result

    def wrap_tool_call(self, request, handler):
        return self._augment(request, handler(request))

    async def awrap_tool_call(self, request, handler):
        return self._augment(request, await handler(request))

    def reset(self) -> None:
        self._streaks.clear()
