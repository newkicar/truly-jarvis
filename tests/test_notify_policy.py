"""notify_policy / notify_channels 单测（gui bgnotify：任务完成三通道通知内核）。

纯内存 + monkeypatch 平台 seam（notify_channels 的 _is_windows / _message_beep /
_powershell），不触网、不弹窗、不跑真 PowerShell；不用 tmp_path（自建目录纪律）。
"""
from src.gui import notify_channels as nc
from src.gui import notify_policy as npol


# ---------- NotificationPolicy.from_config ----------


def test_from_config_non_dict_defaults():
    for raw in (None, "x", [1], 42):
        pol = npol.NotificationPolicy.from_config(raw)
        assert pol.sound is True
        assert pol.voice is False
        assert pol.email is False
        assert pol.email_cfg == {}


def test_from_config_bool_coercion():
    raw = {"sound": "yes", "voice": 0, "email": 1, "email_cfg": {"to": "a@b.c"}}
    pol = npol.NotificationPolicy.from_config(raw)
    assert pol.sound is True
    assert pol.voice is False
    assert pol.email is True
    assert pol.email_cfg == {"to": "a@b.c"}


def test_from_config_email_cfg_non_dict():
    pol = npol.NotificationPolicy.from_config({"email": True, "email_cfg": [1]})
    assert pol.email is True
    assert pol.email_cfg == {}


# ---------- TaskDoneEvent 缺省标题 ----------


def test_event_title_scheduled():
    ev = npol.TaskDoneEvent(kind="scheduled", thread_id="sched-rep")
    assert ev.title == "定时任务 rep 完成"
    ev2 = npol.TaskDoneEvent(kind="scheduled", thread_id="sched-rep", ok=False)
    assert ev2.title == "定时任务 rep 失败"
    ev3 = npol.TaskDoneEvent(kind="scheduled", thread_id="rawid")
    assert ev3.title == "定时任务 rawid 完成"


def test_event_title_chat_and_explicit():
    assert npol.TaskDoneEvent().title == "会话回合完成"
    assert npol.TaskDoneEvent(ok=False).title == "会话回合失败"
    assert npol.TaskDoneEvent(title="自定义").title == "自定义"


# ---------- 各通道文案 ----------


def test_voice_text():
    ev = npol.TaskDoneEvent()
    assert npol.voice_text(ev) == ev.title
    ev2 = npol.TaskDoneEvent(detail="结果文件：t1.md")
    assert npol.voice_text(ev2) == f"{ev2.title}，详情：{ev2.detail}"
    ev3 = npol.TaskDoneEvent()
    ev3.title = ""
    assert npol.voice_text(ev3) == "任务完成"


def test_email_subject():
    ev = npol.TaskDoneEvent()
    assert npol.email_subject(ev) == f"[JARVIS] {ev.title}"
    ev2 = npol.TaskDoneEvent(root="C:\\proj")
    assert npol.email_subject(ev2) == f"[JARVIS] {ev2.title}（C:\\proj）"


def test_email_content_scheduled():
    ev = npol.TaskDoneEvent(kind="scheduled", thread_id="sched-t1", root="P:", detail="vault/Inbox/t1.md")
    lines = npol.email_content(ev).split("\n")
    assert lines[0] == f"标题：{ev.title}"
    assert lines[1] == "项目：P:"
    assert lines[2] == "会话/任务：t1"
    assert lines[3] == "结果文件：vault/Inbox/t1.md"
    assert lines[4] == "状态：成功"


def test_email_content_chat_no_detail():
    ev = npol.TaskDoneEvent(thread_id="abc", ok=False)
    lines = npol.email_content(ev).split("\n")
    assert len(lines) == 5
    assert lines[1] == "项目：-"
    assert lines[2] == "会话：abc"
    assert lines[3] == "结果：-（无补充信息）"
    assert lines[4] == "状态：失败"


def test_email_content_scheduled_non_sched_prefix_thread():
    ev = npol.TaskDoneEvent(kind="scheduled", thread_id="rawtid")
    assert npol.email_content(ev).split("\n")[2] == "会话/任务：rawtid"


# ---------- TaskNotifier.fire ----------


def _rec():
    def fn(*args):
        fn.calls.append(args)
        return "ok"

    fn.calls = []
    return fn


def test_fire_all_channels():
    sound, voice, email = _rec(), _rec(), _rec()
    pol = npol.NotificationPolicy(sound=True, voice=True, email=True, email_cfg={"to": "a@b.c"})
    n = npol.TaskNotifier({"sound": sound, "voice": voice, "email": email}, pol)
    ev = npol.TaskDoneEvent(thread_id="abc", detail="结果：x.md")
    res = n.fire(ev)
    assert res == {"sound": "ok", "voice": "ok", "email": "ok"}
    assert sound.calls == [()]
    assert voice.calls == [(npol.voice_text(ev),)]
    assert email.calls == [("a@b.c", npol.email_subject(ev), npol.email_content(ev))]


def test_fire_hook_nonstr_returns_ok():
    def ret_none(*args):
        return None

    def ret_int(*args):
        return 3

    def ret_list(*args):
        return [1]

    pol = npol.NotificationPolicy(sound=True, voice=True, email=True, email_cfg={"to": "a@b.c"})
    n = npol.TaskNotifier({"sound": ret_none, "voice": ret_int, "email": ret_list}, pol)
    res = n.fire(npol.TaskDoneEvent())
    assert res == {"sound": "ok", "voice": "ok", "email": "ok"}


def test_fire_hook_raise_becomes_error_status():
    def boom(*args):
        raise ValueError("boom")

    pol = npol.NotificationPolicy(sound=True)
    n = npol.TaskNotifier({"sound": boom}, pol)
    assert n.fire(npol.TaskDoneEvent())["sound"] == "error:boom"


def test_fire_disabled_channels_not_called():
    sound, voice, email = _rec(), _rec(), _rec()
    n = npol.TaskNotifier({"sound": sound, "voice": voice, "email": email})  # 缺省 policy：仅 sound 开
    res = n.fire(npol.TaskDoneEvent())
    assert res == {"sound": "ok", "voice": "disabled", "email": "disabled"}
    assert sound.calls and not voice.calls and not email.calls


def test_fire_email_no_recipient_skips_hook():
    email = _rec()
    pol = npol.NotificationPolicy(sound=False, email=True)  # email_cfg 缺省 → to 空
    n = npol.TaskNotifier({"email": email}, pol)
    res = n.fire(npol.TaskDoneEvent())
    assert res["email"] == "skipped:no-recipient"
    assert res["sound"] == "disabled"
    assert not email.calls


def test_fire_missing_hook():
    pol = npol.NotificationPolicy(sound=True, voice=True, email=True, email_cfg={"to": "a@b.c"})
    n = npol.TaskNotifier({}, pol)
    res = n.fire(npol.TaskDoneEvent())
    assert all(v == "error:missing-hook" for v in res.values())


def test_notifier_without_policy_defaults_sound_on():
    sound = _rec()
    n = npol.TaskNotifier({"sound": sound})
    assert n.policy is None
    res = n.fire(npol.TaskDoneEvent())
    assert res["sound"] == "ok"
    assert res["voice"] == "disabled"
    assert res["email"] == "disabled"


# ---------- notify_channels 平台 seam ----------


def test_play_sound_windows(monkeypatch):
    calls = []
    monkeypatch.setattr(nc, "_is_windows", lambda: True)
    monkeypatch.setattr(nc, "_message_beep", lambda: calls.append(1))
    assert nc.play_sound() == "ok"
    assert calls == [1]


def test_play_sound_non_windows_skipped(monkeypatch):
    calls = []
    monkeypatch.setattr(nc, "_is_windows", lambda: False)
    monkeypatch.setattr(nc, "_message_beep", lambda: calls.append(1))
    assert nc.play_sound() == "skipped-non-windows"
    assert calls == []


def test_play_sound_beep_error(monkeypatch):
    monkeypatch.setattr(nc, "_is_windows", lambda: True)

    def boom():
        raise Exception("no winmm")

    monkeypatch.setattr(nc, "_message_beep", boom)
    assert nc.play_sound() == "error:no winmm"


def test_speak_windows_script(monkeypatch):
    scripts = []
    monkeypatch.setattr(nc, "_is_windows", lambda: True)
    monkeypatch.setattr(nc, "_powershell", lambda s: scripts.append(s) or "done")
    assert nc.speak("任务 j1 完成") == "ok"
    assert "System.Speech" in scripts[0]
    assert "$s.Speak('任务 j1 完成')" in scripts[0]


def test_speak_non_windows_skipped(monkeypatch):
    scripts = []
    monkeypatch.setattr(nc, "_is_windows", lambda: False)
    monkeypatch.setattr(nc, "_powershell", lambda s: scripts.append(s) or "done")
    assert nc.speak("x") == "skipped-non-windows"
    assert scripts == []


def test_speak_powershell_error(monkeypatch):
    monkeypatch.setattr(nc, "_is_windows", lambda: True)

    def boom(s):
        raise RuntimeError("ps down")

    monkeypatch.setattr(nc, "_powershell", boom)
    assert nc.speak("x") == "error:ps down"


def test_email_empty_to_before_platform(monkeypatch):
    monkeypatch.setattr(nc, "_is_windows", lambda: True)
    assert nc.send_outlook_email("", "s", "b") == "skipped:no-recipient"
    monkeypatch.setattr(nc, "_is_windows", lambda: False)
    assert nc.send_outlook_email("", "s", "b") == "skipped:no-recipient"


def test_email_windows_script(monkeypatch):
    scripts = []
    monkeypatch.setattr(nc, "_is_windows", lambda: True)
    monkeypatch.setattr(nc, "_powershell", lambda s: scripts.append(s) or "done")
    assert nc.send_outlook_email("a@b.c", "s'u", "body") == "ok"
    script = scripts[0]
    assert "Outlook.Application" in script
    assert "$m = $o.CreateItem(0);" in script
    assert "$m.To = 'a@b.c'" in script
    assert "$m.Subject = 's''u'" in script
    assert "$m.Send()" in script


def test_email_non_windows_skipped(monkeypatch):
    scripts = []
    monkeypatch.setattr(nc, "_is_windows", lambda: False)
    monkeypatch.setattr(nc, "_powershell", lambda s: scripts.append(s) or "done")
    assert nc.send_outlook_email("a@b.c", "s", "b") == "skipped-non-windows"
    assert scripts == []


def test_email_powershell_error(monkeypatch):
    monkeypatch.setattr(nc, "_is_windows", lambda: True)

    def boom(s):
        raise RuntimeError("Outlook not found")

    monkeypatch.setattr(nc, "_powershell", boom)
    assert nc.send_outlook_email("a@b.c", "s", "b") == "error:Outlook not found"


def test_ps_literal_doubles_quotes():
    assert nc._ps_literal("a'b") == "'a''b'"
    assert nc._ps_literal("plain") == "'plain'"


def test_make_hooks_identity():
    h = nc.make_hooks()
    assert set(h) == {"sound", "voice", "email"}
    assert h["sound"] is nc.play_sound
    assert h["voice"] is nc.speak
    assert h["email"] is nc.send_outlook_email
