"""presenter 装配：GuiPresenter + ask_action 安装（工单 04 审批卡片接线点）。

01 兜底：不装卡片 → presenter._default_ask（拒绝 + 提示）。
04：wire_presenter(..., card_factory=...) 装内联审批卡（create_card 信号驱动，
worker 侧 threading.Event 阻塞等决策，resume 契约 {"decisions":[...]} 零内核改）。
"""
from __future__ import annotations

from typing import Any, Callable


def wire_presenter(
    runtime,
    bridge,
    *,
    app=None,
    card_factory: Callable | None = None,
) -> "Any":
    from src.gui.runtime import GuiPresenter

    presenter = GuiPresenter(runtime, bridge)
    if card_factory is not None:
        presenter.set_ask_action(card_factory)
    return presenter
