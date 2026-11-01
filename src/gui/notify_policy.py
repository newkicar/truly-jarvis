"""gui 任务完成通知策略（gui bgnotify，纯 stdlib 无 Qt）。

jarvis.json 的 notifications 段 → NotificationPolicy（sound/voice/email 开关 +
email_cfg）；TaskDoneEvent 是事件载荷（会话回合 / 定时任务，含后台项目）；
TaskNotifier.fire 逐通道调用 hooks，返回每通道状态字符串（绝不外抛）。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TaskDoneEvent:
    """任务完成事件（worker/scheduler 线程构造，经 UiBridge 信号到主线程）。"""

    kind: str = "chat"  # "chat"（会话回合）/ "scheduled"（定时任务）
    root: str = ""  # 项目根（str；归一由消费端 normalize_root_key）
    thread_id: str = ""  # 会话 tid 或 "sched-<task_id>"
    ok: bool = True
    detail: str = ""  # 结果/错误文件路径等补充信息
    title: str = ""  # 缺省按 kind+ok 生成

    def __post_init__(self) -> None:
        if not self.title:
            self.title = self._default_title()

    def _default_title(self) -> str:
        ok_word = "完成" if self.ok else "失败"
        if self.kind == "scheduled":
            task_id = (
                self.thread_id[6:] if self.thread_id.startswith("sched-") else self.thread_id
            )
            return f"定时任务 {task_id} {ok_word}"
        return f"会话回合{ok_word}"


@dataclass
class NotificationPolicy:
    """notifications 段解析产物（全缺省：仅提示音开）。"""

    sound: bool = True
    voice: bool = False
    email: bool = False
    email_cfg: dict = field(default_factory=dict)

    @classmethod
    def from_config(cls, raw) -> "NotificationPolicy":
        """jarvis.json notifications 段（非 dict → 全缺省；email_cfg 非 dict → {}）。"""
        if not isinstance(raw, dict):
            return cls()
        email_cfg = raw.get("email_cfg", {})
        if not isinstance(email_cfg, dict):
            email_cfg = {}
        return cls(
            sound=bool(raw.get("sound", True)),
            voice=bool(raw.get("voice", False)),
            email=bool(raw.get("email", False)),
            email_cfg=email_cfg,
        )


def voice_text(ev: TaskDoneEvent) -> str:
    """语音播报文本 = 标题（＋detail 非空时「，详情：…」）。"""
    text = ev.title or "任务完成"
    if ev.detail:
        text = f"{text}，详情：{ev.detail}"
    return text


def email_subject(ev: TaskDoneEvent) -> str:
    """邮件主题：[JARVIS] 标题（＋项目根，非空时）。"""
    subject = f"[JARVIS] {ev.title or '任务完成'}"
    if ev.root:
        subject = f"{subject}（{ev.root}）"
    return subject


def email_content(ev: TaskDoneEvent) -> str:
    """邮件正文（多行纯文本）。"""
    task_id = (
        ev.thread_id[6:] if ev.thread_id.startswith("sched-") else ev.thread_id
    )
    lines = [
        f"标题：{ev.title or '任务完成'}",
        f"项目：{ev.root or '-'}",
        f"会话/任务：{task_id}" if ev.kind == "scheduled" else f"会话：{ev.thread_id or '-'}",
        f"结果文件：{ev.detail}" if ev.detail else "结果：-（无补充信息）",
        "状态：成功" if ev.ok else "状态：失败",
    ]
    return "\n".join(lines)


class TaskNotifier:
    """按策略逐通道触发 hooks（sound/voice/email），返回 {通道: 状态}。

    hooks 缺省 = make_hooks()（平台通道；非 Windows 返回 skipped 状态串）。
    通道级异常绝不外抛——通知失败不影响任务本身。
    """

    def __init__(self, hooks: "dict | None" = None, policy: "NotificationPolicy | None" = None) -> None:
        if hooks is None:
            from src.gui.notify_channels import make_hooks

            hooks = make_hooks()
        self.hooks = hooks
        self.policy = policy

    def fire(self, ev: TaskDoneEvent) -> "dict[str, str]":
        pol = self.policy or NotificationPolicy()
        result: dict[str, str] = {}
        if not pol.sound:
            result["sound"] = "disabled"
        else:
            result["sound"] = self._invoke("sound", ())
        if not pol.voice:
            result["voice"] = "disabled"
        else:
            result["voice"] = self._invoke("voice", (voice_text(ev),))
        if not pol.email:
            result["email"] = "disabled"
        else:
            to = str(pol.email_cfg.get("to", "") or "")
            if not to:
                result["email"] = "skipped:no-recipient"
            else:
                result["email"] = self._invoke("email", (to, email_subject(ev), email_content(ev)))
        return result

    def _invoke(self, name: str, args: tuple) -> str:
        fn = self.hooks.get(name)
        if fn is None:
            return "error:missing-hook"
        try:
            r = fn(*args)
            return r if isinstance(r, str) else "ok"
        except Exception as exc:  # noqa: BLE001 — 通道失败只记录状态串
            return f"error:{exc}"
