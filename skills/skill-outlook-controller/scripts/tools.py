# scripts/tools.py
from langchain.tools import tool
from typing import List, Optional
from .schemas import (
    ReadEmailInput, ReadMeetingInput, SendEmailInput,
    ReplyEmailInput, SendMeetingInput
)
from .outlook_service import OutlookService


@tool(args_schema=ReadEmailInput)
def read_inbox_emails(
    from_email: Optional[str] = None,
    to: Optional[List[str]] = None,
    cc: Optional[List[str]] = None,
    bcc: Optional[List[str]] = None,
    subject: Optional[str] = None,
    body: Optional[str] = None,
    attachment: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    if_unread: Optional[bool] = False,
) -> dict:
    """
    读取收件箱邮件的主函数，当用户需要读取收件箱邮件时，调用此函数。
    
    Args:
        from_email: 发件人邮箱地址
        to: 收件人邮箱地址列表
        cc: 抄送人邮箱地址列表
        bcc: 密送人邮箱地址列表
        subject: 邮件主题
        body: 邮件正文
        attachment: 附件关键词
        start_time: 开始时间 (格式: YYYY-MM-DD HH:MM)
        end_time: 结束时间 (格式: YYYY-MM-DD HH:MM)
        if_unread: 是否只读未读邮件
    """
    service = None
    try:
        service = OutlookService()
        emails = service.read_inbox_emails(
            from_email=from_email, to=to, cc=cc, bcc=bcc,
            subject=subject, body=body, attachment=attachment,
            start_time=start_time, end_time=end_time, if_unread=if_unread
        )
        emails_dict = {}
        for i, email in enumerate(emails):
            # 【关键修复】保留真实的 entry_id，并添加 1-based 索引
            email["index"] = i + 1  # Agent 使用此索引（1-based）
            if not email.get("entry_id"):
                email["entry_id"] = f"邮件_{i+1}"  # 备用 ID
            emails_dict[i] = email  # 字典键仍为 0-based 用于展示
        return {"messages": f"收取的邮件已读取，详细信息为{emails_dict}"}
    except Exception as e:
        return {"messages": f"读取收取邮件失败: {str(e)}"}
    finally:
        if service:
            service.close()


@tool(args_schema=ReadEmailInput)
def read_sent_emails(
    to: Optional[List[str]] = None,
    cc: Optional[List[str]] = None,
    bcc: Optional[List[str]] = None,
    subject: Optional[str] = None,
    body: Optional[str] = None,
    attachment: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> dict:
    """
    读取已发送邮件的主函数，当用户需要读取已发送邮件时，调用此函数。
    
    Args:
        to: 收件人邮箱地址列表
        cc: 抄送人邮箱地址列表
        bcc: 密送人邮箱地址列表
        subject: 邮件主题
        body: 邮件正文
        attachment: 附件关键词
        start_time: 开始时间 (格式: YYYY-MM-DD HH:MM)
        end_time: 结束时间 (格式: YYYY-MM-DD HH:MM)
    """
    service = None
    try:
        service = OutlookService()
        emails = service.read_sent_emails(
            to=to, cc=cc, bcc=bcc, subject=subject,
            body=body, attachment=attachment,
            start_time=start_time, end_time=end_time
        )
        emails_dict = {}
        for i, email in enumerate(emails):
            # 【关键修复】保留真实的 entry_id，并添加 1-based 索引
            email["index"] = i + 1  # Agent 使用此索引（1-based）
            if not email.get("entry_id"):
                email["entry_id"] = f"邮件_{i+1}"  # 备用 ID
            emails_dict[i] = email  # 字典键仍为 0-based 用于展示
        return {"messages": f"发送的邮件已读取，详细信息为{emails_dict}"}
    except Exception as e:
        return {"messages": f"读取发送邮件失败: {str(e)}"}
    finally:
        if service:
            service.close()


@tool(args_schema=ReadMeetingInput)
def read_meetings(
    from_email: str = None,
    to: List[str] = [],
    participants: List[str] = [],
    meeting_room: Optional[str] = None,
    subject: Optional[str] = None,
    body: Optional[str] = None,
    attachment: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> dict:
    """
    读取会议日程的主函数，当用户需要读取会议日程时，调用此函数。
    
    Args:
        from_email: 发件人邮箱地址
        to: 收件人邮箱地址列表
        participants: 参与者邮箱地址列表
        meeting_room: 会议室名称
        subject: 会议主题
        body: 会议正文
        attachment: 附件关键词
        start_time: 开始时间 (格式: YYYY-MM-DD HH:MM)
        end_time: 结束时间 (格式: YYYY-MM-DD HH:MM)
    """
    service = None
    try:
        service = OutlookService()
        meetings = service.read_meetings(
            from_email=from_email, to=to, participants=participants,
            meeting_room=meeting_room, subject=subject, body=body,
            attachment=attachment, start_time=start_time, end_time=end_time
        )
        meetings_dict = {}
        for i, meeting in enumerate(meetings):
            # 【关键修复】添加 1-based 索引
            meeting["index"] = i + 1  # Agent 使用此索引（1-based）
            meetings_dict[i] = meeting  # 字典键仍为 0-based 用于展示
        return {
            "messages": f"会议日程已读取，详细信息为{meetings_dict}，请终止调用会议日程"
        }
    except Exception as e:
        return {"messages": f"读取会议日程失败: {str(e)}"}
    finally:
        if service:
            service.close()


@tool(args_schema=SendEmailInput)
def send_email(
    to: List[str],
    cc: Optional[list[str]] = None,
    bcc: Optional[list[str]] = None,
    subject: str = ...,
    body: Optional[str] = None,
    attachment: Optional[str] = None,
) -> dict:
    """
    发送邮件的主函数，当用户需要发送邮件时，调用此函数。
    
    Args:
        to: 收件人邮箱地址列表
        cc: 抄送邮箱地址列表
        bcc: 密送邮箱地址列表
        subject: 邮件主题
        body: 邮件正文
        attachment: 附件文件路径（多个路径用分号分隔）
    """
    service = None
    try:
        service = OutlookService()
        service.send_email(
            to=to, cc=cc, bcc=bcc, subject=subject,
            body=body, attachment=attachment
        )
        return {"messages": "邮件发送成功，请提醒用户"}
    except Exception as e:
        return {"messages": f"邮件发送失败: {str(e)}"}
    finally:
        if service:
            service.close()


@tool(args_schema=ReplyEmailInput)
def reply_email(
    entry_id: str,
    body: str = ...,
    reply_all: bool = False,
    cc: Optional[list[str]] = [],
    bcc: Optional[list[str]] = [],
    attachment: Optional[str] = None,
) -> dict:
    """
    回复邮件的主函数，当用户需要回复邮件时，调用此函数。
    
    必须先读取邮件获取 entry_id，然后使用 entry_id 回复邮件。
    
    Args:
        entry_id: 要回复的邮件 EntryID（从读取邮件的返回结果中获取）
        body: 回复内容
        reply_all: 是否回复所有人（包括抄送）
        cc: 额外抄送地址列表
        bcc: 额外密送地址列表
        attachment: 附件文件路径
    """
    service = None
    try:
        service = OutlookService()
        service.reply_email(
            entry_id=entry_id,
            body=body, reply_all=reply_all,
            cc=cc, bcc=bcc, attachment=attachment
        )
        return {"messages": "✓ 邮件回复成功"}
    except Exception as e:
        return {"messages": f"✗ 回复邮件失败：{str(e)}"}
    finally:
        if service:
            service.close()


@tool(args_schema=SendMeetingInput)
def send_meeting(
    participants: List[str],
    meeting_room: Optional[str] = None,
    subject: str = ...,
    body: Optional[str] = None,
    attachment: Optional[str] = None,
    start_time: str = ...,
    end_time: str = ...,
) -> dict:
    """
    发送会议邀请的主函数，当用户需要发送会议邀请时，调用此函数。
    
    Args:
        participants: 参与者邮箱地址列表
        meeting_room: 会议室（完整邮箱地址）
        subject: 会议主题
        body: 会议正文
        attachment: 附件文件路径
        start_time: 开始时间 (格式: YYYY-MM-DD HH:MM)
        end_time: 结束时间 (格式: YYYY-MM-DD HH:MM)
    """
    service = None
    try:
        service = OutlookService()
        service.send_meeting(
            participants=participants, meeting_room=meeting_room,
            subject=subject, body=body, attachment=attachment,
            start_time=start_time, end_time=end_time
        )
        return {"messages": "会议发送成功，请通知用户"}
    except Exception as e:
        return {"messages": f"会议发送失败: {str(e)}"}
    finally:
        if service:
            service.close()