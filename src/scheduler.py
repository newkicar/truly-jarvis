"""定时检索调度器（二期，APScheduler）。

从 schedules/*.json 读取任务配置（时间/任务/保存路径/要求），用 APScheduler
注册定时触发；到点时调用主代理执行研究任务，把最终回答按 save_path 写文件。

save_path 前缀约定：
- `vault:`   → 相对 Obsidian vault 根（如 `vault:Inbox/`）
- `workspace:` → 相对项目根
- 其它      → 相对项目根

仅进程内调度，随 CLI 启动时挂载；不常驻。
改 schedules/*.json 后可用 CLI 的 /reload-schedules 重载（无需重启）。
"""
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import Config
from src import inbox_snapshots
from src.commands import project_root


class ScheduleConfigError(ValueError):
    pass


def describe_cron(cron: str) -> str:
    """把 cron 表达式转成易读中文描述（用于启动/重载时的打印）。

    支持常见形态：每天定点（'0 8 * * *'）、每隔 N 分钟/小时/天（'*/5 * * * *'）。
    无法识别的原样返回。
    """
    try:
        parts = cron.split()
        if len(parts) != 5:
            return cron
        minute, hour, dom, month, dow = parts
        if dom == "*" and month == "*" and dow == "*":
            if hour != "*" and minute != "*" and hour.isdigit() and minute.isdigit():
                return f"每天 {int(hour):02d}:{int(minute):02d}"
            if hour == "*" and minute.startswith("*/"):
                return f"每 {minute[2:]} 分钟"
        if minute == "0" and hour.startswith("*/") and dom == "*" and month == "*" and dow == "*":
            return f"每 {hour[2:]} 小时"
        if minute == "0" and hour == "0" and dom.startswith("*/") and month == "*" and dow == "*":
            return f"每 {dom[2:]} 天"
    except ValueError:
        pass
    return cron


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
        try:
            validate_schedule_save_path(str(data.get("save_path", "vault:Inbox/")))
        except ScheduleConfigError as e:
            raise ScheduleConfigError(f"{path.name}: {e}") from e
        tasks.append({"file": path.name, **data})
    return tasks


def validate_schedule_save_path(save_path: str) -> None:
    """定时任务 save_path 必须指向 Vault Inbox。"""
    raw = (save_path or "vault:Inbox/").strip()
    if not raw.startswith("vault:"):
        raise ScheduleConfigError(
            f"save_path 必须指向 Vault Inbox（如 vault:Inbox/），当前为 {raw!r}"
        )
    rel = raw[len("vault:") :].strip("/").replace("\\", "/")
    if rel != "Inbox" and not rel.startswith("Inbox/"):
        raise ScheduleConfigError(
            f"save_path 必须落在 Inbox 内（vault:Inbox/），当前为 {raw!r}"
        )


def resolve_save_path(config: Config, save_path: str) -> Path:
    """把 save_path 前缀解析为绝对路径。"""
    validate_schedule_save_path(save_path)
    save_path = (save_path or "vault:Inbox/").strip()
    if save_path.startswith("vault:"):
        return (config.vault_path / save_path[len("vault:"):]).resolve()
    if save_path.startswith("workspace:"):
        return (config.memory_dir.parent / save_path[len("workspace:"):]).resolve()
    return (config.memory_dir.parent / save_path).resolve()


def _run_task(agent, config: Config, task: dict):
    """执行单个定时任务：跑 agent 研究 → 写结果到 save_path。

    失败绝不静默：打印 traceback 到 stderr、在 save_path 写 .error.md 标记，
    再 re-raise 让调度器记录。
    """
    save_path = resolve_save_path(config, str(task.get("save_path", "")))
    save_path.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")

    try:
        prompt = task["task"]
        req = task.get("requirements", "")
        if req:
            prompt = f"{prompt}\n\n要求：{req}"

        result = agent.invoke(
            {"messages": [{"role": "user", "content": prompt}]},
            config={"configurable": {"thread_id": f"sched-{task['id']}"}, "recursion_limit": 30},
        )
        # HITL：定时任务无人审批，若触发审批中断则视为失败（不悬挂，明确记录）
        interrupts = getattr(result, "interrupts", None) or []
        if interrupts:
            names = [
                a.get("name", "?")
                for i in interrupts
                for a in (getattr(i, "value", None) or {}).get("action_requests", [])
            ]
            raise RuntimeError(
                f"任务 {task['id']} 触发了需人工审批的操作（{', '.join(names)}），"
                "定时任务无审批交互，已跳过。可在 javis.json permissions 设为 allow。"
            )
        texts = [m.content for m in result["messages"] if getattr(m, "type", "") == "ai"]
        if not texts:
            raise RuntimeError(f"任务 {task['id']} 未产出 AI 回答")
        body = texts[-1]
    except Exception:
        err = traceback.format_exc()
        print(f"[定时任务 {task['id']}] 执行失败:\n{err}", file=sys.stderr, flush=True)
        err_file = save_path / f"{task['id']}-{stamp}.error.md"
        err_file.write_text(
            f"# 定时任务失败 — {task['id']} — {stamp}\n\n"
            f"任务：{task.get('task', '')}\n\n```\n{err}\n```\n",
            encoding="utf-8",
        )
        raise

    file_path = save_path / f"{task['id']}-{stamp}.md"
    header = f"# {task['id']} — {stamp}\n\n"
    thread_id = f"sched-{task['id']}"
    virtual_path = f"/vault/Inbox/{file_path.name}"
    pre_exists, pre_content = inbox_snapshots.read_pre_state(config.vault_path, virtual_path)
    inbox_snapshots.record_write(
        project_root(),
        thread_id=thread_id,
        checkpoint_id=f"sched-{task['id']}-{stamp}",
        virtual_path=virtual_path,
        pre_exists=pre_exists,
        pre_content=pre_content,
    )
    file_path.write_text(header + body, encoding="utf-8")

    _cleanup_thread(agent, task["id"])


def _cleanup_thread(agent, task_id: str):
    """删除定时任务自己的 checkpoint 线程，避免累积污染 /sessions 与 checkpoints 表。

    任务结果已写文件，会话过程无保留价值；失败也不影响（静默跳过）。
    """
    checkpointer = getattr(agent, "checkpointer", None)
    if checkpointer is None:
        return
    try:
        checkpointer.delete_thread(f"sched-{task_id}")
    except Exception:
        pass


def register_jobs(scheduler: BackgroundScheduler, agent, config: Config) -> list[str]:
    """读取 schedules/*.json 并为每个 enabled 任务注册/替换 job，返回易读清单。

    replace_existing=True：重载时同名 job 直接替换，天然覆盖旧 cron。
    """
    tasks = load_schedules(config.schedules_dir)
    for task in tasks:
        cron = task.get("cron", "0 8 * * *")
        scheduler.add_job(
            _run_task,
            CronTrigger.from_crontab(cron),
            args=[agent, config, task],
            id=f"javis-{task['id']}",
            replace_existing=True,
        )
    return [f"{t['id']}({describe_cron(t.get('cron', '0 8 * * *'))})" for t in tasks]


def make_scheduler(agent, config: Config) -> BackgroundScheduler:
    """装配调度器：为每个 enabled 任务注册 CronTrigger。"""
    scheduler = BackgroundScheduler()
    register_jobs(scheduler, agent, config)
    return scheduler


def reload_schedules(scheduler: BackgroundScheduler, agent, config: Config) -> str:
    """移除全部 javis-* job，按 schedules/*.json 当前内容重新注册。

    返回「已重载」文本；无任务时也返回空清单说明。
    """
    for job in scheduler.get_jobs():
        if job.id.startswith("javis-"):
            job.remove()
    registered = register_jobs(scheduler, agent, config)
    if not registered:
        return "已重载：schedules/ 下无 enabled 定时任务。"
    lines = [f"已重载 {len(registered)} 个定时任务:"] + [f"  - {r}" for r in registered]
    return "\n".join(lines)