# scripts/outlook_service.py
import os
import tempfile

# 🔴 新增：智能导入依赖库，提供友好的安装指导
try:
    import win32com
    HAS_WIN32COM = True
except ImportError:
    HAS_WIN32COM = False
    print("⚠️ 警告：未找到 pywin32 库")

# 在任何其他 win32com 导入之前强制重定向
if HAS_WIN32COM:
    cache_dir = os.path.join(tempfile.gettempdir(), "gen_py_thomas")
    os.makedirs(cache_dir, exist_ok=True)

    # 强制覆盖全局生成路径
    win32com.__gen_path__ = cache_dir
    os.environ["PYTHONCOMCACHE"] = cache_dir

    # 现在才导入具体的客户端
    import win32com.client
    import pythoncom
from datetime import datetime, timedelta


class OutlookService:
    def __init__(self):
        """初始化 Outlook 应用程序"""
        # 🔴 关键修复：检查 win32com 是否可用
        if not HAS_WIN32COM:
            raise ImportError(
                "❌ 缺少必要依赖库：pywin32\n\n"
                "请使用以下命令安装：\n"
                "pip install pywin32\n\n"
                "安装完成后重新执行任务。"
            )
        
        pythoncom.CoInitialize()
        self.outlook = win32com.client.Dispatch("Outlook.Application")
        self.namespace = self.outlook.GetNamespace("MAPI")

    def get_all_folders(self, folder_type=None, exclude_folders=None):
        """
        获取所有文件夹（包括在线邮箱和 PST 文件）

        Args:
            folder_type: 文件夹类型，如 6=收件箱，5=已发送邮件，9=日历
            exclude_folders: 需要排除的文件夹名称列表
        """
        all_folders = []
        if exclude_folders is None:
            exclude_folders = []

        try:
            for store in self.namespace.Stores:
                try:
                    if folder_type:
                        folder = store.GetDefaultFolder(folder_type)
                        if folder.Name not in exclude_folders:
                            all_folders.append(folder)
                            self._get_subfolders_recursive(
                                folder, all_folders, exclude_folders
                            )
                    else:
                        root = store.GetRootFolder()
                        if root.Name not in exclude_folders:
                            all_folders.append(root)
                            self._get_subfolders_recursive(
                                root, all_folders, exclude_folders
                            )
                except Exception as e:
                    print(f"警告: 无法访问存储 {store.DisplayName} 的文件夹: {e}")
                    continue
        except Exception as e:
            print(f"错误: 获取文件夹时出错: {e}")

        return all_folders

    def _get_subfolders_recursive(
        self, parent_folder, folder_list, exclude_folders=None
    ):
        """递归获取所有子文件夹"""
        if exclude_folders is None:
            exclude_folders = []

        try:
            for folder in parent_folder.Folders:
                if folder.Name not in exclude_folders:
                    folder_list.append(folder)
                    self._get_subfolders_recursive(folder, folder_list, exclude_folders)
        except:
            pass

    def read_inbox_emails(
        self,
        from_email=None,
        to=None,
        cc=None,
        bcc=None,
        subject=None,
        body=None,
        attachment=None,
        start_time=None,
        end_time=None,
        if_unread=False,
        limit=None,
    ):
        """
        读取收件箱邮件（排除已删除邮件和草稿文件夹）
        
        Args:
            limit: 最大读取数量，默认 20 封（从今天开始往前推）
        """
        all_emails = []
        
        # 如果未指定 limit，默认 20 封
        if limit is None:
            limit = 20

        exclude_folders = [
            "已删除邮件",
            "草稿",
            "Deleted Items",
            "Drafts",
            "已发送邮件",
            "发件箱",
            "Outbox",
            "各种申请",
            "同步问题",
            "冲突",
        ]

        all_folders = self.get_all_folders(exclude_folders=exclude_folders)
        print(f"开始读取文件夹中的收件箱邮件（最多 {limit} 封）...")

        for folder in all_folders:
            # 检查是否已达到限制
            if len(all_emails) >= limit:
                break
                
            try:
                items = folder.Items
                if items.Count > 0:
                    for item in items:
                        # 检查是否已达到限制
                        if len(all_emails) >= limit:
                            break
                            
                        try:
                            if (
                                hasattr(item, "MessageClass")
                                and "IPM.Note" in item.MessageClass
                            ):
                                if hasattr(item, "ReceivedTime"):
                                    if self._filter_email(
                                        item,
                                        from_email,
                                        to,
                                        cc,
                                        bcc,
                                        subject,
                                        body,
                                        attachment,
                                        start_time,
                                        end_time,
                                        if_unread,
                                    ):
                                        email_info = self._extract_email_details(
                                            item, folder.Name
                                        )
                                        if email_info:
                                            all_emails.append(email_info)
                        except Exception:
                            continue
            except Exception:
                continue

        print(f"\n读取完成，共返回 {len(all_emails)} 封收件箱邮件")
        return all_emails

    def read_sent_emails(
        self,
        to=None,
        cc=None,
        bcc=None,
        subject=None,
        body=None,
        attachment=None,
        start_time=None,
        end_time=None,
        limit=None,
    ):
        """
        读取已发送邮件和发件箱中的邮件
        
        Args:
            limit: 最大读取数量，默认 20 封（从今天开始往前推）
        """
        include_folders = ["已发送邮件", "发件箱", "Outbox"]
        all_emails = []
        sent_folders = []
        
        # 如果未指定 limit，默认 20 封
        if limit is None:
            limit = 20

        for store in self.namespace.Stores:
            try:
                try:
                    sent_folder = store.GetDefaultFolder(5)
                    sent_folders.append(sent_folder)
                except:
                    pass

                root = store.GetRootFolder()
                for folder in root.Folders:
                    if folder.Name in include_folders:
                        sent_folders.append(folder)
            except:
                continue

        print(f"开始读取发送邮件文件夹（最多 {limit} 封）...")

        for folder in sent_folders:
            # 检查是否已达到限制
            if len(all_emails) >= limit:
                break
                
            try:
                items = folder.Items
                if items.Count > 0:
                    for item in items:
                        # 检查是否已达到限制
                        if len(all_emails) >= limit:
                            break
                            
                        try:
                            if (
                                hasattr(item, "MessageClass")
                                and "IPM.Note" in item.MessageClass
                            ):
                                if self._filter_sent_email(
                                    item,
                                    to,
                                    cc,
                                    bcc,
                                    subject,
                                    body,
                                    attachment,
                                    start_time,
                                    end_time,
                                ):
                                    email_info = self._extract_email_details(
                                        item, folder.Name
                                    )
                                    if email_info:
                                        all_emails.append(email_info)
                        except Exception:
                            continue
            except Exception:
                continue

        print(f"\n读取完成，共返回 {len(all_emails)} 封发送邮件")
        return all_emails

    def read_meetings(
        self,
        from_email=None,
        to=None,
        participants=None,
        meeting_room=None,
        subject=None,
        body=None,
        attachment=None,
        start_time=None,
        end_time=None,
    ):
        """
        读取所有会议邀请
        
        Args:
            start_time: 开始时间，如果为 None 且 end_time 也为 None，默认为今天
            end_time: 结束时间，如果为 None 且 start_time 也为 None，默认为今天 + 7天
        """
        all_meetings = []
        calendar_folders = []
        
        # 默认时间范围：从今天开始的近7天
        if start_time is None and end_time is None:
            start_time = datetime.now().strftime("%Y-%m-%d")
            end_time = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
            print(f"未指定时间范围，默认读取: {start_time} 至 {end_time}")
        elif start_time is not None and end_time is None:
            # 只有开始时间，往后推 7 天
            end_time = (datetime.strptime(start_time, "%Y-%m-%d") + timedelta(days=7)).strftime("%Y-%m-%d")
            print(f"未指定结束时间，默认读取: {start_time} 至 {end_time}")
        elif start_time is None and end_time is not None:
            # 只有结束时间，从当天开始
            start_time = datetime.now().strftime("%Y-%m-%d")
            print(f"未指定开始时间，默认读取: {start_time} 至 {end_time}")
        else:
            print(f"读取指定时间范围: {start_time} 至 {end_time}")

        for store in self.namespace.Stores:
            try:
                calendar = store.GetDefaultFolder(9)
                calendar_folders.append(calendar)
                self._get_subfolders_recursive(calendar, calendar_folders)
            except:
                continue

        print(f"开始读取 {len(calendar_folders)} 个日历文件夹...")

        for folder in calendar_folders:
            try:
                items = folder.Items
                if items.Count > 0:
                    for item in items:
                        try:
                            if (
                                hasattr(item, "MeetingStatus")
                                and item.MeetingStatus > 0
                            ):
                                if self._filter_meeting(
                                    item,
                                    from_email,
                                    to,
                                    participants,
                                    meeting_room,
                                    subject,
                                    body,
                                    attachment,
                                    start_time,
                                    end_time,
                                ):
                                    meeting_info = self._extract_meeting_details(
                                        item, folder.Name
                                    )
                                    if meeting_info:
                                        all_meetings.append(meeting_info)
                        except Exception:
                            continue
            except Exception:
                continue

        print(f"\n读取完成，共找到 {len(all_meetings)} 个会议")
        return all_meetings

    def send_email(
        self, to, cc=None, bcc=None, subject=None, body=None, attachment=None
    ):
        """
        发送邮件
        """
        mail = self.outlook.CreateItem(0)

        if to:
            if isinstance(to, str):
                mail.To = to
            elif isinstance(to, list):
                mail.To = ";".join(to)

        if cc:
            if isinstance(cc, str):
                mail.CC = cc
            elif isinstance(cc, list):
                mail.CC = ";".join(cc)

        if bcc:
            if isinstance(bcc, str):
                mail.BCC = bcc
            elif isinstance(bcc, list):
                mail.BCC = ";".join(bcc)

        if subject:
            mail.Subject = subject

        if body:
            html_body = self._build_html_email(body)
            mail.HTMLBody = html_body

        # 【修复】支持多个附件
        if attachment:
            # 统一转换为列表处理
            if isinstance(attachment, str):
                attachment_list = [attachment]
            elif isinstance(attachment, list):
                attachment_list = attachment
            else:
                attachment_list = []
            
            # 添加所有存在的附件
            for att_path in attachment_list:
                if os.path.exists(att_path):
                    mail.Attachments.Add(att_path)
                else:
                    print(f"⚠️  警告：附件文件不存在，跳过: {att_path}")

        mail.Send()
        return True

    def reply_email(
        self,
        entry_id=None,
        body=None,
        reply_all=False,
        cc=None,
        bcc=None,
        attachment=None,
    ):
        """
        回复邮件
        """
        if not entry_id:
            raise Exception("缺少必需参数: entry_id（请先读取邮件获取）")

        try:
            email_item = self.namespace.GetItemFromID(entry_id)
        except Exception as e:
            raise Exception(f"无效的邮件 EntryID：{entry_id}，错误：{str(e)}")

        if not email_item or email_item.MessageClass != "IPM.Note":
            raise Exception("选中的不是标准邮件，无法回复")

        if reply_all:
            reply = email_item.ReplyAll()
        else:
            reply = email_item.Reply()

        if body:
            # 使用 HTML 格式保持编码一致性
            original_html = getattr(email_item, "HTMLBody", "")
            if original_html:
                # 提取原始邮件的 <body> 内容（如果有）
                import re
                body_match = re.search(r'<body[^>]*>(.*?)</body>', original_html, re.IGNORECASE | re.DOTALL)
                if body_match:
                    original_body_content = body_match.group(1)
                else:
                    original_body_content = original_html
                
                # 构建回复 HTML
                reply_html = f"""<html>
<body>
<div style="font-family: '微软雅黑', Arial, sans-serif; font-size: 14px;">
{body}
</div>
<br><br>
<div style="color: #888888; font-size: 12px; border-top: 1px solid #ccc; padding-top: 10px; margin-top: 10px;">
{original_body_content}
</div>
</body>
</html>"""
                reply.HTMLBody = reply_html
            else:
                # 如果没有 HTML，使用纯文本（带编码保护）
                original_body = email_item.Body if email_item.Body else ""
                separator = "\n" + "=" * 50 + "\n"
                reply.Body = f"{body}\n{separator}{original_body}".encode('utf-8').decode('utf-8')

        if cc:
            current_cc = reply.CC if reply.CC else ""
            if current_cc:
                reply.CC = f"{current_cc};{';'.join(cc)}"
            else:
                reply.CC = ";".join(cc)

        # 【修复】支持多个附件
        if attachment:
            # 统一转换为列表处理
            if isinstance(attachment, str):
                attachment_list = [attachment]
            elif isinstance(attachment, list):
                attachment_list = attachment
            else:
                attachment_list = []
            
            # 添加所有存在的附件
            for att_path in attachment_list:
                if os.path.exists(att_path):
                    reply.Attachments.Add(att_path)
                else:
                    print(f"️  警告：附件文件不存在，跳过: {att_path}")

        reply.Send()
        return True

    def send_meeting(
        self,
        participants,
        meeting_room=None,
        subject=None,
        body=None,
        attachment=None,
        start_time=None,
        end_time=None,
    ):
        """
        发送会议邀请
        """
        meeting = self.outlook.CreateItem(1)
        meeting.MeetingStatus = 1

        if start_time:
            start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
            start_dt = start_dt + timedelta(hours=8)
            meeting.Start = start_dt

        if end_time:
            end_dt = datetime.strptime(end_time, "%Y-%m-%d %H:%M")
            end_dt = end_dt + timedelta(hours=8)
            meeting.End = end_dt

        if subject:
            meeting.Subject = subject

        if body:
            html_body = self._build_html_email(body)
            meeting.Body = html_body

        if participants:
            recipients = meeting.Recipients
            for participant in participants:
                if participant:
                    recipient = recipients.Add(participant)
                    recipient.Type = 1

        if meeting_room:
            try:
                meeting.Location = meeting_room
            except Exception:
                pass

        meeting.Recipients.ResolveAll()

        # 【修复】支持多个附件
        if attachment:
            # 统一转换为列表处理
            if isinstance(attachment, str):
                attachment_list = [attachment]
            elif isinstance(attachment, list):
                attachment_list = attachment
            else:
                attachment_list = []
            
            # 添加所有存在的附件
            for att_path in attachment_list:
                if os.path.exists(att_path):
                    meeting.Attachments.Add(att_path)
                else:
                    print(f"⚠️  警告：附件文件不存在，跳过: {att_path}")

        meeting.Send()
        return True

    def close(self):
        """释放资源"""
        pythoncom.CoUninitialize()

    def _extract_email_details(self, item, folder_name):
        """提取邮件的详细信息"""
        try:
            sender_name = getattr(item, "SenderName", "")
            sender_email = getattr(item, "SenderEmailAddress", "")
            to_recipients = getattr(item, "To", "")
            cc_recipients = getattr(item, "CC", "")
            subject = getattr(item, "Subject", "")
            
            # 【关键修复】获取邮件的 EntryID，用于回复邮件
            entry_id = getattr(item, "EntryID", "")

            received_time = ""
            try:
                received_time = getattr(item, "ReceivedTime", "")
                if received_time:
                    received_time = received_time.strftime("%Y-%m-%d %H:%M:%S")
            except:
                pass

            sent_time = ""
            try:
                sent_time = getattr(item, "SentOn", "")
                if sent_time:
                    sent_time = sent_time.strftime("%Y-%m-%d %H:%M:%S")
            except:
                pass

            body = ""
            try:
                body = getattr(item, "Body", "")
                if not body:
                    body = getattr(item, "HTMLBody", "")
            except:
                pass

            attachments = []
            try:
                attachment_items = getattr(item, "Attachments", None)
                if attachment_items and attachment_items.Count > 0:
                    for i in range(attachment_items.Count):
                        try:
                            attachment = attachment_items.Item(i + 1)
                            filename = getattr(attachment, "FileName", "")
                            if filename:
                                attachments.append(
                                    {
                                        "文件名": filename,
                                        "大小": getattr(attachment, "Size", 0),
                                    }
                                )
                        except:
                            continue
            except:
                pass

            read_status = "未知"
            try:
                unread = getattr(item, "Unread", False)
                read_status = "已读" if not unread else "未读"
            except:
                pass

            return {
                "entry_id": entry_id,  # 【新增】返回真实的 EntryID
                "文件夹": folder_name,
                "发件人": {"姓名": sender_name, "邮箱": sender_email},
                "收件人": to_recipients,
                "抄送人": cc_recipients,
                "主题": subject,
                "接收时间": received_time,
                "发送时间": sent_time,
                "状态": read_status,
                "内容": body[:500] + "..." if len(body) > 500 else body,
                "附件": attachments,
            }
        except Exception:
            return None

    def _extract_meeting_details(self, item, folder_name):
        """提取会议的详细信息"""
        try:
            subject = getattr(item, "Subject", "")
            location = getattr(item, "Location", "")
            organizer = getattr(item, "Organizer", "")

            start_time = ""
            try:
                start_time = getattr(item, "Start", "")
                if start_time:
                    start_time = start_time.strftime("%Y-%m-%d %H:%M:%S")
            except:
                pass

            end_time = ""
            try:
                end_time = getattr(item, "End", "")
                if end_time:
                    end_time = end_time.strftime("%Y-%m-%d %H:%M:%S")
            except:
                pass

            body = ""
            try:
                body = getattr(item, "Body", "")
                if not body:
                    body = getattr(item, "HTMLBody", "")
            except:
                pass

            participants = []
            try:
                recipients = getattr(item, "Recipients", None)
                if recipients and recipients.Count > 0:
                    for i in range(recipients.Count):
                        try:
                            recipient = recipients.Item(i + 1)
                            name = getattr(recipient, "Name", "")
                            address = getattr(recipient, "Address", "")
                            response = getattr(recipient, "MeetingResponseStatus", 0)
                            response_text = {
                                0: "无响应",
                                1: "组织者",
                                2: "暂定",
                                3: "接受",
                                4: "拒绝",
                                5: "未响应",
                            }.get(response, "未知")
                            participants.append(
                                {
                                    "姓名": name,
                                    "邮箱": address,
                                    "响应状态": response_text,
                                }
                            )
                        except:
                            continue
            except:
                pass

            attachments = []
            try:
                attachment_items = getattr(item, "Attachments", None)
                if attachment_items and attachment_items.Count > 0:
                    for i in range(attachment_items.Count):
                        try:
                            attachment = attachment_items.Item(i + 1)
                            filename = getattr(attachment, "FileName", "")
                            if filename:
                                attachments.append(
                                    {
                                        "文件名": filename,
                                        "大小": getattr(attachment, "Size", 0),
                                    }
                                )
                        except:
                            continue
            except:
                pass

            meeting_status = ""
            try:
                status = getattr(item, "MeetingStatus", 0)
                status_text = {
                    0: "未设置",
                    1: "会议",
                    3: "已接收",
                    5: "已取消",
                }.get(status, "未知")
                meeting_status = status_text
            except:
                pass

            return {
                "文件夹": folder_name,
                "主题": subject,
                "地点": location,
                "组织者": organizer,
                "开始时间": start_time,
                "结束时间": end_time,
                "状态": meeting_status,
                "内容": body[:500] + "..." if len(body) > 500 else body,
                "参与者": participants,
                "附件": attachments,
            }
        except Exception:
            return None

    def _filter_email(
        self,
        item,
        from_email,
        to,
        cc,
        bcc,
        subject,
        body,
        attachment,
        start_time,
        end_time,
        if_unread=False,
    ):
        """筛选邮件"""
        if if_unread:
            try:
                unread = getattr(item, "Unread", False)
                if not unread:
                    return False
            except:
                return False

        if from_email:
            try:
                sender = getattr(item, "SenderEmailAddress", "")
                if not sender:
                    sender = getattr(item, "Sender", "")
                if from_email.lower() not in str(sender).lower():
                    return False
            except:
                return False

        if to:
            try:
                to_recipients = getattr(item, "To", "")
                if isinstance(to, str):
                    to = [to]
                for to_email in to:
                    if to_email and to_email.lower() not in str(to_recipients).lower():
                        return False
            except:
                return False

        if cc:
            try:
                cc_recipients = getattr(item, "CC", "")
                if isinstance(cc, str):
                    cc = [cc]
                for cc_email in cc:
                    if cc_email and cc_email.lower() not in str(cc_recipients).lower():
                        return False
            except:
                return False

        if bcc:
            try:
                bcc_recipients = getattr(item, "BCC", "")
                if isinstance(bcc, str):
                    bcc = [bcc]
                for bcc_email in bcc:
                    if (
                        bcc_email
                        and bcc_email.lower() not in str(bcc_recipients).lower()
                    ):
                        return False
            except:
                return False

        if subject:
            try:
                item_subject = getattr(item, "Subject", "")
                if subject.lower() not in str(item_subject).lower():
                    return False
            except:
                return False

        if body:
            try:
                item_body = getattr(item, "Body", "")
                if not item_body:
                    item_body = getattr(item, "HTMLBody", "")
                if body.lower() not in str(item_body).lower():
                    return False
            except:
                return False

        if attachment:
            try:
                attachments = getattr(item, "Attachments", None)
                if attachments and attachments.Count > 0:
                    found = False
                    for i in range(attachments.Count):
                        try:
                            att = attachments.Item(i + 1)
                            filename = getattr(att, "FileName", "")
                            if attachment.lower() in str(filename).lower():
                                found = True
                                break
                        except:
                            continue
                    if not found:
                        return False
                else:
                    return False
            except:
                return False

        if start_time:
            try:
                received_time = getattr(item, "ReceivedTime", None)
                if received_time:
                    start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
                    if received_time < start_dt:
                        return False
            except:
                pass

        if end_time:
            try:
                received_time = getattr(item, "ReceivedTime", None)
                if received_time:
                    end_dt = datetime.strptime(end_time, "%Y-%m-%d %H:%M")
                    if received_time > end_dt:
                        return False
            except:
                pass

        return True

    def _filter_sent_email(
        self, item, to, cc, bcc, subject, body, attachment, start_time, end_time
    ):
        """筛选已发送邮件"""
        if to:
            try:
                to_recipients = getattr(item, "To", "")
                if isinstance(to, str):
                    to = [to]
                for to_email in to:
                    if to_email and to_email.lower() not in str(to_recipients).lower():
                        return False
            except:
                return False

        if cc:
            try:
                cc_recipients = getattr(item, "CC", "")
                if isinstance(cc, str):
                    cc = [cc]
                for cc_email in cc:
                    if cc_email and cc_email.lower() not in str(cc_recipients).lower():
                        return False
            except:
                return False

        if bcc:
            try:
                bcc_recipients = getattr(item, "BCC", "")
                if isinstance(bcc, str):
                    bcc = [bcc]
                for bcc_email in bcc:
                    if (
                        bcc_email
                        and bcc_email.lower() not in str(bcc_recipients).lower()
                    ):
                        return False
            except:
                return False

        if subject:
            try:
                item_subject = getattr(item, "Subject", "")
                if subject.lower() not in str(item_subject).lower():
                    return False
            except:
                return False

        if body:
            try:
                item_body = getattr(item, "Body", "")
                if not item_body:
                    item_body = getattr(item, "HTMLBody", "")
                if body.lower() not in str(item_body).lower():
                    return False
            except:
                return False

        if attachment:
            try:
                attachments = getattr(item, "Attachments", None)
                if attachments and attachments.Count > 0:
                    found = False
                    for i in range(attachments.Count):
                        try:
                            att = attachments.Item(i + 1)
                            filename = getattr(att, "FileName", "")
                            if attachment.lower() in str(filename).lower():
                                found = True
                                break
                        except:
                            continue
                    if not found:
                        return False
                else:
                    return False
            except:
                return False

        if start_time:
            try:
                sent_time = getattr(item, "SentOn", None)
                if sent_time:
                    start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
                    if sent_time < start_dt:
                        return False
            except:
                pass

        if end_time:
            try:
                sent_time = getattr(item, "SentOn", None)
                if sent_time:
                    end_dt = datetime.strptime(end_time, "%Y-%m-%d %H:%M")
                    if sent_time > end_dt:
                        return False
            except:
                pass

        return True

    def _filter_meeting(
        self,
        item,
        from_email,
        to,
        participants,
        meeting_room,
        subject,
        body,
        attachment,
        start_time,
        end_time,
    ):
        """筛选会议"""
        if from_email:
            try:
                organizer = getattr(item, "Organizer", "")
                if from_email.lower() not in str(organizer).lower():
                    return False
            except:
                return False

        if to:
            try:
                recipients = getattr(item, "Recipients", None)
                if recipients and recipients.Count > 0:
                    found = False
                    for i in range(recipients.Count):
                        try:
                            recipient = recipients.Item(i + 1)
                            address = getattr(recipient, "Address", "")
                            if isinstance(to, str):
                                to_list = [to]
                            else:
                                to_list = to
                            for to_email in to_list:
                                if to_email.lower() in str(address).lower():
                                    found = True
                                    break
                            if found:
                                break
                        except:
                            continue
                    if not found:
                        return False
                else:
                    return False
            except:
                return False

        if participants:
            try:
                recipients = getattr(item, "Recipients", None)
                if recipients and recipients.Count > 0:
                    participant_emails = []
                    for i in range(recipients.Count):
                        try:
                            recipient = recipients.Item(i + 1)
                            address = getattr(recipient, "Address", "")
                            if address:
                                participant_emails.append(address.lower())
                        except:
                            continue

                    for participant in participants:
                        if participant and not any(
                            participant.lower() in email for email in participant_emails
                        ):
                            return False
                else:
                    return False
            except:
                return False

        if meeting_room:
            try:
                location = getattr(item, "Location", "")
                if meeting_room.lower() not in str(location).lower():
                    return False
            except:
                return False

        if subject:
            try:
                item_subject = getattr(item, "Subject", "")
                if subject.lower() not in str(item_subject).lower():
                    return False
            except:
                return False

        if body:
            try:
                item_body = getattr(item, "Body", "")
                if not item_body:
                    item_body = getattr(item, "HTMLBody", "")
                if body.lower() not in str(item_body).lower():
                    return False
            except:
                return False

        if attachment:
            try:
                attachments = getattr(item, "Attachments", None)
                if attachments and attachments.Count > 0:
                    found = False
                    for i in range(attachments.Count):
                        try:
                            att = attachments.Item(i + 1)
                            filename = getattr(att, "FileName", "")
                            if attachment.lower() in str(filename).lower():
                                found = True
                                break
                        except:
                            continue
                    if not found:
                        return False
                else:
                    return False
            except:
                return False

        if start_time:
            try:
                start = getattr(item, "Start", None)
                if start:
                    start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
                    if start < start_dt:
                        return False
            except:
                pass

        if end_time:
            try:
                end = getattr(item, "End", None)
                if end:
                    end_dt = datetime.strptime(end_time, "%Y-%m-%d %H:%M")
                    if end > end_dt:
                        return False
            except:
                pass

        return True

    def _build_html_email(self, body):
        """构建 HTML 格式邮件"""
        # 🔴 新增：从外部文件读取签名，方便用户自定义
        try:
            from src.utils.path_adapter import get_base_dir
            signature_file = get_base_dir() / "email_signiture.txt"
            if signature_file.exists():
                with open(signature_file, 'r', encoding='utf-8') as f:
                    signature_text = f.read().strip()
                # 将纯文本转换为 HTML 格式（每行用 <br> 换行）
                HTML_SIGNATURE = "<br><br>\n<hr style=\"border:1px solid #ccc\">\n<div style=\"font-family: 微软雅黑; color: 'black'; font-size: 12px;\">\n" + \
                                signature_text.replace('\n', '<br>\n') + "\n</div>"
            else:
                # 如果文件不存在，使用默认签名
                HTML_SIGNATURE = """
<br><br>
<hr style="border:1px solid #ccc">
<div style="font-family: 微软雅黑; color: 'black'; font-size: 12px;">
Kind Regards / 美好祝愿<br>
Shun Li / 李顺<br>
HRM / 人力资源管理部<br>
Fulscience Automotive Electronics Co.,Ltd.<br>
富赛汽车电子有限公司<br>
No. 7999 Dongfeng Street, Automobile Economic & Technological Development Zone, Changchun City<br>
长春市汽车产业开发区东风大街7999号<br>
Postcode邮编:130000<br>
Mobile 131-6687-6027 <br>
Important Note: This e-mail and any attachments are confidential, may contain trade secrets and may well also be legally privileged or otherwise protected from disclosure. If you are not the intended recipient, please understand that you must not copy this e-mail or any attachments or disclose the contents to any other person, delete this e-mail and any attachment from your system immediately. Thank you!<br>
重要提示：该电子邮件和任何附件是保密的，可能包含商业秘密，也很可能在法律上享有特权。如果您不是预期的收件人，请您明白，您不能复制该电子邮件或任何附件或向任何其他人披露内容，并从您的系统立即删除该电子邮件和任何附件。谢谢<br>
</div>
"""
        except Exception as e:
            print(f"⚠️ 警告：读取签名文件失败：{e}，使用默认签名")
            HTML_SIGNATURE = """
<br><br>
<hr style="border:1px solid #ccc">
<div style="font-family: 微软雅黑; color: 'black'; font-size: 12px;">
Kind Regards / 美好祝愿<br>
Shun Li / 李顺<br>
HRM / 人力资源管理部<br>
Fulscience Automotive Electronics Co.,Ltd.<br>
富赛汽车电子有限公司<br>
No. 7999 Dongfeng Street, Automobile Economic & Technological Development Zone, Changchun City<br>
长春市汽车产业开发区东风大街7999号<br>
Postcode邮编:130000<br>
Mobile 131-6687-6027 <br>
Important Note: This e-mail and any attachments are confidential, may contain trade secrets and may well also be legally privileged or otherwise protected from disclosure. If you are not the intended recipient, please understand that you must not copy this e-mail or any attachments or disclose the contents to any other person, delete this e-mail and any attachment from your system immediately. Thank you!<br>
重要提示：该电子邮件和任何附件是保密的，可能包含商业秘密，也很可能在法律上享有特权。如果您不是预期的收件人，请您明白，您不能复制该电子邮件或任何附件或向任何其他人披露内容，并从您的系统立即删除该电子邮件和任何附件。谢谢<br>
</div>
"""
        html_body = f"""
<html>
<head>
<style>
    .email-body {{
        font-family: '微软雅黑', 'Microsoft YaHei', Arial, sans-serif;
        font-size: 14px;
        color: #333333;
        line-height: 1.6;
    }}
</style>
</head>
<body>
<div class="email-body">
{body}
{HTML_SIGNATURE}
</div>
</body>
</html>
"""
        return html_body
