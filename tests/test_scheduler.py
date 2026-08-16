"""scheduler 模块测试。

Seam: src.scheduler.load_schedules / resolve_save_path / _run_task / make_scheduler。
验证：JSON 配置读取（含 disabled 过滤）、save_path 前缀解析、任务执行写文件、
make_scheduler 注册 job。用 fake agent 不触网。
"""
import json

from apscheduler.schedulers.background import BackgroundScheduler

from src import scheduler
from conftest import make_fake_config


def _write_schedule(sdir, name, data):
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_load_schedules_filters_disabled(tmp_path):
    cfg = make_fake_config(tmp_path)
    _write_schedule(cfg.schedules_dir, "a.json", {"id": "a", "task": "t", "cron": "0 8 * * *"})
    _write_schedule(cfg.schedules_dir, "b.json", {"id": "b", "task": "t", "enabled": False})

    tasks = scheduler.load_schedules(cfg.schedules_dir)
    assert [t["id"] for t in tasks] == ["a"]


def test_load_schedules_requires_id_and_task(tmp_path):
    cfg = make_fake_config(tmp_path)
    _write_schedule(cfg.schedules_dir, "bad.json", {"cron": "0 8 * * *"})
    try:
        scheduler.load_schedules(cfg.schedules_dir)
        assert False, "应当抛 ScheduleConfigError"
    except scheduler.ScheduleConfigError:
        pass


def test_resolve_save_path_vault(tmp_path):
    cfg = make_fake_config(tmp_path)
    assert scheduler.resolve_save_path(cfg, "vault:Inbox/") == (cfg.vault_path / "Inbox").resolve()
    assert scheduler.resolve_save_path(cfg, "workspace:out/") == (
        cfg.memory_dir.parent / "out"
    ).resolve()


def test_run_task_writes_file(tmp_path):
    cfg = make_fake_config(tmp_path)

    class FakeAgent:
        def invoke(self, input, config=None):
            return {"messages": [type("M", (), {"type": "ai", "content": "调研结果正文"})()]}

    task = {
        "id": "t1",
        "task": "调研 X",
        "save_path": "vault:Inbox/",
        "requirements": "输出中文",
    }
    scheduler._run_task(FakeAgent(), cfg, task)
    files = list((cfg.vault_path / "Inbox").glob("t1-*.md"))
    assert len(files) == 1
    assert "调研结果正文" in files[0].read_text(encoding="utf-8")


def test_make_scheduler_registers_jobs(tmp_path):
    cfg = make_fake_config(tmp_path)
    _write_schedule(cfg.schedules_dir, "a.json", {"id": "a", "task": "t", "cron": "0 8 * * *"})
    sched = scheduler.make_scheduler(object(), cfg)
    assert isinstance(sched, BackgroundScheduler)
    assert sched.get_job("javis-a") is not None


def test_register_jobs_returns_list(tmp_path):
    cfg = make_fake_config(tmp_path)
    _write_schedule(cfg.schedules_dir, "a.json", {"id": "a", "task": "t", "cron": "0 8 * * *"})
    _write_schedule(cfg.schedules_dir, "b.json", {"id": "b", "task": "t", "cron": "0 8 * * *"})
    sched = scheduler.make_scheduler(object(), cfg)
    reg = scheduler.register_jobs(sched, object(), cfg)
    assert sched.get_job("javis-a") is not None
    assert sched.get_job("javis-b") is not None
    assert len(reg) == 2
    assert "a" in reg[0] and "b" in reg[1]


def test_reload_schedules_replaces_cron(tmp_path):
    from datetime import datetime, timezone

    cfg = make_fake_config(tmp_path)
    _write_schedule(cfg.schedules_dir, "a.json", {"id": "a", "task": "t", "cron": "*/1 * * * *"})
    sched = scheduler.make_scheduler(object(), cfg)
    now = datetime.now(timezone.utc)
    before = sched.get_job("javis-a").trigger.get_next_fire_time(None, now)

    _write_schedule(cfg.schedules_dir, "a.json", {"id": "a", "task": "t", "cron": "0 8 * * *"})
    msg = scheduler.reload_schedules(sched, object(), cfg)
    after = sched.get_job("javis-a").trigger.get_next_fire_time(None, now)
    assert before != after
    assert "已重载" in msg
    assert "a" in msg


def test_run_task_error_writes_error_marker(tmp_path):
    cfg = make_fake_config(tmp_path)

    class BoomAgent:
        def invoke(self, input, config=None):
            raise RuntimeError("网络失败")

    task = {"id": "err", "task": "调研 X", "save_path": "vault:Inbox/"}
    try:
        scheduler._run_task(BoomAgent(), cfg, task)
        assert False, "应当抛异常"
    except RuntimeError:
        pass
    err_files = list((cfg.vault_path / "Inbox").glob("err-*.error.md"))
    assert len(err_files) == 1
    assert "网络失败" in err_files[0].read_text(encoding="utf-8")


def test_describe_cron():
    assert scheduler.describe_cron("0 8 * * *") == "每天 08:00"
    assert scheduler.describe_cron("*/5 * * * *") == "每 5 分钟"
    assert scheduler.describe_cron("30 14 * * *") == "每天 14:30"
    assert scheduler.describe_cron("0 */2 * * *") == "每 2 小时"
    assert scheduler.describe_cron("0 0 */2 * *") == "每 2 天"
    assert scheduler.describe_cron("0 8 * * 1") == "0 8 * * 1"