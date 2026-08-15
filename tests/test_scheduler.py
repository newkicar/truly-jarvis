"""scheduler 模块测试。

Seam: src.scheduler.load_schedules / resolve_save_path / _run_task / make_scheduler。
验证：JSON 配置读取（含 disabled 过滤）、save_path 前缀解析、任务执行写文件、
make_scheduler 注册 job。用 fake agent 不触网。
"""
import json

from apscheduler.schedulers.background import BackgroundScheduler

from src.config import Config
from src import scheduler


def _fake_config(tmp_path):
    return Config(
        base_url="https://fake/v1",
        api_key="sk",
        model_id="m",
        tavily_key="tvly",
        vault_path=tmp_path / "vault",
        memory_dir=tmp_path / "memory",
        checkpoint_db=tmp_path / "cp.sqlite",
        schedules_dir=tmp_path / "schedules",
        skills=(),
        mcps=(),
        schedules=(),
    )


def _write_schedule(sdir, name, data):
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_load_schedules_filters_disabled(tmp_path):
    cfg = _fake_config(tmp_path)
    _write_schedule(cfg.schedules_dir, "a.json", {"id": "a", "task": "t", "cron": "0 8 * * *"})
    _write_schedule(cfg.schedules_dir, "b.json", {"id": "b", "task": "t", "enabled": False})

    tasks = scheduler.load_schedules(cfg.schedules_dir)
    assert [t["id"] for t in tasks] == ["a"]


def test_load_schedules_requires_id_and_task(tmp_path):
    cfg = _fake_config(tmp_path)
    _write_schedule(cfg.schedules_dir, "bad.json", {"cron": "0 8 * * *"})
    try:
        scheduler.load_schedules(cfg.schedules_dir)
        assert False, "应当抛 ScheduleConfigError"
    except scheduler.ScheduleConfigError:
        pass


def test_resolve_save_path_vault(tmp_path):
    cfg = _fake_config(tmp_path)
    assert scheduler.resolve_save_path(cfg, "vault:Inbox/") == (cfg.vault_path / "Inbox").resolve()
    assert scheduler.resolve_save_path(cfg, "workspace:out/") == (
        cfg.memory_dir.parent / "out"
    ).resolve()


def test_run_task_writes_file(tmp_path):
    cfg = _fake_config(tmp_path)

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
    cfg = _fake_config(tmp_path)
    _write_schedule(cfg.schedules_dir, "a.json", {"id": "a", "task": "t", "cron": "0 8 * * *"})
    sched = scheduler.make_scheduler(object(), cfg)
    assert isinstance(sched, BackgroundScheduler)
    assert sched.get_job("javis-a") is not None