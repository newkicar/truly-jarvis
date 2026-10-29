"""工单 12：GUI 自检页（/doctor 的 GUI 对应物）——一屏看全运行环境与降级状态。

纯函数报告构建（无网络、无落盘，probe 结果由调用方注入，fake 配置驱动可测）
+ Qt 对话框渲染。区块：LLM 端点/凭据 · 输入通道 · 可选依赖（RAG/MCP/Ollama）·
全局记忆路径 · 检查点 db · 定时任务。降级指引：缺 chromadb → 装 wheel；
Ollama 不可达 → 起 Ollama。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.config import Config
from src.gui.llm_config import KEY_REF
from src.project_paths import user_home

STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"


@dataclass(frozen=True)
class DoctorRow:
    block: str
    item: str
    status: str  # ok | warn | fail
    detail: str
    hint: str = ""


def chromadb_available() -> bool:
    """可选依赖探测（不执行 chromadb，find_spec 零副作用）。"""
    import importlib.util

    return importlib.util.find_spec("chromadb") is not None


def build_doctor_report(
    config: Config,
    *,
    llm=None,
    key_store=None,
    ollama_reachable: bool | None = None,
    mcp_tool_count: int | None = None,
    scheduler_running: bool = False,
) -> list[DoctorRow]:
    """按区块生成自检行；同一输入恒等输出（offscreen 测试零网络）。"""
    rows: list[DoctorRow] = []

    # ---- LLM 端点 / 凭据
    if llm is not None:
        url_ok = bool(llm.base_url.strip()) and bool(llm.model_id.strip())
        if url_ok and key_store is not None and key_store.get(KEY_REF):
            rows.append(
                DoctorRow(
                    "LLM", "端点/凭据", STATUS_OK,
                    f"{llm.base_url} · {llm.model_id}",
                    "Key 存凭据存储（key_ref 有效）",
                )
            )
        elif url_ok:
            rows.append(
                DoctorRow(
                    "LLM", "端点/凭据", STATUS_WARN,
                    f"{llm.base_url} · {llm.model_id}",
                    "key_ref 悬空或凭据未存 → 回向导第 3 步重填 Key",
                )
            )
        else:
            rows.append(
                DoctorRow(
                    "LLM", "端点/凭据", STATUS_FAIL,
                    "端点或模型 ID 未填全", "回向导补齐 base_url / model_id"
                )
            )
    elif config.api_key:
        rows.append(
            DoctorRow(
                "LLM", "端点/凭据", STATUS_OK,
                f"项目 .env → {config.base_url} · {config.model_id}",
                "使用项目 .env（开发机路径）",
            )
        )
    else:
        rows.append(
            DoctorRow(
                "LLM", "端点/凭据", STATUS_FAIL, "无 LLM 配置", "打开首启向导或放置 .env 后重启"
            )
        )

    # ---- 输入通道（GUI = 原生 Windows 输入，无 ConPTY 事故面）
    rows.append(
        DoctorRow(
            "输入通道", "键盘/IME/粘贴", STATUS_OK,
            "Windows 原生输入通道（无 ConPTY）",
            "粘贴 = Ctrl+V（OS 剪贴板，文本/图片）；Shift+Enter 换行",
        )
    )

    # ---- 可选依赖
    chroma = chromadb_available()
    rows.append(
        DoctorRow(
            "可选依赖", "RAG 语义索引（chromadb）",
            STATUS_OK if chroma else STATUS_WARN,
            "chromadb 已安装，增量向量索引可用"
            if chroma
            else "chromadb 未安装 → 知识库检索回落 grep/wiki 导航",
            "" if chroma else "pip install chromadb 装 wheel 启用语义检索",
        )
    )
    if ollama_reachable is None:
        rows.append(
            DoctorRow(
                "可选依赖", "Ollama embedding", STATUS_WARN,
                f"未探测（{config.rag_ollama_base_url} · {config.rag_embed_model}）",
                "启动后自检页可显示可达性",
            )
        )
    else:
        rows.append(
            DoctorRow(
                "可选依赖", "Ollama embedding",
                STATUS_OK if ollama_reachable else STATUS_WARN,
                "Ollama 可达，语义 embedding 可用"
                if ollama_reachable
                else f"Ollama 不可达（{config.rag_ollama_base_url}）→ 语义检索失效，回落 grep/wiki",
                "" if ollama_reachable else "启动 Ollama（ollama serve）或换 embed 端点",
            )
        )
    if mcp_tool_count is None:
        servers = (config.mcps or {}).get("servers", {})
        rows.append(
            DoctorRow(
                "可选依赖", "MCP", STATUS_OK,
                f"配置 {len(servers)} 个 server（未启用 --mcp 或未加载）"
                if servers
                else "未配置 mcps.servers（基础客户端零 MCP）",
            )
        )
    else:
        rows.append(
            DoctorRow(
                "可选依赖", "MCP", STATUS_OK,
                f"已加载 {mcp_tool_count} 个 MCP 工具（server 前缀）"
                if mcp_tool_count
                else "MCP 0 工具（未启用或连接失败=警告跳过，不影响启动）",
            )
        )

    # ---- 全局记忆路径（工单 11 对齐：~/.jarvis，JARVIS_HOME 可改）
    home = user_home()
    rows.append(
        DoctorRow("记忆", "全局目录", STATUS_OK, str(home),
                  "记忆/技能/用户全局配置与安装目录分离")
    )
    mem = Path(config.memory_dir)
    globalized = False
    try:
        globalized = (Path(home) in mem.parents) or (mem == Path(home) / "memory")
    except Exception:
        globalized = False
    rows.append(
        DoctorRow(
            "记忆", "信息记忆目录", STATUS_OK, str(mem),
            "已全局化（跨项目复用）" if globalized else "项目级 memory/（jarvis.json memory_dir）",
        )
    )

    # ---- 检查点 db
    db = Path(config.checkpoint_db)
    db_dir_ok = db.parent.exists()
    shm = db.parent / (db.name + "-shm")
    rows.append(
        DoctorRow(
            "检查点", "checkpoints.sqlite",
            STATUS_OK if db_dir_ok else STATUS_WARN,
            f"{db}（{'目录存在' if db_dir_ok else '目录缺失，启动时自动创建'}）",
            "WAL 活跃（另一进程可能持有连接）" if shm.exists() else "",
        )
    )

    # ---- 定时任务
    rows.append(
        DoctorRow(
            "定时任务", "scheduler", STATUS_OK,
            "运行中（单 scheduler 门控，不双开）"
            if scheduler_running
            else "未启动（GUI 默认关；--scheduled 开启）",
        )
    )
    return rows


# ---------------------------------------------------------------- Qt 渲染
_STATUS_COLOR = {STATUS_OK: "#2ecc71", STATUS_WARN: "#f39c12", STATUS_FAIL: "#e74c3c"}


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def doctor_report_markup(rows: list[DoctorRow]) -> str:
    """报告 → QLabel RichText（字段逐个转义，结构 HTML 由本函数拼装）。"""
    out: list[str] = []
    last_block: str | None = None
    for r in rows:
        if r.block != last_block:
            out.append(f'<div style="margin-top:8px"><b>{_esc(r.block)}</b></div>')
            last_block = r.block
        color = _STATUS_COLOR.get(r.status, "#999999")
        hint = f'<div style="color:#8892a0;margin-left:16px">↳ {_esc(r.hint)}</div>' if r.hint else ""
        out.append(
            f'<div style="margin-left:8px"><span style="{color};font-weight:bold">●</span> '
            f"<b>{_esc(r.item)}</b> — {_esc(r.detail)}{hint}</div>"
        )
    return "\n".join(out)


def make_doctor_dialog(rows: list[DoctorRow], parent=None):
    """自检对话框（延迟导入 PySide6，报告构建可无 Qt 环境测试）。"""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QScrollArea, QVBoxLayout

    dlg = QDialog(parent)
    dlg.setWindowTitle("自检（Doctor）")
    dlg.resize(720, 460)
    lay = QVBoxLayout(dlg)
    area = QScrollArea()
    area.setWidgetResizable(True)
    label = QLabel(doctor_report_markup(rows))
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setWordWrap(True)
    label.setObjectName("report-label")
    area.setWidget(label)
    lay.addWidget(area, 1)
    btn = QPushButton("关闭")
    btn.clicked.connect(dlg.accept)
    lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignRight)
    dlg.doctor_rows = rows  # 测试断言
    return dlg
