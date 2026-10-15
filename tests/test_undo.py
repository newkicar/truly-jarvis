"""commands.undo（消息层撤回）单测：撤 1 / 撤 3 / 撤超出（撤到空白）/ 无输入点。"""
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage

from src import commands


class _Snap:
    """LangGraph checkpoint 快照 mock（config/metadata/values/next）。"""

    def __init__(self, cid, source, messages):
        self.config = {"configurable": {"thread_id": "t1", "checkpoint_id": cid}}
        self.metadata = {"source": source}
        self.values = {"messages": messages}
        self.next = ()


class _UndoAgent:
    """fake agent：三轮用户输入（c0/c2/c4 为 input 点，c1/c3/c5 为 update）。"""

    def __init__(self):
        m1, a1 = HumanMessage("问题 1", id="m1"), AIMessage("回答 1", id="m2")
        m2, a2 = HumanMessage("问题 2", id="m3"), AIMessage("回答 2", id="m4")
        m3, a3 = HumanMessage("问题 3", id="m5"), AIMessage("回答 3", id="m6")
        self._snaps = [
            _Snap("c0", "input", [m1]),
            _Snap("c1", "update", [m1, a1]),
            _Snap("c2", "input", [m1, a1, m2]),
            _Snap("c3", "update", [m1, a1, m2, a2]),
            _Snap("c4", "input", [m1, a1, m2, a2, m3]),
            _Snap("c5", "update", [m1, a1, m2, a2, m3, a3]),
        ]
        self._head = self._snaps[-1]
        self.updates = []

    def get_state_history(self, config):
        """新→旧：head 打头，其余链路（排除 head 本身）。"""
        return [self._head] + [s for s in reversed(self._snaps) if s is not self._head]

    def get_state(self, config):
        return self._head

    def update_state(self, config, values=None, as_node=None):
        self.updates.append((config, values, as_node))
        if values is None:
            cid = config["configurable"].get("checkpoint_id")
            self._head = next(
                s for s in self._snaps
                if s.config["configurable"]["checkpoint_id"] == cid
            )
        else:
            msgs = list(self._head.values["messages"])
            doomed = {rm.id for rm in values["messages"] if isinstance(rm, RemoveMessage)}
            self._head = _Snap(
                self._head.config["configurable"]["checkpoint_id"],
                "update",
                [m for m in msgs if m.id not in doomed],
            )
        return config


class _EmptyAgent:
    def get_state_history(self, config):
        return []

    def get_state(self, config):
        raise AssertionError("空会话不应调用 get_state")

    def update_state(self, config, values=None, as_node=None):
        raise AssertionError("空会话不应 update_state")


def test_undo_one_rolls_back_to_parent_checkpoint():
    agent = _UndoAgent()
    text = commands.undo(agent, "t1", 1)
    assert "已撤回 1 条消息" in text
    assert len(agent.updates) == 1
    cfg, values, as_node = agent.updates[0]
    assert values is None and as_node is None
    assert cfg["configurable"]["checkpoint_id"] == "c3"  # 末个输入点 c4 的父 checkpoint


def test_undo_three_reaches_blank():
    agent = _UndoAgent()
    text = commands.undo(agent, "t1", 3)
    assert "已撤回 3 条消息" in text
    assert len(agent.updates) == 3
    cfg, values, as_node = agent.updates[-1]
    assert as_node == "model"  # 末步为外科式删除（线程起点无父 checkpoint）
    assert {rm.id for rm in values["messages"]} == {"m1", "m2"}
    assert agent.get_state(commands.thread_config("t1")).values["messages"] == []
    # 撤回后 /history 渲染与 /history 边界一致：会话已空白
    assert commands.render_session_text(agent, "t1") == ""


def test_undo_exceeds_clamps_with_notice():
    agent = _UndoAgent()
    text = commands.undo(agent, "t1", 99)
    assert "已撤回 3 条消息" in text
    assert "已超出" in text
    assert agent.get_state(commands.thread_config("t1")).values["messages"] == []


def test_undo_no_input_points():
    assert "没有可撤回的消息" in commands.undo(_EmptyAgent(), "t1", 1)