"""tool_call 解析层测试（C2: ToolCallView + arg_value/command 自由函数）。"""
from src.tool_call import ToolCallView, arg_value, command, tool_call_view


def test_arg_value_picks_first_existing():
    assert arg_value({"file_path": "a.txt", "path": "b.txt"}, "file_path", "path") == "a.txt"
    assert arg_value({"path": "b.txt"}, "file_path", "path") == "b.txt"
    assert arg_value({}, "file_path", "path") == ""
    assert arg_value({"x": 1}, "file_path") == ""


def test_arg_value_coerces_to_string():
    assert arg_value({"x": 42}, "x") == "42"
    assert arg_value({"x": None}, "x") == ""


def test_command_string():
    assert command({"command": "ls -la"}) == "ls -la"
    assert command({"command": ""}) == ""
    assert command({}) == ""


def test_command_list():
    assert command({"command": ["git", "push", "origin"]}) == "git push origin"
    assert command({"cmd": ["python", "-c"]}) == "python -c"


def test_command_falls_back_to_cmd():
    assert command({"cmd": "echo hi"}) == "echo hi"


def test_tool_call_view_from_request():
    class _Req:
        tool_call = {"name": "write_file", "args": {"file_path": "x.md"}, "id": "tc1"}

    view = tool_call_view(_Req())
    assert view.name == "write_file"
    assert view.id == "tc1"
    assert view.arg_value("file_path") == "x.md"
    assert view.command() == ""


def test_tool_call_view_handles_no_tool_call():
    class _Empty:
        pass

    view = tool_call_view(_Empty())
    assert view.name == ""
    assert view.id == ""
    assert view.args == {}


def test_tool_call_view_handles_dict_tool_call():
    view = tool_call_view(type("_Req", (), {"tool_call": {"name": "ls", "args": {"path": "/x"}, "id": "t2"}})())
    assert view.name == "ls"
    assert view.arg_value("path") == "/x"


def test_tool_call_view_handles_non_dict_args():
    view = tool_call_view(type("_Req", (), {"tool_call": {"name": "x", "args": "bad", "id": "t"}})())
    assert view.args == {}


def test_tool_call_view_methods_delegate():
    v = ToolCallView(name="execute", id="t", args={"command": "echo 1"})
    assert v.command() == "echo 1"
    assert v.arg_value("command") == "echo 1"
