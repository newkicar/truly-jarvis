"""审批卡片左右对比 diff（WP2）单测：aligned_diff 纯函数 + SideBySideDiff 部件 + 卡片集成 + _file_diff。

纪律：offscreen Qt；目录用 os.makedirs 自建（.scratch/，勿用 tmp_path/tempfile）。
"""
import os
import types
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QPlainTextEdit

from src.gui import cards, diff_view
from src.commands import ToolInvocation


def _inv(name, args=None, path=None):
    return ToolInvocation(name=name, args=args or {"command": "echo hi"}, path=path)


# ---------------------------------------------------------------- aligned_diff 纯函数
def test_aligned_diff_identical_rows_1to1():
    rows = diff_view.aligned_diff("a\nb\n", "a\nb\n")
    assert [r[0] for r in rows] == [" ", " ", " "]
    assert all(l == r for _, l, r in rows)
    assert rows[0][1] == "a" and rows[-1][1] == ""  # 尾随空行


def test_aligned_diff_delete_row_left_red_marker():
    rows = diff_view.aligned_diff("a\nb\nc", "a\nc")
    assert rows == [(" ", "a", "a"), ("-", "b", ""), (" ", "c", "c")]


def test_aligned_diff_insert_row_right_marker():
    rows = diff_view.aligned_diff("a\nc", "a\nb\nc")
    assert rows == [(" ", "a", "a"), ("+", "", "b"), (" ", "c", "c")]


def test_aligned_diff_replace_zipped_modify_and_added():
    rows = diff_view.aligned_diff("\n".join(["a", "x", "z"]), "\n".join(["a", "x1", "x2", "z"]))
    assert rows == [
        (" ", "a", "a"),
        ("~", "x", "x1"),
        ("+", "", "x2"),
        (" ", "z", "z"),
    ]


def test_aligned_diff_truncates_to_max_lines_with_ellipsis_tail():
    old = "\n".join(f"o{i}" for i in range(400))
    new = "\n".join(f"n{i}" for i in range(400))
    rows = diff_view.aligned_diff(old, new, max_lines=50)
    assert len(rows) == 50
    assert rows[-1][0] == "\u2026"


def test_aligned_diff_none_values():
    assert diff_view.aligned_diff(None, None) == [(" ", "", "")]


# ---------------------------------------------------------------- SideBySideDiff 部件
def test_side_by_side_widget_two_panes_and_text(qtbot):
    w = diff_view.SideBySideDiff("a\nb", "a\nc")
    qtbot.addWidget(w)
    panes = w.findChildren(QPlainTextEdit, "diff-pane")
    assert len(panes) == 2
    left, right = sorted(panes, key=lambda x: x.toPlainText())
    assert left.toPlainText().strip() == "a\nb"
    assert right.toPlainText().strip() == "a\nc"


def test_side_by_side_scroll_sync(qtbot):
    old = "\n".join(f"o{i}" for i in range(500))
    new = "\n".join(f"n{i}" for i in range(500))
    w = diff_view.SideBySideDiff(old, new, max_lines=500)
    qtbot.addWidget(w)
    w.show()
    w.resize(600, 300)
    lb = w._left.verticalScrollBar()
    rb = w._right.verticalScrollBar()
    lb.setValue(100)
    assert rb.value() == lb.value()


# ---------------------------------------------------------------- 卡片集成
def test_approval_card_with_diff_suppresses_text_preview(qtbot):
    inv = _inv("write_file", {"file_path": "/workspace/a.txt"}, "/workspace/a.txt")
    card = cards.ApprovalCard(inv, "text-preview", lambda r: None, lambda: None, diff=("x\ny", "x\nz"))
    qtbot.addWidget(card)
    assert len(card.findChildren(QPlainTextEdit, "diff-pane")) == 2
    assert len(card.findChildren(QPlainTextEdit, "card-preview")) == 0


def test_approval_card_without_diff_falls_back_to_text_preview(qtbot):
    inv = _inv("execute")
    card = cards.ApprovalCard(inv, "text-preview", lambda r: None, lambda: None)
    qtbot.addWidget(card)
    assert len(card.findChildren(QPlainTextEdit, "diff-pane")) == 0
    assert len(card.findChildren(QPlainTextEdit, "card-preview")) == 1


def test_card_widget_from_payload_roundtrip(qtbot):
    payload = (_inv("write_file"), "preview", "cid", lambda r: None, lambda: None, ("a", "b"))
    card = cards.card_widget_from_payload(payload)
    assert len(card.findChildren(QPlainTextEdit, "diff-pane")) == 2
    # 旧形状 5 元组 payload 也兼容（diff=None 回落文本预览）
    card2 = cards.card_widget_from_payload(payload[:5])
    assert len(card2.findChildren(QPlainTextEdit, "diff-pane")) == 0
    qtbot.addWidget(card)
    qtbot.addWidget(card2)


# ---------------------------------------------------------------- _file_diff
def test_file_diff_edit_returns_before_after():
    root = Path(".scratch") / "diff_probe"
    root.mkdir(parents=True, exist_ok=True)
    probe = root / "probe.txt"
    probe.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    runtime = types.SimpleNamespace(
        config=types.SimpleNamespace(vault_path=Path(root), project_root=Path(root))
    )
    inv = _inv(
        "edit_file",
        {"file_path": "/workspace/probe.txt", "old_string": "beta", "new_string": "BETA"},
        "/workspace/probe.txt",
    )
    assert cards._file_diff(inv, runtime) == ("alpha\nbeta\ngamma\n", "alpha\nBETA\ngamma\n")


def test_file_diff_write_new_file_empty_before():
    root = Path(".scratch") / "diff_probe"
    root.mkdir(parents=True, exist_ok=True)
    runtime = types.SimpleNamespace(
        config=types.SimpleNamespace(vault_path=Path(root), project_root=Path(root))
    )
    inv = _inv(
        "write_file",
        {"file_path": "/workspace/new.txt", "content": "hi"},
        "/workspace/new.txt",
    )
    assert cards._file_diff(inv, runtime) == ("", "hi")


def test_file_diff_execute_returns_none():
    assert cards._file_diff(_inv("execute"), runtime=None) is None


def test_file_diff_bad_runtime_returns_none():
    root = Path(".scratch") / "diff_probe"
    root.mkdir(parents=True, exist_ok=True)
    inv = _inv("delete", {}, "/workspace/probe.txt")
    assert cards._file_diff(inv, None) is None
