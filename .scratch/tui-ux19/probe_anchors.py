import io
def show(path, pats):
    lines = io.open(path, encoding="utf-8").read().splitlines()
    print("====", path, len(lines), "lines")
    for p in pats:
        hits=[i+1 for i,l in enumerate(lines) if p in l]
        print("  %r: %s" % (p, hits[:14]))
show("src/commands.py", ["def thread_config","def content_to_text","def thread_history_text","def iter_reasoning_text","def extract_reasoning","def thread_history_full"])
show("src/streaming.py", ["def iter_text_deltas","def consume_stream_events","on_reasoning_delta","on_message_delta","on_message_end"])
show("src/tui_turn.py", ["class TurnPresenter","def write_line","def on_tool_call","def on_cancelled","def on_turn_incomplete","def callbacks","_reasoning_buf"])
show("src/tui_format.py", ["def truncate_lines","def format_tool_call","class AiStreamThrottler","def format_tool_detail","def format_reasoning_block","def reasoning_stream_renderable","def tool_detail_worth_expanding"])
