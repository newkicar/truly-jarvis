from pathlib import Path
p = Path('src/tui_turn.py')
s = p.read_text(encoding='utf-8')

# 1. import 扩展
old_import = 'from src.tui_format import AiStreamThrottler, format_tool_call'
new_import = ('from src.tui_format import '
              'AiStreamThrottler, format_tool_call, reasoning_block_markup, '
              'tool_detail_block, tool_detail_worth_expanding')
assert s.count(old_import) == 1
s = s.replace(old_import, new_import, 1)

# 2. on_tool_call 重写 + 新增 on_reasoning_end
old_t = '''    def on_tool_call(self, name: str, args: str, err: bool, output: str | None, depth: int) -> None:
        self.write_line(format_tool_call(name, args, error=err, output=output, indent=depth))
        if name == "write_todos" and not self.cancelled():
            self.app.call_from_thread(self.app._refresh_todos_panel)
'''
new_t = '''    def on_tool_call(self, name: str, args: str, err: bool, output: str | None, depth: int) -> None:
        # tui-ux19: 值得展开（失败/有输出/长参数）→ 注册可点击工具条目（折叠态上屏 + 展开态待命）；
        # 否则普通单行调用（write_line 已含取消守卫）。
        detail = tool_detail_worth_expanding(name, args, error=err, output=output)
        collapsed = format_tool_call(name, args, error=err, output=output, indent=depth, detail=detail)
        if detail and not self.cancelled():
            expanded = tool_detail_block(name, args, error=err, output=output, indent=depth)
            self.app.call_from_thread(self.log.write_tool_entry, collapsed, expanded)
        else:
            self.write_line(collapsed)
        if name == "write_todos" and not self.cancelled():
            self.app.call_from_thread(self.app._refresh_todos_panel)

    def on_reasoning_end(self, text: str) -> None:
        # tui-ux19: 思考内容上屏（💭 淡色斜体块，对标正文区分；正文之后渲染）
        if self.cancelled() or not (text or "").strip():
            return
        self.write_line(reasoning_block_markup(text.strip()))
'''
assert s.count(old_t) == 1
s = s.replace(old_t, new_t, 1)

# 3. callbacks 增加 on_reasoning_end
old_c = '''            "on_message_delta": self.on_message_delta,
            "on_message_end": self.on_message_end,'''
new_c = '''            "on_message_delta": self.on_message_delta,
            "on_message_end": self.on_message_end,
            "on_reasoning_end": self.on_reasoning_end,'''
assert s.count(old_c) == 1
s = s.replace(old_c, new_c, 1)

p.write_text(s, encoding='utf-8')
print('tui_turn ok')
