"""GUI #1/#2 — 未提交草稿随会话 + 图片跨会话泄漏回归（offscreen）。

#1: 切换会话时输入框/图片条里的未提交内容记为「该会话的草稿」；切回时恢复（无草稿=空）。
#2: 提交后无条件清空图片条（载荷随队携带图片）；queued_flush 重投时用户气泡补入（图不丢、不泄漏）。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui.events import UiBridge
from src.gui.main_window import MainWindow
from src.gui.runtime import GuiPresenter
from tests.gui_fakes import cleanup_home, new_home
from tests.test_gui_image_strip import _png_path, _tmp_dir
from tests.test_gui_presenter import _fake_runtime


def test_drafts_follow_session_switch(qapp):
    """#1：未提交输入随会话走——切走=存、切回=恢复、无草稿=清空。"""
    home = new_home()
    d = _tmp_dir()
    p1, p2 = _png_path(d, "a.png"), _png_path(d, "b.png")
    try:
        rt = _fake_runtime()
        pres = GuiPresenter(rt, UiBridge())
        win = MainWindow(pres, pres.bridge)

        win._switch_to("t1")
        win.input_bar.edit.setPlainText("half-typed")
        win.image_strip.add_image(p1)
        win.image_strip.add_image(p2)

        win._switch_to("t2")  # t2 无草稿 → 输入区与图片条空
        assert win.input_bar.edit.toPlainText() == ""
        assert win.image_strip.paths() == []

        win.input_bar.edit.setPlainText("draft of t2")
        win.image_strip.add_image(p1)

        win._switch_to("t1")  # 恢复 t1 的未提交草稿
        assert win.input_bar.edit.toPlainText() == "half-typed"
        assert win.image_strip.paths() == [p1, p2]

        win._switch_to("t2")  # t2 的草稿同样随会话保留
        assert win.input_bar.edit.toPlainText() == "draft of t2"
        assert win.image_strip.paths() == [p1]

        win._switch_to("t3")  # 无草稿 = 空
        assert win.input_bar.edit.toPlainText() == ""
        assert win.image_strip.paths() == []
    finally:
        cleanup_home(home)


def test_submit_clears_draft_and_image_strip(qapp, monkeypatch):
    """#2 回归：提交后无条件清空图片条（载荷带图）；残留在其它对话=泄漏。"""
    home = new_home()
    d = _tmp_dir()
    p1 = _png_path(d, "a.png")
    try:
        rt = _fake_runtime()
        pres = GuiPresenter(rt, UiBridge())
        win = MainWindow(pres, pres.bridge)

        caps: dict = {}

        def fake_start(tid, text, **kw):
            caps[tid] = {"text": text, **kw}
            return "queued"

        monkeypatch.setattr(pres, "start_turn", fake_start)

        win._switch_to("t1")
        win.image_strip.add_image(p1)
        win.input_bar.edit.setPlainText("看图")
        win.input_bar.btn_send.click()

        assert caps["t1"]["images"] == [p1]        # 提交载荷带图
        assert win.image_strip.paths() == []       # 附件条清空
        assert win.input_bar.edit.toPlainText() == ""

        win._switch_to("t2")
        assert win.image_strip.paths() == []       # 残留不泄漏到别的对话
        assert win.input_bar.edit.toPlainText() == ""

        win._switch_to("t1")
        assert win.image_strip.paths() == []
        assert win.input_bar.edit.toPlainText() == ""
    finally:
        cleanup_home(home)


def test_queued_flush_reinjects_text_and_images(qapp):
    """#2：排队载荷重投入门时，用户气泡此刻才进对话窗（随附图片不丢）。"""
    home = new_home()
    d = _tmp_dir()
    p1 = _png_path(d, "a.png")
    try:
        rt = _fake_runtime()
        pres = GuiPresenter(rt, UiBridge())
        win = MainWindow(pres, pres.bridge)

        win._switch_to("tA")
        pres.bridge.queued_flush.emit("tA", "重投文本", [p1])

        pane = win.panes["tA"]
        first = pane._vbox.itemAt(0).widget()
        second = pane._vbox.itemAt(1).widget()
        assert first is not None and "重投文本" in first.text()
        assert second is not None and second.widget() is not None  # 图片行
    finally:
        cleanup_home(home)
