"""梦境沉淀：回顾近期会话，蒸馏可复用知识进长期记忆知识库。

设计（.scratch/javis-dream/spec.md）：
- 蒸馏走 langmem ``create_thread_extractor``（schema 抽取 + tool-call 调用；
  无 tool call / 模型异常 / 解析失败一律静默回落空列表——梦境是后台知识活动，
  不允许炸穿调用链）；
- 合并走一次模型 JSON 调用（新+旧 → 去重/冲突以新为准/≤max），解析失败回落
  顺序保留去重；
- 知识库 = ``memory/dream/knowledge.md``（bullet 列表）；运行日志 = ``memory/dream/runs.md``；
- cron 仅进程内：``jarvis.json`` 的 ``dream.enabled``（默认 true）/
  ``dream.cron``（默认 "0 3 * * *"），只在 app 运行中触发，不深夜拉起进程；
- 手动入口 = ``/dream`` 命令（commands.py 延迟 import 本模块，无循环依赖）；
- 知识库文件存在时由 agent.py 显式补注入长期记忆（顶层 glob 非递归）。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from src import commands
from src.config import Config

DREAM_DIR = "dream"
KNOWLEDGE_NAME = "knowledge.md"
RUN_LOG_NAME = "runs.md"
DEFAULT_CRON = "0 3 * * *"
MAX_ITEMS = 50

DEFAULT_DISTILL_INSTRUCTIONS = (
    "你是 JARVIS 助手的知识沉淀器。回顾下面的对话，蒸馏出以后还能直接复用的知识："
    "常用操作步骤、踩坑与解法、用户偏好、项目约定、已验证有效的工具/命令/参数组合。"
    "只沉淀「下次遇到同类事能直接照着做」的条目，不沉淀一次性闲聊与单次具体结果。"
    "每条一行简洁中文要点（≤80 字）。没有可沉淀内容时返回空列表。"
)


class DreamItems(BaseModel):
    """langmem schema 抽取目标：知识库条目列表。"""

    items: list[str]


def dream_job_config(config: Config) -> tuple[bool, str]:
    """从 ``jarvis.json`` ``dream`` 段读 (enabled, cron)；缺省 enabled=True、cron='0 3 * * *'。"""
    raw = getattr(config, "dream", None)
    cfg = raw if isinstance(raw, dict) else {}
    enabled = bool(cfg.get("enabled", True))
    cron = cfg.get("cron", DEFAULT_CRON)
    if not isinstance(cron, str) or not cron.strip():
        cron = DEFAULT_CRON
    return enabled, cron.strip()


def knowledge_dir(config: Config) -> Path:
    """知识库目录：memory/dream/。"""
    return config.memory_dir / DREAM_DIR


def load_knowledge(config: Config) -> list[str]:
    """读现有知识库 bullet 行（``- `` 前缀）；文件不存在返回 []。"""
    path = knowledge_dir(config) / KNOWLEDGE_NAME
    if not path.exists():
        return []
    items: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("- ") and line[2:].strip():
            items.append(line[2:].strip())
    return items


def write_knowledge(config: Config, items: list[str]) -> Path:
    """整体重写知识库文件（标题 + bullet 行）；返回文件路径。"""
    path = knowledge_dir(config) / KNOWLEDGE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 梦境知识库", ""]
    lines.extend(f"- {x}" for x in items)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def append_run_log(config: Config, line: str) -> Path:
    """向运行日志 runs.md 追加一行（时间戳 + 回顾会话数 + 蒸馏/终态条数由调用方拼好）。"""
    path = knowledge_dir(config) / RUN_LOG_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line.rstrip() + "\n")
    return path


def _dedupe_order(items: list[str], max_items: int = MAX_ITEMS) -> list[str]:
    """顺序保留去重（casefold；先出现者胜）；截断到 max_items。"""
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        key = x.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(x)
        if len(out) >= max_items:
            break
    return out


def distill(model, messages: list[BaseMessage], instructions: str | None = None) -> list[str]:
    """langmem schema 抽取蒸馏知识条目；任何失败返回 []（梦境不炸链）。

    注意：模型必须支持 ``bind_tools``（ChatOpenAI 原生支持；纯 fake 需自行实现）。
    langmem 无 tool call 时 ``responses`` 为空 → IndexError，属正常「无可沉淀」路径。
    """
    if model is None:
        return []
    try:
        from langmem import create_thread_extractor

        extractor = create_thread_extractor(
            model,
            schema=DreamItems,
            instructions=instructions or DEFAULT_DISTILL_INSTRUCTIONS,
        )
        out = extractor.invoke({"messages": list(messages)})
        raw = getattr(out, "items", None) or []
        return [s.strip() for s in raw if isinstance(s, str) and s.strip()]
    except Exception:  # noqa: BLE001 - 无 tool call / 模型异常 / 解析失败一律回落 []
        return []


def consolidate(
    model,
    new_items: list[str],
    existing_items: list[str],
    max_items: int = MAX_ITEMS,
) -> list[str]:
    """合并新蒸馏与现有知识库：优先模型 JSON 合并（去重/冲突以新为准/≤max），

    模型缺失或解析失败回落 ``_dedupe_order(新+旧)``（新在前）。
    """
    combined = list(new_items) + list(existing_items)
    if not combined:
        return []
    if model is None:
        return _dedupe_order(combined, max_items)
    prompt = (
        "你是 JARVIS 助手的知识库维护器。下面给出「新知识」与「现有知识」，"
        "请合并为一份去重且自洽的知识列表：冲突条目以新知识为准（改写或删除旧条目），"
        "保持每条一行简洁中文要点（≤80 字），总条数不超过 %d。"
        "只输出 JSON 字符串数组，不要 markdown 代码块、不要解释。\n"
        "新知识：\n%s\n现有知识：\n%s"
    ) % (max_items, json.dumps(list(new_items), ensure_ascii=False), json.dumps(list(existing_items), ensure_ascii=False))
    try:
        resp = model.invoke([SystemMessage(content=prompt)])
        text = getattr(resp, "content", None)
        if not isinstance(text, str):
            text = str(text)
        m = re.search(r"\[.*\]", text, re.S)
        if not m:
            raise ValueError("模型输出中无 JSON 数组")
        parsed = json.loads(m.group(0))
        items = [
            str(x).strip()
            for x in parsed
            if isinstance(x, (str, int, float)) and str(x).strip()
        ]
        if not items:
            raise ValueError("合并结果为空")
        return _dedupe_order(items, max_items)
    except Exception:  # noqa: BLE001 - 解析失败/模型异常回落顺序去重
        return _dedupe_order(combined, max_items)


def _participating_thread_ids(agent, limit: int) -> list[str]:
    """近 limit 个会话（排除 sched-*，新→旧取窗）中「≥1 用户消息且 ≥1 JARVIS 回复」的线程。

    返回按旧→新排序（蒸馏按时间自然顺序聚合消息）。
    """
    threads = commands.session_thread_ids(agent)[:limit]
    kept: list[str] = []
    for tid in reversed(threads):
        head = agent.get_state(commands.thread_config(tid))
        msgs = (head.values or {}).get("messages") or []
        if any(isinstance(m, HumanMessage) for m in msgs) and any(
            isinstance(m, AIMessage) for m in msgs
        ):
            kept.append(tid)
    return kept


def run_dream(agent, config: Config, limit: int = 20, tail: int = 100) -> str:
    """/dream 命令与定时任务统一入口。

    流程：近 limit 个参与会话 → 每会话尾 tail 条消息聚合 → langmem 蒸馏
    → 与现有知识库合并（JSON 优先，去重回落）→ 重写 knowledge.md + runs.md 日志。
    模型不可用 / 无会话可回顾 → 返回说明文案，不抛异常、不动文件。
    """
    model = getattr(agent, "_jarvis_model", None)
    existing = load_knowledge(config)
    if model is None:
        return f"梦境沉淀失败：模型不可用，本次未沉淀（知识库现有 {len(existing)} 条）"
    threads = _participating_thread_ids(agent, limit)
    if not threads:
        return f"梦境沉淀：暂无可回顾的近期会话（知识库现有 {len(existing)} 条）"

    msgs: list[BaseMessage] = []
    for tid in threads:
        head = agent.get_state(commands.thread_config(tid))
        all_msgs = (head.values or {}).get("messages") or []
        msgs.extend(all_msgs[-tail:])

    new_items = distill(model, msgs)
    final_items = consolidate(model, new_items, existing)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not new_items and final_items == existing:
        append_run_log(config, f"{stamp} 回顾 {len(threads)} 个会话，未蒸馏到新知识（知识库 {len(existing)} 条）")
        return f"梦境沉淀完成：回顾 {len(threads)} 个会话，未蒸馏到新的可复用知识（知识库现有 {len(existing)} 条）"

    write_knowledge(config, final_items)
    append_run_log(
        config,
        f"{stamp} 回顾 {len(threads)} 个会话，蒸馏 {len(new_items)} 条 → 知识库 {len(final_items)} 条",
    )
    return (
        f"梦境沉淀完成：回顾 {len(threads)} 个会话，蒸馏 {len(new_items)} 条 → "
        f"知识库 {len(final_items)} 条（memory/dream/knowledge.md）"
    )
