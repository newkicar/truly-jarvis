import pathlib

p = pathlib.Path("src/streaming.py")
raw = p.read_bytes().decode("utf-8")


def enc(t):
    return t.replace("\n", "\r\n")


helper = '''def extract_reasoning(item: Any) -> str:
    """Extract thinking (reasoning) content from a single message in stream_events (tui-ux19).

    Three sources (all getattr/try defensive, not crashing across langchain 1.3/1.4 versions):
      (1) item.reasoning - langchain-core ChatModelStream's SyncTextProjection
        (after finalization str()/.get() = full text; incomplete is ""; repr starting with "<" is treated as un-specialized and rejected);
      (2) item.output.additional_kwargs["reasoning_content"] - common field for OpenAI-compatible gateways;
      (3) item.output.additional_kwargs["reasoning"]["summary"] - OpenAI reasoning
        summary (list of parts, dict takes text, joined by newlines).
    If (2)/(3) hits, return immediately (higher priority than (1)); if all empty, return "".
    """
    text = ""
    proj = getattr(item, "reasoning", None)
    if proj is not None:
        get = getattr(proj, "get", None)
        if callable(get):
            try:
                val = get()
            except Exception:
                val = None
            if isinstance(val, str) and val.strip():
                text = val.strip()
        if not text:
            cand = str(proj).strip()
            if cand and not cand.startswith("<"):
                text = cand
    try:
        out = item.output
    except Exception:
        out = None
    kw = getattr(out, "additional_kwargs", None)
    if isinstance(kw, dict):
        rc = kw.get("reasoning_content")
        if isinstance(rc, str) and rc.strip():
            return rc.strip()
        reasoning = kw.get("reasoning")
        if isinstance(reasoning, dict):
            parts: list[str] = []
            for part in reasoning.get("summary") or []:
                if isinstance(part, dict):
                    pt = part.get("text")
                    if isinstance(pt, str) and pt.strip():
                        parts.append(pt.strip())
                elif isinstance(part, str) and part.strip():
                    parts.append(part.strip())
            if parts:
                return "\\n".join(parts)
    return text


'''
helper = helper.replace("\n", "\r\n")
anchor_helper = enc("\n\ndef iter_text_deltas(chunks) -> list[str]:")
assert raw.count(anchor_helper) == 1, "anchor_helper not unique"
raw = raw.replace(anchor_helper, "\r\n" + helper + anchor_helper, 1)

old_emit = """            if draining:
                continue
            if segment and callbacks.get("on_message_end"):
                callbacks["on_message_end"]("".join(segment))
    return consumed
"""
new_emit = """            if draining:
                continue
            # tui-ux19: thinking content goes to screen first (transcription order thinking -> reply), independent of whether the body segment is empty
            if callbacks.get("on_reasoning_end"):
                reasoning = extract_reasoning(item)
                if reasoning:
                    callbacks["on_reasoning_end"](reasoning)
            if segment and callbacks.get("on_message_end"):
                callbacks["on_message_end"]("".join(segment))
    return consumed
"""
assert raw.count(enc(old_emit)) == 1, "anchor_emit not unique"
raw = raw.replace(enc(old_emit), enc(new_emit), 1)

p.write_bytes(raw.encode("utf-8"))
print("patched streaming.py OK")
