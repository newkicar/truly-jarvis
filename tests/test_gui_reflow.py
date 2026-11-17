"""gui-ux21 — 宽度自适应换行（wrap_every + ReflowLabel + 卡片重排）offscreen 测试。

修两处缺陷：
- 日志/工具区此前按固定 48/80 字硬切（窄窗大量浪费、宽窗提前折行，视觉不自然）
  → wrap_every 像素宽换算字数 + 80ms 防抖重排（对标 TUI tui-ux20）；
- _detail_html 的 <>br 是 afa23e7 误写（应为 <br>；旧 regex 测试无该断言故漏网）。

纪律：全部 offscreen（QT_QPA_PLATFORM=offscreen）；禁用 tmp_path / tempfile。
"""
import math
import os
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QLabel  # noqa: E402

from src.gui import cards, md_render, pane, theme  # noqa: E402


# ---- 1. wrap_every 边界 -----------------------------------------------------------
def test_wrap_every_boundaries(qapp):
    theme.apply_theme(qapp, "dark")
    font = md_render.mono_font()
    assert md_render.wrap_every(font, 0) == 160            # offscreen/未布局 → cap
    assert md_render.wrap_every(font, -10) == 160
    assert md_render.wrap_every(font, 5000) == 160         # 上限截断
    assert md_render.wrap_every(font, 4) == 8              # 下限截断 min_chars
    assert 8 <= md_render.wrap_every(font, 300) <= 160     # 合法宽度 ∈ [8, 160]
    # 单调性：越宽字数越多（或相等）
    assert md_render.wrap_every(font, 400) >= md_render.wrap_every(font, 100)


# ---- 2. md_to_qt_html 参数化 ------------------------------------------------------
def test_md_to_qt_html_every_parameterized(qapp):
    theme.apply_theme(qapp, "dark")
    s = "c" * 300
    tight = md_render.md_to_qt_html(s, 10)
    loose = md_render.md_to_qt_html(s, 80)
    assert tight.count("<br>") > loose.count("<br>")


# ---- 3. _detail_html 回归：<>br 修复 + every 参数化 ------------------------------
def test_detail_html_br_fixed(qapp):
    theme.apply_theme(qapp, "dark")
    html = pane._detail_html("A" * 300, "B" * 300, False, 0)
    assert "<br>" in html
    assert "<>br" not in html
    # every 越小断行越多
    assert pane._detail_html("A" * 300, "B" * 300, False, 0, every=8).count("<br>") > html.count("<br>")


# ---- 4. ReflowLabel 独立：resize 重排 + 防抖 -------------------------------------
def test_reflow_label_rewraps_on_resize(qapp, qtbot):
    theme.apply_theme(qapp, "dark")
    label = pane.ReflowLabel(lambda e: md_render.soft_break("X" * 400, e), 48)
    qtbot.addWidget(label)
    label.show()
    label.render()
    base = math.ceil(400 / 48)  # 9 行
    assert len(label.text().split("\n")) == base
    # 窄窗 → 断行更多（只断方向）
    label.resize(120, 50)
    label.rewrap_now()
    assert len(label.text().split("\n")) > base
    # 超宽窗 → 断行更少（cap=160）
    label.resize(3000, 50)
    label.rewrap_now()
    assert len(label.text().split("\n")) < base
    # 防抖路径：resize → 80ms 定时器 → _every 自动校正
    w = 500
    label.resize(w, 50)
    qapp.processEvents()
    qtbot.wait(120)
    assert label._every == md_render.wrap_every(label.font(), w)


# ---- 5. ToolLineWidget 摘要/详情重排 ---------------------------------------------
def test_tool_line_widget_rewrap(qapp, qtbot):
    theme.apply_theme(qapp, "dark")
    w = pane.ToolLineWidget("execute", "A" * 300, False, "B" * 300)
    qtbot.addWidget(w)
    assert "A" in w._summary.text()
    w.show()
    w.resize(500, 200)
    qapp.processEvents()
    w._summary.rewrap_now()
    w.toggle()
    assert "B" in w._detail.text()
    assert "<br>" in w._detail.text()


# ---- 6. ChatPane.append_user 重排后内容守恒 --------------------------------------
def test_chat_pane_append_user_content_preserved(qapp, qtbot):
    theme.apply_theme(qapp, "dark")
    p = pane.ChatPane("t1")
    qtbot.addWidget(p)
    p.append_user("U" * 600)
    p.show()
    p.resize(500, 300)
    qapp.processEvents()
    qtbot.wait(120)
    labels = [x for x in p.findChildren(QLabel) if x.objectName() == "bub-user"]
    assert len(labels) == 1
    # 换行只会插入 \n，去空白后内容必须原样守恒
    assert "".join(labels[0].text().split()) == "[你]" + "U" * 600


# ---- 7. ApprovalCard 重排 ---------------------------------------------------------
def test_approval_card_rewrap(qapp, qtbot):
    theme.apply_theme(qapp, "dark")
    path = r"C:\long" * 20
    inv = types.SimpleNamespace(name="execute", path=path, args={"command": "git status"})
    card = cards.ApprovalCard(inv, "prev" * 50, lambda r: None, lambda: None)
    qtbot.addWidget(card)
    card.show()
    card.resize(400, 600)
    qapp.processEvents()
    card._rewrap()  # 不崩
    assert card._path_label.text().replace("\n", "") == "目标: " + path
    assert card._preview_edit.toPlainText().replace("\n", "") == "prev" * 50
    # 未 show 卡片：width()=0 早退，no-op 不崩
    card2 = cards.ApprovalCard(inv, "prev" * 50, lambda r: None, lambda: None)
    qtbot.addWidget(card2)
    card2._rewrap()


# ---- 8. ThinkingBox 正文重排 ------------------------------------------------------
def test_thinking_box_body_rewraps(qapp, qtbot):
    theme.apply_theme(qapp, "dark")
    box = pane.ThinkingBox()
    qtbot.addWidget(box)
    box.add_delta("Y" * 400)
    assert "Y" in box._body.text()
    box.show()
    box.resize(120, 200)
    box._body.rewrap_now()
    assert len(box._body.text().split("\n")) > 1