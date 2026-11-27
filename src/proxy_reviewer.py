"""#19: LLM 裁决层（proxy.review）——HITL ask 时的「替我审批」。

定位：gated 工具调用的基础动作解析为 ask（未被 YOLO 短路 / 确定性规则表
（proxy_auto_allow、只读启发式）/ 显式 deny 定案）时，若当前线程处于
「替我审批」（ADR-0014 proxy_threads）且 jarvis.json 的 proxy.review 段
enabled=true，由 LLM 裁决该调用是否可自动放行（escalation-only 一期：
只开放 ask→allow 提升，critical 一律回落 ask）。裁决 fail-closed：
模型异常 / JSON 解析失败 / 枚举越界一律回落原审批（ask），绝不自动放行。

入口 = permissions._build_when 的 when 谓词（惰性 import 防循环依赖）；
三个依赖键由 #18 注入共享 permission state（纯 expand）：
  - state[PROXY_REVIEW_KEY]        裁决层配置 dict（enabled/timeout_s/...）
  - state[PROXY_REVIEW_MODEL_KEY]  裁决层模型客户端（None = 无）
  - state[PROXY_REVIEW_LAST_KEY]   最近裁决记录 dict（#19 写 / #20 呈现）

门控三条件（缺一即 inert：零模型调用、零审计行、零 LAST_KEY 写入）：
  1. 配置 enabled=True；
  2. 当前 thread proxy_active（ADR-0014 开关）；
  3. state 有模型客户端。

幂等：指纹 sha1(tool+args+thread+最后用户消息+project_root) → 模块级缓存
（上限 1000，满则逐出最旧）；HITL resume/重入命中缓存不重调模型、不写
审计行，仅刷新 state[PROXY_REVIEW_LAST_KEY]（cache_hit=True）。

reasoning-blind（缺省 True）：prompt 可信来源 = 最后用户消息（截 2000）
+ AGENTS.md（截 4000）+ policy_extra（追加不替换），不含工具输出；
显式 False 时追加最近一条工具结果（截 2000）。输出只许 JSON
{risk, authorization, rationale(≤80字)}。

审计：每次非缓存裁决追加一条 jsonl 记录到 cfg["audit_log"]
（缺省 ~/.jarvis/logs/proxy-review.jsonl）；写失败静默（审计不影响门链路）。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from src.permissions import (
    PROXY_REVIEW_BREAKERS_KEY,
    PROXY_REVIEW_KEY,
    PROXY_REVIEW_LAST_KEY,
    PROXY_REVIEW_MODEL_KEY,
    PROXY_REVIEW_OVERRIDES_KEY,
    _current_turn_tid,
    proxy_active,
)

_REVIEW_CACHE: dict[str, dict] = {}
_CACHE_LIMIT = 1000
# #21: 一次性覆盖每线程上限（同任务 10 条；第 11 次 deny 回落 ask、不再提供覆盖入口）
OVERRIDE_CAP = 10
_RISK_ENUM = ("low", "medium", "high", "critical")
_GLOB_CHARS = frozenset("*?[")
_USER_ROLES = frozenset({"human", "user"})
_TOOL_ROLES = frozenset({"tool"})
_INSTRUCTIONS_CAP = 4000
_CONTEXT_CAP = 2000
_ARGS_JSON_CAP = 4000
# #21: 线程级断路器状态（state[PROXY_REVIEW_BREAKERS_KEY][tid]）
_BreakerState = dict  # {"streak": int, "window": list, "tripped": bool}


def clear_review_cache() -> None:
    """清空指纹缓存（测试隔离 / 进程边界手动重置）。"""
    _REVIEW_CACHE.clear()


def review_last_record(state: dict | None, tool: str, thread_id: str = "") -> dict | None:
    """"#20: 取共享 state 的最近裁决记录（state[PROXY_REVIEW_LAST_KEY]）。

    呈现层（TUI ⚡ 标记 / CLI ⚡ / 审批注记）读这一个键：
    - state 非 dict / 键缺失 / 非 dict / tool 不匹配 → None；
    - thread_id 非空时要求记录 thread_id 相等（跨线程记录不呈现）；
    命中即返回记录的浅拷贝，调用方只读。
    """
    if not isinstance(state, dict):
        return None
    rec = state.get(PROXY_REVIEW_LAST_KEY)
    if not isinstance(rec, dict) or not rec:
        return None
    if str(rec.get("tool", "")) != tool:
        return None
    if thread_id and str(rec.get("thread_id", "")) != thread_id:
        return None
    return dict(rec)


def proxy_review_upgrade(state: dict, tool: str, args: dict, request: object = None) -> bool:
    """裁决一次 ask 是否升级放行。True = 自动放行（when 不中断）；False = 维持原审批。"""
    if state is None or not tool:
        return False
    tid = _current_turn_tid(state)
    if not _gate_active(state, tid):
        return False
    # #21: 断路器已触发 → 该线程停用裁决层：不调模型 / 不写审计 / 不写缓存，回落人工审批
    if breaker_tripped(state, tid):
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tool": tool,
            "outcome": "ask",
            "risk": "",
            "authorization": "",
            "rationale": "",
            "note": "断路器已触发：该线程裁决层停用，回落人工审批",
            "fingerprint": "",
            "thread_id": tid,
            "cache_hit": False,
            "breaker_tripped": True,
        }
        _record_last(state, rec)
        return False
    args = args if isinstance(args, dict) else {}
    user_text = _last_role_text(request, _USER_ROLES, _CONTEXT_CAP)
    fp = _fingerprint(tool, args, tid, user_text, state.get("project_root"))
    cached = _cache_lookup(fp)
    if cached is not None:
        last = dict(cached)
        last["cache_hit"] = True
        _record_last(state, last)
        # 缓存命中不推进断路器计数（非新的模型裁决）
        return last.get("outcome") == "allow"
    cfg = state.get(PROXY_REVIEW_KEY) or {}
    prompt = _build_review_prompt(cfg, tool, args, request, user_text, state.get("project_root"))
    verdict, note = _decide(cfg, state.get(PROXY_REVIEW_MODEL_KEY), prompt)
    outcome = review_outcome(
        str(verdict.get("risk", "")),
        str(verdict.get("authorization", "")),
        scope_is_narrow(tool, args),
    )
    # #21: critical → deny（开放模型否决）；一次性覆盖每线程上限，耗尽后降级 ask（回落人工审批）
    if outcome == "deny" and not override_budget_left(state, tid):
        outcome = "ask"
        note = "覆盖上限（10 条）已达，回落人工审批"
    # #20/#21: 成功裁决回落人工审批（outcome=ask）时填 note（失败路径 note 已由 _decide 给出）
    if outcome == "ask" and not note:
        risk = str(verdict.get("risk", ""))
        if risk == "high":
            note = "high 风险未收窄范围，回落人工审批"
        else:
            note = "裁决回落人工审批"
    # #21: 断路器仅统计成功的模型裁决（verdict 非空；解析失败 / fail-closed 路径不计数）
    if verdict:
        _record_verdict_breaker(state, tid, outcome, cfg)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool": tool,
        "outcome": outcome,
        "risk": str(verdict.get("risk", "")),
        "authorization": str(verdict.get("authorization", "")),
        "rationale": str(verdict.get("rationale", "")),
        "note": note,
        "fingerprint": fp[:12],
        "thread_id": tid,
        "cache_hit": False,
    }
    _write_audit(cfg, record)
    _cache_store(fp, record)
    _record_last(state, record)
    return outcome == "allow"


def review_outcome(risk: str, authorization: str, narrow: bool) -> str:
    """裁决矩阵（纯函数，#21 起开放模型 deny）：

    - low/medium → allow（无脑放行）；
    - high → 仅当 authorization ∈ {medium, high, critical} 且 narrow-scope 才 allow，否则 ask；
    - critical → deny（模型否决；审批 modal 展示 rationale + 一次性覆盖入口，
      每线程覆盖上限 OVERRIDE_CAP，耗尽后由 proxy_review_upgrade 降级 ask）；
    - 枚举越界 / 缺失 → ask（fail-closed）。
    """
    risk = str(risk or "").strip().lower()
    auth = str(authorization or "").strip().lower()
    if risk not in _RISK_ENUM:
        return "ask"
    if risk in ("low", "medium"):
        return "allow"
    if risk == "high":
        return "allow" if (auth in ("medium", "high", "critical") and narrow) else "ask"
    return "deny"  # critical（#21）：模型否决


def scope_is_narrow(tool: str, args: dict) -> bool:
    """narrow-scope 纯字符串判定（不 resolve 路径、不碰文件系统）：

    - write_file/edit_file：单一具体路径（非空、无 glob 通配、非逗号多路径）；
      edit_file 另需锚点 old_str/pattern 非空（无锚点 = 盲改，不 narrow）；
    - delete：单一具体文件路径；
    - execute 与其他工具一律 False（命令副作用面无法按字符串收窄）。
    """
    if not isinstance(args, dict):
        return False
    if tool in ("write_file", "edit_file"):
        path = args.get("file_path", args.get("path"))
        if not _is_single_concrete_path(path):
            return False
        if tool == "edit_file":
            anchor = args.get("old_str", args.get("pattern"))
            if not isinstance(anchor, str) or not anchor.strip():
                return False
        return True
    if tool == "delete":
        return _is_single_concrete_path(args.get("path", args.get("file_path")))
    return False


def _gate_active(state: dict, tid: str) -> bool:
    cfg = state.get(PROXY_REVIEW_KEY)
    if not isinstance(cfg, dict) or not cfg.get("enabled"):
        return False
    if state.get(PROXY_REVIEW_MODEL_KEY) is None:
        return False
    return proxy_active(state, tid)


def _fingerprint(tool: str, args: dict, tid: str, user_text: str, project_root: object) -> str:
    payload = json.dumps(args, sort_keys=True, default=str, ensure_ascii=False)
    raw = "\x00".join((tool, payload, tid, user_text, str(project_root)))
    return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()


def _cache_lookup(fp: str) -> dict | None:
    hit = _REVIEW_CACHE.get(fp)
    if hit is not None:
        _REVIEW_CACHE.pop(fp)
        _REVIEW_CACHE[fp] = hit  # 刷新为最近使用
    return hit


def _cache_store(fp: str, record: dict) -> None:
    _REVIEW_CACHE[fp] = record
    while len(_REVIEW_CACHE) > _CACHE_LIMIT:
        _REVIEW_CACHE.pop(next(iter(_REVIEW_CACHE)))


def _record_last(state: dict, record: dict) -> None:
    if state is not None:
        state[PROXY_REVIEW_LAST_KEY] = dict(record)


def _build_review_prompt(
    cfg: dict, tool: str, args: dict, request: object, user_text: str, project_root: object
) -> str:
    reasoning_blind = bool(cfg.get("reasoning_blind", True))
    tool_result = "" if reasoning_blind else _last_role_text(request, _TOOL_ROLES, _CONTEXT_CAP)
    sections = [
        "你是权限审批系统的 LLM 裁决层（替我审批）。一个工具调用即将由代理执行，"
        "按用户配置的规则它本需人工审批（ask）。请判断这个调用是否安全、可代用户放行。",
        "### 当前工具调用\n工具: " + tool + "\n参数: "
        + json.dumps(args, ensure_ascii=False, default=str, sort_keys=True)[:_ARGS_JSON_CAP],
    ]
    if user_text:
        sections.append("### 用户最近消息（意图上下文）\n" + user_text)
    instructions = _load_instructions(project_root)
    if instructions:
        sections.append("### 项目约定（AGENTS.md 摘要）\n" + instructions)
    if tool_result:
        sections.append("### 最近工具执行结果（补充）\n" + tool_result)
    policy_extra = str(cfg.get("policy_extra") or "").strip()
    if policy_extra:
        sections.append("### 额外策略（用户自定义）\n" + policy_extra)
    sections += [
        "判定口径：",
        "- risk = 该调用失败或被滥用时的潜在损害。low=几乎无害；medium=局部且可恢复；"
        "high=可能伤及项目或用户数据；critical=不可逆或破坏性。",
        "- authorization = 结合用户最近消息与项目约定，用户对「这类操作」的明确授权程度。"
        "critical=明确点名要求；high=明确要求；medium=可合理推断需要；low=与意图无关或来源可疑。",
        "- 拿不准时一律保守（risk 取高、authorization 取低）。",
        "只输出一个 JSON 对象（不要任何其他文字）："
        '{"risk": "low|medium|high|critical", "authorization": "low|medium|high|critical", '
        '"rationale": "80字以内理由"}',
    ]
    return "\n\n".join(sections)


def _load_instructions(project_root: object) -> str:
    try:
        from src.project_paths import load_project_instructions

        return str(load_project_instructions(project_root) or "")[:_INSTRUCTIONS_CAP]
    except Exception:
        return ""


def _last_role_text(request: object, roles: frozenset, limit: int = 2000) -> str:
    if request is None:
        return ""
    for msg in reversed(_messages_of(getattr(request, "state", None))):
        if _role_of(msg) in roles:
            return _content_to_text(_content_of(msg))[:limit]
    return ""


def _messages_of(gstate: object) -> list:
    if gstate is None:
        return []
    msgs = gstate.get("messages") if isinstance(gstate, dict) else getattr(gstate, "messages", None)
    if msgs is None:
        return []
    try:
        return list(msgs)
    except TypeError:
        return [msgs]


def _role_of(msg: object) -> str:
    role = getattr(msg, "type", None)
    if role is None and isinstance(msg, dict):
        role = msg.get("role") or msg.get("type")
    return str(role or "").lower()


def _content_of(msg: object) -> object:
    if isinstance(msg, dict):
        return msg.get("content", "")
    return getattr(msg, "content", "")


def _content_to_text(content: object) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return str(content)


def _invoke_once(model: object, prompt: str, timeout_s: int) -> str:
    try:
        resp = model.invoke(prompt, timeout=timeout_s)
    except TypeError:
        resp = model.invoke(prompt)
    content = getattr(resp, "content", resp)
    if isinstance(content, dict):
        content = content.get("content", content.get("text", ""))
    return _content_to_text(content)


def _decide(cfg: dict, model: object, prompt: str) -> tuple[dict, str]:
    text = ""
    last_err: Exception | None = None
    attempts = max(1, int(cfg.get("retries") or 3))
    for _ in range(attempts):
        try:
            text = _invoke_once(model, prompt, int(cfg.get("timeout_s") or 30))
            last_err = None
            break
        except Exception as exc:  # noqa: BLE001 - fail-closed，异常类型多样
            last_err = exc
    if last_err is not None:
        return {}, f"审查失败（{type(last_err).__name__}）；审查失败 ≠ 不安全，回落人工审批"
    verdict, note = _parse_review_json(text)
    if note:
        return {}, note
    return verdict, ""


def _parse_review_json(text: str) -> tuple[dict, str]:
    body = str(text or "")
    start = body.find("{")
    end = body.rfind("}")
    if start < 0 or end <= start:
        return {}, "JSON 解析失败：模型输出无对象"
    try:
        data = json.loads(body[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return {}, "JSON 解析失败"
    if not isinstance(data, dict):
        return {}, "JSON 解析失败：顶层非对象"
    risk = str(data.get("risk") or "").strip().lower()
    auth = str(data.get("authorization") or "").strip().lower()
    if risk not in _RISK_ENUM or auth not in _RISK_ENUM:
        return {}, f"JSON 解析失败：risk/authorization 越界（{risk!r}/{auth!r}）"
    return {
        "risk": risk,
        "authorization": auth,
        "rationale": str(data.get("rationale") or "")[:80],
    }, ""


def _is_single_concrete_path(value: object) -> bool:
    if not isinstance(value, str):
        return False
    v = value.strip()
    if not v or "," in v:
        return False
    if any(ch in _GLOB_CHARS for ch in v):
        return False
    return True


# ---------------- #21: 一次性覆盖预算 + 线程级断路器 ----------------


def override_budget_left(state: dict | None, thread_id: str) -> int:
    """#21: 该线程剩余的一次性覆盖次数（上限 OVERRIDE_CAP；缺省全量可用）。"""
    if not isinstance(state, dict):
        return OVERRIDE_CAP
    used = state.get(PROXY_REVIEW_OVERRIDES_KEY)
    used = used.get(str(thread_id)) if isinstance(used, dict) else 0
    if not isinstance(used, int) or used < 0:
        used = 0
    return max(OVERRIDE_CAP - used, 0)


def record_override(state: dict | None, thread_id: str) -> int:
    """#21: 记录该线程一次一次性覆盖（人工放行模型 deny），返回已用次数。"""
    if not isinstance(state, dict):
        return 0
    overrides = state.setdefault(PROXY_REVIEW_OVERRIDES_KEY, {})
    if not isinstance(overrides, dict):
        overrides = {}
        state[PROXY_REVIEW_OVERRIDES_KEY] = overrides
    used = overrides.get(str(thread_id))
    overrides[str(thread_id)] = (used + 1) if isinstance(used, int) else 1
    return overrides[str(thread_id)]


def breaker_tripped(state: dict | None, thread_id: str) -> bool:
    """#21: 该线程断路器是否已触发（触发即会话内不复位，裁决层整体停用）。"""
    if not isinstance(state, dict):
        return False
    breakers = state.get(PROXY_REVIEW_BREAKERS_KEY)
    rec = breakers.get(str(thread_id)) if isinstance(breakers, dict) else None
    return bool(isinstance(rec, dict) and rec.get("tripped"))


def _record_verdict_breaker(
    state: dict, thread_id: str, outcome: str, cfg: dict | None
) -> None:
    """#21: 记录一次成功的模型裁决进断路器计数。

    触发条件（任一即触发，触发后会话内不复位）：
    - 连续 deny 达 deny_streak（缺省 3）；或
    - 滑动窗口（缺省 50 次裁决）内 deny 达 deny_in_window（缺省 10）。
    allow / ask 裁决清零连续计数但窗口保留（非 deny 也占窗口名额）。
    阈值读 cfg["breaker"]（config.resolve_proxy_review 已归一）；缺省回落 3/10/50。
    """
    if not isinstance(state, dict):
        return
    breaker_cfg = (cfg or {}).get("breaker")
    breaker_cfg = breaker_cfg if isinstance(breaker_cfg, dict) else {}
    streak_cap = int(breaker_cfg.get("deny_streak") or 3)
    window_cap = int(breaker_cfg.get("deny_in_window") or 10)
    window_size = int(breaker_cfg.get("window") or 50)
    breakers = state.setdefault(PROXY_REVIEW_BREAKERS_KEY, {})
    if not isinstance(breakers, dict):
        breakers = {}
        state[PROXY_REVIEW_BREAKERS_KEY] = breakers
    rec = breakers.get(str(thread_id))
    if not isinstance(rec, dict):
        rec = {"streak": 0, "window": [], "tripped": False}
        breakers[str(thread_id)] = rec
    window = rec.get("window")
    if not isinstance(window, list):
        window = []
        rec["window"] = window
    streak = int(rec.get("streak") or 0)
    if outcome == "deny":
        streak += 1
    else:
        streak = 0  # allow / ask（降级后）清零连续计数，窗口保留
    window.append(outcome)
    if len(window) > window_size:
        del window[: len(window) - window_size]
    rec["streak"] = streak
    if streak >= streak_cap or window.count("deny") >= window_cap:
        rec["tripped"] = True


def proxy_review_note(
    state: dict | None, tool: str, thread_id: str = "", override_hint: bool = False
) -> tuple[str | None, bool]:
    """#21: 统一生成审批注记 (note, override)。

    - 最近裁决 outcome=deny 且尚有覆盖预算 → note = rationale（空则「模型否决」），
      override_hint=True 时追加「｜可一次性覆盖（本线程剩 N 次）」，override=True
      （呈现层据此显示「一次性覆盖」按钮）；
    - 最近裁决 outcome=ask → note = 记录内 note（解析失败 / 覆盖上限 / 断路器 / 高风险回落），override=False；
    - 其余（allow / 无记录 / tool 不匹配 / 跨线程）→ (None, False)。
    """
    rec = review_last_record(state, tool, thread_id)
    if not rec:
        return None, False
    outcome = rec.get("outcome")
    if outcome == "deny":
        if override_budget_left(state, str(thread_id or "")) <= 0:
            return None, False
        note = str(rec.get("rationale") or "模型否决")
        if override_hint:
            note += "｜可一次性覆盖（本线程剩 %d 次）" % override_budget_left(state, str(thread_id or ""))
        return note, True
    if outcome == "ask":
        return (str(rec.get("note") or "") or None), False
    return None, False


def _write_audit(cfg: dict, record: dict) -> None:
    try:
        path = Path(os.path.expanduser(str(cfg.get("audit_log") or "")))
        if not path.parts:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - 审计失败不影响门链路
        return


__all__ = [
    "OVERRIDE_CAP",
    "breaker_tripped",
    "clear_review_cache",
    "override_budget_left",
    "proxy_review_note",
    "proxy_review_upgrade",
    "record_override",
    "review_last_record",
    "review_outcome",
    "scope_is_narrow",
]