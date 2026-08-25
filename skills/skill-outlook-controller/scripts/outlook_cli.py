#!/usr/bin/env python
"""Outlook 命令行接口 - 供 Agent 通过 execute 工具调用

用法:
    python outlook_cli.py <action> <json_args>

示例:
    python outlook_cli.py read_inbox '{"if_unread": true}'
    python outlook_cli.py send_email '{"to": ["user@example.com"], "subject": "测试", "body": "内容"}'
"""

import json
import os
import sys
import tempfile
import io
import win32com

# 【核心修复】强制设置 stdout/stderr 为 UTF-8 编码，解决 Windows GBK 编码问题
# 这能避免 UnicodeEncodeError 和中文乱码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 【最强保险】显式重定向
cache_dir = os.path.join(tempfile.gettempdir(), "gen_py_thomas")
os.makedirs(cache_dir, exist_ok=True)
win32com.__gen_path__ = cache_dir  # 核心点：强制覆盖
os.environ["PYTHONCOMCACHE"] = cache_dir  # 辅助保险

# 之后才进行后续导入
from outlook_service import OutlookService


def read_inbox_emails(args):
    """读取收件箱邮件"""
    service = OutlookService()
    try:
        emails = service.read_inbox_emails(
            from_email=args.get("from_email"),
            to=args.get("to", []),
            cc=args.get("cc", []),
            bcc=args.get("bcc", []),
            subject=args.get("subject"),
            body=args.get("body"),
            attachment=args.get("attachment"),
            start_time=args.get("start_time"),
            end_time=args.get("end_time"),
            if_unread=args.get("if_unread", False),
        )
        return {"success": True, "count": len(emails), "emails": emails}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        service.close()


def read_sent_emails(args):
    """读取已发送邮件"""
    service = OutlookService()
    try:
        emails = service.read_sent_emails(
            to=args.get("to", []),
            cc=args.get("cc", []),
            bcc=args.get("bcc", []),
            subject=args.get("subject"),
            body=args.get("body"),
            attachment=args.get("attachment"),
            start_time=args.get("start_time"),
            end_time=args.get("end_time"),
        )
        return {"success": True, "count": len(emails), "emails": emails}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        service.close()


def send_email(args):
    """发送邮件"""
    if "to" not in args or "subject" not in args:
        return {"success": False, "error": "缺少必需参数: to, subject"}

    service = OutlookService()
    try:
        # 【修复】兼容 attachments 和 attachment 两种字段名
        attachment = args.get("attachments") or args.get("attachment")
        
        service.send_email(
            to=args["to"],
            cc=args.get("cc", []),
            bcc=args.get("bcc", []),
            subject=args["subject"],
            body=args.get("body", ""),
            attachment=attachment,
        )
        return {"success": True, "message": "邮件发送成功"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        service.close()


def reply_email(args):
    """回复邮件"""
    if "entry_id" not in args:
        return {"success": False, "error": "缺少必需参数: entry_id（请先读取邮件获取）"}
    if "body" not in args:
        return {"success": False, "error": "缺少必需参数: body（回复内容）"}

    service = OutlookService()
    try:
        # 【修复】兼容 attachments 和 attachment 两种字段名
        attachment = args.get("attachments") or args.get("attachment")
        
        service.reply_email(
            entry_id=args["entry_id"],
            body=args["body"],
            reply_all=args.get("reply_all", False),
            cc=args.get("cc", []),
            bcc=args.get("bcc", []),
            attachment=attachment,
        )
        return {"success": True, "message": "邮件回复成功"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        service.close()


def read_meetings(args):
    """读取会议"""
    service = OutlookService()
    try:
        meetings = service.read_meetings(
            from_email=args.get("from_email"),
            to=args.get("to", []),
            participants=args.get("participants", []),
            meeting_room=args.get("meeting_room"),
            subject=args.get("subject"),
            body=args.get("body"),
            attachment=args.get("attachment"),
            start_time=args.get("start_time"),
            end_time=args.get("end_time"),
        )
        return {"success": True, "count": len(meetings), "meetings": meetings}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        service.close()


def send_meeting(args):
    """发送会议邀请"""
    if (
        "participants" not in args
        or "subject" not in args
        or "start_time" not in args
        or "end_time" not in args
    ):
        return {
            "success": False,
            "error": "缺少必需参数: participants, subject, start_time, end_time",
        }

    service = OutlookService()
    try:
        # 【修复】兼容 attachments 和 attachment 两种字段名
        attachment = args.get("attachments") or args.get("attachment")
        
        service.send_meeting(
            participants=args["participants"],
            meeting_room=args.get("meeting_room"),
            subject=args["subject"],
            body=args.get("body", ""),
            attachment=attachment,
            start_time=args["start_time"],
            end_time=args["end_time"],
        )
        return {"success": True, "message": "会议邀请发送成功"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        service.close()


def main():
    """主入口"""
    if len(sys.argv) < 3:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": "用法: python outlook_cli.py <action> <json_args>",
                    "available_actions": [
                        "read_inbox",
                        "read_sent",
                        "send_email",
                        "reply_email",
                        "read_meetings",
                        "send_meeting",
                    ],
                    "hint": "注意：JSON 参数必须用单引号包裹，例如: python outlook_cli.py read_inbox '{\"if_unread\": true}'",
                },
                ensure_ascii=False,
            )
        )
        sys.exit(1)

    action = sys.argv[1]
    param_input = sys.argv[2]  # 既可以是 JSON 字符串，也可以是文件路径

    # 【方案 1】优先检查是否为 JSON 文件路径（最稳健，完全避开 Shell 转义问题）
    if param_input.endswith(".json") and os.path.exists(param_input):
        print(f"DEBUG: Loading JSON from file: {param_input}", file=sys.stderr)
        try:
            with open(param_input, "r", encoding="utf-8") as f:
                args = json.load(f)
            print("DEBUG: Successfully loaded JSON from file", file=sys.stderr)
        except Exception as e:
            error_msg = {
                "success": False,
                "error": f"读取 JSON 文件失败: {str(e)}",
                "file": param_input,
            }
            print(json.dumps(error_msg, ensure_ascii=False))
            sys.exit(1)
    else:
        # 【方案 2】暴力合并所有参数，处理 Shell 拆分问题
        # 无论 Shell 怎么拆分参数，全部合并后再提取 JSON
        all_params = sys.argv[2:]
        print(f"DEBUG: received {len(all_params)} args", file=sys.stderr)
        print(f"DEBUG: raw args = {all_params}", file=sys.stderr)

        # 暴力合并所有参数（用空格连接）
        full_cmd_args = " ".join(all_params)
        print(f"DEBUG: merged args = {full_cmd_args[:150]}", file=sys.stderr)

        # 清理 Windows 特有的转义字符
        clean_json = full_cmd_args.replace('\\"', '"').replace("\\'", "'")
        print(f"DEBUG: cleaned args = {clean_json[:150]}", file=sys.stderr)

        # 提取 JSON 对象（找到第一个 { 和最后一个 }）
        start = clean_json.find("{")
        end = clean_json.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw_json = clean_json[start : end + 1]
            print(f"DEBUG: extracted JSON = {raw_json[:100]}", file=sys.stderr)
        else:
            raw_json = clean_json
            print(
                f"DEBUG: using full string as JSON = {raw_json[:100]}", file=sys.stderr
            )

        # 尝试解析 JSON
        try:
            args = json.loads(raw_json)
            print("DEBUG: JSON parsed successfully", file=sys.stderr)
        except json.JSONDecodeError as e:
            # 尝试修复常见的 JSON 格式问题
            fixed_json = raw_json

            # 移除可能的外层引号（Shell 添加的）
            if (fixed_json.startswith("'") and fixed_json.endswith("'")) or (
                fixed_json.startswith('"') and fixed_json.endswith('"')
            ):
                fixed_json = fixed_json[1:-1]
                print(f"DEBUG: removed outer quotes", file=sys.stderr)

            import re

            # 第 1 步：修复键没有引号的情况：{to: ...} -> {"to": ...}
            fixed_json = re.sub(
                r"(\{|,)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:", r'\1 "\2":', fixed_json
            )

            # 第 2 步：修复数组中的字符串缺少引号：[zhao weiling] -> ["zhao weiling"]
            # 匹配 [ 后面的非数字、非布尔、非 null 的值
            def fix_array_value(match):
                value = match.group(1)
                # 如果已经是引号包裹的，不处理
                if value.startswith('"') or value.startswith("'"):
                    return match.group(0)
                # 如果是数字、布尔、null，不处理
                if re.match(r"^-?\d+\.?\d*$", value) or value in [
                    "true",
                    "false",
                    "null",
                ]:
                    return match.group(0)
                # 否则添加引号
                return f'"{value}"'

            fixed_json = re.sub(
                r"\[\s*([^\[\]]+?)\s*\]",
                lambda m: "["
                + re.sub(
                    r"([^,\[\]\s][^,\[\]]*[^,\[\]\s]|[^,\[\]\s])",
                    fix_array_value,
                    m.group(1),
                )
                + "]",
                fixed_json,
            )

            # 第 3 步：修复字符串值缺少引号（在 : 后面，, 或 } 前面）
            # 匹配 : 后面的非引号、非数字、非布尔、非 null 的值
            def fix_string_value(match):
                prefix = match.group(1)  # ": "
                value = match.group(2)  # 实际值

                # 如果已经是引号包裹的，不处理
                if value.startswith('"') or value.startswith("'"):
                    return match.group(0)
                # 如果是数组，不处理（已经在第 2 步处理过了）
                if value.startswith("["):
                    return match.group(0)
                # 如果是数字、布尔、null，不处理
                if re.match(r"^-?\d+\.?\d*$", value) or value in [
                    "true",
                    "false",
                    "null",
                ]:
                    return match.group(0)
                # 否则添加引号
                return f'{prefix}"{value}"'

            fixed_json = re.sub(r"(:\s*)([^,}\]]+)", fix_string_value, fixed_json)

            print(f"DEBUG: trying fixed JSON = {fixed_json[:150]}", file=sys.stderr)

            try:
                args = json.loads(fixed_json)
                print("DEBUG: JSON fixed and parsed successfully", file=sys.stderr)
            except json.JSONDecodeError as e3:
                error_msg = {
                    "success": False,
                    "error": f"JSON 解析失败: {str(e3)}",
                    "hint": '请确保 JSON 参数格式正确，例如: {{"if_unread": true}}',
                    "received": raw_json,
                    "tried_to_fix": fixed_json,
                }
                print(json.dumps(error_msg, ensure_ascii=False))
                sys.exit(1)

    actions = {
        "read_inbox": read_inbox_emails,
        "read_sent": read_sent_emails,
        "send_email": send_email,
        "reply_email": reply_email,
        "read_meetings": read_meetings,
        "send_meeting": send_meeting,
    }

    if action not in actions:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": f"未知操作: {action}",
                    "available_actions": list(actions.keys()),
                }
            )
        )
        sys.exit(1)

    result = actions[action](args)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
