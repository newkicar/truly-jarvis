"""定时检索调度器（二期，APScheduler）。

从 schedules/*.json 读取任务配置（时间/任务/保存路径/要求），用 APScheduler
注册定时触发；到点时调用主代理执行研究任务，把最终回答按 save_path 写文件。

save_path 前缀约定：
- `vault:`   → 相对 Obsidian vault 根（如 `vault:Inbox/`）
- `workspace:` → 相对项目根
- 其它      → 相对项目根

仅进程内调度，随 CLI 启动时挂载；不常驻。
"""
import json
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import Config


class ScheduleConfigError(ValueError):
    pass


def load_schedules(schedules_dir: Path) -> list[dict]:
    """读取 schedules/ 下所有 *.json 任务配置，过滤 disabled。"""
    schedules_dir = Path(schedules_dir)
    tasks = []
    if not schedules_dir.exists():
        return tasks
    for path in sorted(schedules_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not data.get("enabled", True):
            continue
        if not data.get("id") or not data.get("task"):
            raise ScheduleConfigError(f"{path.name}: 缺少 id 或 task")
        tasks.append({"file": path.name, **data})
    return tasks


def resolve_save_path(config: Config, save_path: str) -> Path:
    """把 save_path 前缀解析为绝对路径。"""
    save_path = (save_path or "vault:Inbox/").strip()
    if save_path.startswith("vault:"):
        return (config.vault_path / save_path[len("vault:"):]).resolve()
    if save_path.startswith("workspace:"):
        return (config.memory_dir.parent / save_path[len("workspace:"):]).resolve()
    return (config.memory_dir.parent / save_path).resolve()


def _run_task(agent, config: Config, task: dict):
    """执行单个定时任务：跑 agent 研究 → 写结果到 save_path。"""
    save_path = resolve_save_path(config, str(task.get("save_path", "")))
    save_path.mkdir(parents=True, exist_ok=True)

    prompt = task["task"]
    req = task.get("requirements", "")
    if req:
        prompt = f"{prompt}\n\n要求：{req}"

    result = agent.invoke(
        {"messages": [{"role": "user", "content": prompt}]},
        config={"configurable": {"thread_id": f"sched-{task['id']}"}, "recursion_limit": 30},
    )
    texts = [m.content for m in result["messages"] if getattr(m, "type", "") == "ai"]
    if not texts:
        return
    body = texts[-1]

    stamp = datetime.now().strftime("%Y-%m-%d")
    file_path = save_path / f"{task['id']}-{stamp}.md"
    header = f"# {task['id']} — {stamp}\n\n"
    file_path.write_text(header + body, encoding="utf-8")


def make_scheduler(agent, config: Config) -> BackgroundScheduler:
    """装配调度器：为每个 enabled 任务注册 CronTrigger。"""
    scheduler = BackgroundScheduler()
    for task in load_schedules(config.schedules_dir):
        cron = task.get("cron", "0 8 * * *")
        scheduler.add_job(
            _run_task,
            CronTrigger.from_crontab(cron),
            args=[agent, config, task],
            id=f"javis-{task['id']}",
            replace_existing=True,
        )
    return scheduler