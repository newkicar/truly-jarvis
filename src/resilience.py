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
import re
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
DOOM_LOOP_HARD_LIMIT = 5

DOOM_LOOP_GUIDANCE = (
    "\n\n[系统提示] 该调用已连续 {n} 次以相同参数失败。禁止原样重试。"
    "请先诊断根因（读报错信息、检查前置条件），再换一种方案；"
    "若连续换方案仍失败，停下向用户报告已尝试清单与卡点。"
)

DOOM_LOOP_HARD_BREAK = (
    "[harness 拒绝执行] 该调用已连续 {n} 次以相同参数失败，本次调用在执行前已被 harness 拦截。"
    "同名同参的后续调用同样会被拒绝——继续原样重试只会得到本消息。\n"
    "必须换方法类别（换工具 / 换路径形态 / 换入口；微调参数或引号不算），"
    "或立即停下向用户报告「已尝试清单 + 报错原文 + 卡点」。"
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
    不误伤合法轮询。

    两级处置（0006 课原则：提示词是建议，代码才是边界）：
    - threshold（默认 3）：软引导——失败结果后附加换方案提示；
    - hard_limit（默认 5）：硬熔断——**不再执行工具**，直接返回 error ToolMessage，
      物理切断原样重试路径。弱模型无视软引导时由代码强制刹车。

    失败判定有两类信号：
    - ToolMessage.status == "error"（工具层错误）；
    - execute 类工具的 exit code（deepagents execute 失败时 status 仍是
      success，退出码体现在内容尾部状态行
      "[Command failed with exit code N]" / "[Command succeeded with exit code 0]"）。
    """

    _CMD_STATUS_RE = re.compile(r"\[Command (succeeded|failed) with exit code (\d+)\]")

    def __init__(
        self,
        threshold: int = DOOM_LOOP_THRESHOLD,
        hard_limit: int = DOOM_LOOP_HARD_LIMIT,
    ):
        super().__init__()
        self.threshold = max(2, int(threshold))
        self.hard_limit = max(self.threshold + 1, int(hard_limit))
        self._streaks: dict[tuple[str, str], int] = {}

    @property
    def name(self) -> str:
        return "doom-loop"

    @staticmethod
    def _is_failure(result) -> bool:
        if getattr(result, "status", None) == "error":
            return True
        content = getattr(result, "content", "")
        if not isinstance(content, str):
            return False
        matches = DoomLoopMiddleware._CMD_STATUS_RE.findall(content)
        if matches:
            cmd_status, code = matches[-1]
            return cmd_status == "failed" or code != "0"
        return False

    def _hard_break(self, request):
        from langchain_core.messages import ToolMessage

        tool_call = getattr(request, "tool_call", None) or {}
        sig = _tool_signature(request)
        return ToolMessage(
            content=DOOM_LOOP_HARD_BREAK.format(n=self._streaks.get(sig, 0) + 1),
            name=str(tool_call.get("name", "?")),
            tool_call_id=str(tool_call.get("id", "")),
            status="error",
        )

    def _augment(self, request, result):
        sig = _tool_signature(request)
        if not self._is_failure(result):
            self._streaks.pop(sig, None)
            return result
        count = self._streaks.get(sig, 0) + 1
        self._streaks[sig] = count
        if count >= self.hard_limit:
            # 兜底（正常路径在 wrap_tool_call 预检已拦截）：结果替换为硬熔断。
            return self._hard_break(request)
        if count < self.threshold:
            return result
        content = getattr(result, "content", "")
        result.content = f"{content}{DOOM_LOOP_GUIDANCE.format(n=count)}"
        return result

    def wrap_tool_call(self, request, handler):
        # 预检提前一档：第 hard_limit 次尝试在执行前拦截（工具总共最多执行 hard_limit-1 次）。
        if self._streaks.get(_tool_signature(request), 0) >= self.hard_limit - 1:
            return self._hard_break(request)
        return self._augment(request, handler(request))

    async def awrap_tool_call(self, request, handler):
        if self._streaks.get(_tool_signature(request), 0) >= self.hard_limit - 1:
            return self._hard_break(request)
        return self._augment(request, await handler(request))

    def reset(self) -> None:
        self._streaks.clear()


STAGNATION_WINDOW = 6
STAGNATION_SOFT = 3
STAGNATION_HARD = 6
STAGNATION_JACCARD = 0.7

STAGNATION_SOFT_GUIDANCE = (
    "\n\n[系统提示] {tool} 已连续 {n} 次以高度相似的参数被调用——"
    "只是微调参数、未获得新信息。请停止逐词追加，改为：① 用已获取的信息直接作答；"
    "② 换方法类别（换工具 / 换数据源 / 换入口——微调参数不算换方案）；"
    "③ 仍卡住则停下向用户报告「已尝试什么、缺什么、卡点」。"
)

STAGNATION_HARD_BREAK = (
    "[harness 拒绝执行] {tool} 已连续 {n} 次以高度相似的参数被调用，"
    "本次调用在执行前已被 harness 拦截——继续沿此方向不会带来新信息。"
    "请改用已获取的信息直接作答，或换方法类别（换工具 / 换数据源 / 换入口）；"
    "仍卡住则向用户报告「已尝试清单 + 缺什么 + 卡点」。"
)

# 硬熔断 error ToolMessage 的前缀标记（测试 / harness 文桉共用同一出处）。
STAGNATION_BLOCKED_MARKER = "[harness 拒绝执行]"

_ASCII_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")


def arg_tokens(args: object) -> frozenset[str]:
    """把工具参数规范化成 token 集（纯 stdlib；CJK 用双字）。

    用于「近似重复」的 Jaccard 相似度：ASCII 保留 [a-z0-9]{2,}
    （避免单数字/符号误判）；CJK 取连续段的字符双字（「长春」相邻 -> ["长春"]，
    单个 CJK 段贡献该字符本身），让中文查询一字之差仍算高度相似。None/空 -> frozenset()。
    """
    if args is None:
        return frozenset()
    try:
        text = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = repr(args)
    text = text.lower()
    tokens: list[str] = _ASCII_TOKEN_RE.findall(text)
    for run in _CJK_RUN_RE.findall(text):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return frozenset(tokens)


def token_similarity(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard 相似度：交/并。双空 -> 1.0，一空 -> 0.0。"""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _request_scope(request) -> tuple[str, str]:
    """返回 (工具名, thread 作用域)。scope 防御式取 thread_id，缺省 "default"。

    支持两种 request 形态：对象属性 (.state) 与 dict (["state"])；
    测试用的无 state 假 request 落入 "default" 作用域。
    """
    tool_call = getattr(request, "tool_call", None) or {}
    state = getattr(request, "state", None)
    if state is None and isinstance(request, dict):
        state = request.get("state")
    thread_id = "default"
    if isinstance(state, dict):
        configurable = state.get("configurable")
        if isinstance(configurable, dict):
            thread_id = str(configurable.get("thread_id") or "default")
    return str(tool_call.get("name", "?")), thread_id


class StagnationGuardMiddleware(AgentMiddleware):
    """停滞防御（doom-loop 的泛化）：同一工具以高度相似参数成功 N 次连发 -> 注入引导 / 硬熔断。

    补 DoomLoopMiddleware 的盲区：DoomLoop 只抓「精确重复签名 且 失败」；
    「调用全成功 + 参数每次加一个词」（逐词堆砌式搜索）才是烧穿步数预算的常见
    现实病灶——检测器必须认「成功但不前进」。检测器保持愚蠢：参数 token 集
    （ASCII 字母数字 + CJK 双字）做 Jaccard，滑窗 STAGNATION_WINDOW、阈值
    STAGNATION_JACCARD；两级处置同 doom-loop：
    - STAGNATION_SOFT（3 次）：软引导——成功结果尾部追加换方案提示；
    - STAGNATION_HARD（6 次）：硬熔断——不执行工具，直接返回 error ToolMessage。
    作用域 = thread_id，各会话独立计数；不同工具独立计数；
    参数显著不同（相似度 < 阈值）立即清零 streak，合法批量工作 / fan-out 不误伤。
    """

    def __init__(
        self,
        window: int = STAGNATION_WINDOW,
        soft: int = STAGNATION_SOFT,
        hard: int = STAGNATION_HARD,
        jaccard: float = STAGNATION_JACCARD,
    ):
        super().__init__()
        self.window = max(2, int(window))
        self.soft = max(2, int(soft))
        self.hard = max(self.soft + 1, int(hard))
        self.jaccard = float(jaccard)
        self._windows: dict[str, dict[str, deque[frozenset[str]]]] = {}
        self._streaks: dict[str, dict[str, int]] = {}

    @property
    def name(self) -> str:
        return "stagnation-guard"

    def _near(self, scope: str, tool: str, tokens: frozenset[str]) -> int:
        """tokens 与最近 window 内任一调用是否近似；更新并返回 streak。

        近似 -> +1（累加）；显著不同 -> 0（清零重武装）。
        """
        window = self._windows.setdefault(scope, {}).setdefault(
            tool, deque(maxlen=self.window)
        )
        streaks = self._streaks.setdefault(scope, {})
        near = any(token_similarity(tokens, w) >= self.jaccard for w in window)
        streak = streaks.get(tool, 0) + 1 if near else 0
        streaks[tool] = streak
        return streak

    def _record(self, scope: str, tool: str, tokens: frozenset[str]) -> None:
        self._windows.setdefault(scope, {}).setdefault(
            tool, deque(maxlen=self.window)
        ).append(tokens)

    def _hard_break(self, request, tool: str, streak: int):
        from langchain_core.messages import ToolMessage

        tool_call = getattr(request, "tool_call", None) or {}
        return ToolMessage(
            content=STAGNATION_HARD_BREAK.format(n=streak, tool=tool),
            name=tool,
            tool_call_id=str(tool_call.get("id", "")),
            status="error",
        )

    def _pre_check(self, request) -> tuple[str, str, frozenset[str], int]:
        tool, scope = _request_scope(request)
        args = (getattr(request, "tool_call", None) or {}).get("args") or {}
        tokens = arg_tokens(args)
        streak = self._near(scope, tool, tokens)
        return tool, scope, tokens, streak

    def _post(self, request, tool, scope, tokens, streak, result):
        if streak >= self.hard:
            # 兜底（正常路径已在 wrap/awrap 预检拦截）：不执行，返回 error。
            return self._hard_break(request, tool, streak)
        self._record(scope, tool, tokens)
        if streak >= self.soft:
            content = getattr(result, "content", "")
            if isinstance(content, str):
                result.content = f"{content}{STAGNATION_SOFT_GUIDANCE.format(n=streak, tool=tool)}"
        return result

    def wrap_tool_call(self, request, handler):
        tool, scope, tokens, streak = self._pre_check(request)
        if streak >= self.hard:
            return self._hard_break(request, tool, streak)
        return self._post(request, tool, scope, tokens, streak, handler(request))

    async def awrap_tool_call(self, request, handler):
        tool, scope, tokens, streak = self._pre_check(request)
        if streak >= self.hard:
            return self._hard_break(request, tool, streak)
        return self._post(request, tool, scope, tokens, streak, await handler(request))

    def reset(self) -> None:
        self._windows.clear()
        self._streaks.clear()
