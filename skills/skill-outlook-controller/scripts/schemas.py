# scripts/schemas.py
from pydantic import BaseModel, Field
from typing import List, Optional


class ReadEmailInput(BaseModel):
    """读取邮件输入 (收件箱/发件箱通用)。"""
    
    from_email: Optional[str] = Field(None, description="发件人邮箱")
    to: Optional[List[str]] = Field(default_factory=list, description="收件人列表")
    cc: Optional[List[str]] = Field(default_factory=list, description="抄送列表")
    bcc: Optional[List[str]] = Field(default_factory=list, description="密送列表")
    subject: Optional[str] = Field(None, description="主题关键词")
    body: Optional[str] = Field(None, description="正文关键词")
    attachment: Optional[str] = Field(None, description="附件关键词")
    start_time: Optional[str] = Field(None, description="开始时间 YYYY-MM-DD HH:MM")
    end_time: Optional[str] = Field(None, description="结束时间 YYYY-MM-DD HH:MM")
    if_unread: Optional[bool] = Field(False, description="仅未读邮件")


class ReadMeetingInput(BaseModel):
    """读取会议输入。"""
    
    from_email: Optional[str] = Field(None, description="组织者邮箱")
    to: Optional[List[str]] = Field(default_factory=list, description="收件人列表")
    participants: Optional[List[str]] = Field(
        default_factory=list, description="参与者列表"
    )
    meeting_room: Optional[str] = Field(None, description="会议室名称")
    subject: Optional[str] = Field(None, description="主题关键词")
    body: Optional[str] = Field(None, description="议程关键词")
    attachment: Optional[str] = Field(None, description="附件关键词")
    start_time: Optional[str] = Field(None, description="开始时间 YYYY-MM-DD HH:MM")
    end_time: Optional[str] = Field(None, description="结束时间 YYYY-MM-DD HH:MM")


class SendEmailInput(BaseModel):
    """发送邮件输入。"""
    
    to: list[str] = Field(..., description="收件人列表")
    cc: Optional[list[str]] = Field(default_factory=list, description="抄送列表")
    bcc: Optional[list[str]] = Field(default_factory=list, description="密送列表")
    subject: str = Field(..., description="邮件主题")
    body: Optional[str] = Field(..., description="邮件正文")
    attachment: Optional[list[str]] = Field(default_factory=list, description="附件路径列表（支持多个附件）")


class ReplyEmailInput(BaseModel):
    """回复邮件输入。"""
    
    entry_id: str = Field(..., description="要回复的邮件 EntryID（从读取邮件的返回结果中获取）")
    body: str = Field(..., description="回复内容")
    reply_all: bool = Field(False, description="是否回复所有人")
    cc: Optional[list[str]] = Field(
        default_factory=list, description="额外添加的抄送列表"
    )
    bcc: Optional[list[str]] = Field(
        default_factory=list, description="额外添加的密送列表"
    )
    attachment: Optional[list[str]] = Field(default_factory=list, description="添加的附件路径列表（支持多个附件）")


class SendMeetingInput(BaseModel):
    """发送会议邀请输入。"""
    
    participants: List[str] = Field(..., description="参与者邮箱列表")
    meeting_room: Optional[str] = Field(None, description="会议室名称/资源邮箱")
    subject: str = Field(..., description="会议主题")
    body: Optional[str] = Field(None, description="会议议程")
    attachment: Optional[list[str]] = Field(default_factory=list, description="附件路径列表（支持多个附件）")
    start_time: str = Field(..., description="开始时间 YYYY-MM-DD HH:MM")
    end_time: str = Field(..., description="结束时间 YYYY-MM-DD HH:MM")