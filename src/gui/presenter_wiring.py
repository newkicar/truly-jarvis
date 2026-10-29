"""presenter 装配：GuiPresenter + ask_action 安装（工单 04 起默认内联审批卡片）。"""
from __future__ import annotations

from typing import Any, Callable


def wire_presenter(runtime, bridge, *, app=None, card_factory: Callable | None = None) -> "Any":
    """card_factory=None → 默认内联审批卡片（make_card_ask）；显式传入可替换（测试用自动放行等）。"""
    from src.gui.cards import make_card_ask
    from src.gui.runtime import GuiPresenter

    presenter = GuiPresenter(runtime, bridge)
    presenter.set_ask_action(card_factory if card_factory is not None else make_card_ask(runtime, bridge))
    return presenter
