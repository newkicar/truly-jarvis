"""gui 任务完成通知策略测试（notify_policy 纯逻辑，无 Qt、不触碰平台通道）。

Seam: src.gui.notify_policy.NotificationPolicy.from_config / TaskDoneEvent 默认标题 /
voice_text / email_subject / email_content / TaskNotifier.fire（fake hooks，绝不调 make_hooks）。
"""
import types

from src.gui.notify_policy import (
    NotificationPolicy,
    TaskDoneEvent,
    TaskNotifier,
    email_content,
    email_subject,
    voice_text,
)


# ---------------------------------------------------------------- 策略解析
def test_from_config_none_and_non_dict_defaults():
    p = NotificationPolicy.from_config(None)
    assert p.sound is True and p.voice is False and p.email is False
    assert p.email_cfg == {}
    assert NotificationPolicy.from_config(["sound"]).voice is False
    assert NotificationPolicy.from_config("notifications").email is False


def test_from_config_email_cfg_non_dict_to_empty():
    p = NotificationPolicy.from_config({"email_cfg": "not-a-dict", "email": True})
    assert p.email_cfg == {} and p.email is True


def test_from_config_explicit_fields():
    p = NotificationPolicy.from_config(
        {"sound": False, "voice": True, "email": True, "email_cfg": {"to": "a@b.c"}}
    )
    assert p.sound is False and p.voice is True and p.email is True
    assert p.email_cfg == {"to": "a@b.c"}


# ---------------------------------------------------------------- 事件默认标题
def test_default_title_chat():
    assert TaskDoneEvent(ok=True).title == "会话回合完成"
    assert TaskDoneEvent(ok=False).title == "会话回合失败"


def test_default_title_scheduled_sched_prefix():
    assert (
        TaskDoneEvent(kind="scheduled", thread_id="sched-daily", ok=True).title
        == "定时任务 daily 完成"
    )
    assert (
        TaskDoneEvent(kind="scheduled", thread_id="sched-daily", ok=False).title
        == "定时任务 daily 失败"
    )


def test_default_title_scheduled_verbatim_thread():
    ev = TaskDoneEvent(kind="scheduled", thread_id="myjob")
    assert ev.title == "定时任务 myjob 完成"


def test_explicit_title_wins():
    assert TaskDoneEvent(title="自定义").title == "自定义"
    assert TaskDoneEvent(ok=False, title="自定义").title == "自定义"


# ---------------------------------------------------------------- 播报/邮件文本
def test_voice_text_detail_suffix():
    ev = TaskDoneEvent(detail="结果：/tmp/out.md")
    assert voice_text(ev) == "会话回合完成，详情：结果：/tmp/out.md"


def test_voice_text_fallback_word_when_title_empty():
    ev = types.SimpleNamespace(title="", detail="d")
    assert voice_text(ev) == "任务完成，详情：d"


def test_email_subject_with_and_without_root():
    ev = TaskDoneEvent(root="D:/proj")
    assert email_subject(ev) == "[JARVIS] 会话回合完成（D:/proj）"
    assert email_subject(TaskDoneEvent()) == "[JARVIS] 会话回合完成"


def test_email_content_scheduled_ok_with_detail():
    ev = TaskDoneEvent(kind="scheduled", root="R", thread_id="sched-x", detail="f.md")
    assert email_content(ev) == "\n".join(
        [
            "标题：定时任务 x 完成",
            "项目：R",
            "会话/任务：x",
            "结果文件：f.md",
            "状态：成功",
        ]
    )


def test_email_content_chat_fail_no_detail():
    ev = TaskDoneEvent(thread_id="t1", ok=False)
    assert email_content(ev) == "\n".join(
        [
            "标题：会话回合失败",
            "项目：-",
            "会话：t1",
            "结果：-（无补充信息）",
            "状态：失败",
        ]
    )


# ---------------------------------------------------------------- fire（fake hooks）
def _capture_hooks(calls):
    def record(kind):
        def hook(*args):
            calls.append((kind, args))
            return "ok"
        return hook

    return {"sound": record("sound"), "voice": record("voice"), "email": record("email")}


def test_fire_all_on_three_invocations():
    calls = []
    n = TaskNotifier(
        _capture_hooks(calls),
        NotificationPolicy(sound=True, voice=True, email=True, email_cfg={"to": "a@b"}),
    )
    ev = TaskDoneEvent(root="R", thread_id="t1", detail="d")
    r = n.fire(ev)
    assert r == {"sound": "ok", "voice": "ok", "email": "ok"}
    assert [c[0] for c in calls] == ["sound", "voice", "email"]
    by_kind = dict(calls)
    assert by_kind["sound"] == ()
    assert by_kind["voice"] == (voice_text(ev),)
    assert by_kind["email"] == ("a@b", email_subject(ev), email_content(ev))


def test_fire_all_off_zero_invocations():
    calls = []
    n = TaskNotifier(
        _capture_hooks(calls),
        NotificationPolicy(sound=False, voice=False, email=False),
    )
    assert n.fire(TaskDoneEvent()) == {"sound": "disabled", "voice": "disabled", "email": "disabled"}
    assert calls == []


def test_fire_email_on_but_no_recipient():
    calls = []
    hooks = _capture_hooks(calls)
    r1 = TaskNotifier(
        hooks, NotificationPolicy(sound=False, voice=False, email=True, email_cfg={})
    ).fire(TaskDoneEvent())
    assert r1["email"] == "skipped:no-recipient"
    r2 = TaskNotifier(
        hooks, NotificationPolicy(sound=False, voice=False, email=True, email_cfg={"to": ""})
    ).fire(TaskDoneEvent())
    assert r2["email"] == "skipped:no-recipient"
    assert calls == []


def test_fire_missing_hook_key():
    n = TaskNotifier({"sound": lambda *a: "ok"}, NotificationPolicy(voice=True))
    r = n.fire(TaskDoneEvent())
    assert r["sound"] == "ok"
    assert r["voice"] == "error:missing-hook"
    assert r["email"] == "disabled"


def test_fire_hook_exception_becomes_error_status():
    def boom(*a):
        raise ValueError("boom")

    n = TaskNotifier({"sound": boom}, NotificationPolicy())
    r = n.fire(TaskDoneEvent())
    assert r["sound"].startswith("error:") and "boom" in r["sound"]


def test_fire_non_str_return_coerced_to_ok():
    n = TaskNotifier({"sound": lambda *a: None}, NotificationPolicy())
    assert n.fire(TaskDoneEvent())["sound"] == "ok"


def test_notifier_without_policy_defaults_sound_only():
    calls = []
    n = TaskNotifier(_capture_hooks(calls), policy=None)
    assert n.fire(TaskDoneEvent()) == {"sound": "ok", "voice": "disabled", "email": "disabled"}
    assert [c[0] for c in calls] == ["sound"]
