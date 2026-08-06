from __future__ import annotations

import re
import threading
from typing import Callable

from .db import Database
from .onebot import OneBotClient


GLOBAL_BLACK_RE = re.compile(r"^\s*(\d{5,12})[Tt]\s*$")


class ManagerService:
    def __init__(self, db: Database, notify: Callable[[str], None], refresh: Callable[[], None]):
        self.db = db
        self.notify = notify
        self.refresh = refresh
        self.client = OneBotClient(self.handle_event, notify)

    def admins(self) -> set[str]:
        return {x.strip() for x in self.db.get_setting("admin_qqs", "").split(",") if x.strip()}

    def handle_event(self, event: dict) -> None:
        if self.db.get_setting("blacklist_plugin_enabled", "1") != "1":
            return
        try:
            if event.get("post_type") == "request" and event.get("request_type") == "group":
                self._handle_group_request(event)
            elif event.get("post_type") == "message" and event.get("message_type") == "group":
                self._handle_group_message(event)
        except Exception as exc:
            self.notify(f"事件处理失败: {exc}")

    def _handle_group_request(self, event: dict) -> None:
        qq, group_id = str(event.get("user_id", "")), str(event.get("group_id", ""))
        if not any(g["group_id"] == group_id for g in self.db.groups(enabled_only=True)):
            return
        status = self.db.status(qq, group_id)
        if status == "black":
            reason = self.db.get_setting("reject_reason", "该账号在黑名单中，已自动拒绝")
            self.client.call_async("set_group_add_request", {
                "flag": event.get("flag", ""), "sub_type": event.get("sub_type", "add"),
                "approve": False, "reason": reason,
            })
            self.db.log("自动拒绝入群", qq, group_id, reason)
            self.refresh()
        elif status == "white" and self.db.get_setting("auto_approve_white", "1") == "1":
            self.client.call_async("set_group_add_request", {
                "flag": event.get("flag", ""), "sub_type": event.get("sub_type", "add"), "approve": True,
            })
            self.db.log("白名单自动通过", qq, group_id, str(event.get("comment", "")))
            self.refresh()
        else:
            self.db.log("待人工审核", qq, group_id, f"flag={event.get('flag','')}|sub_type={event.get('sub_type','add')}|{event.get('comment','')}")
            self.notify(f"收到入群申请: {qq} → {group_id}")
            self.refresh()

    def _handle_group_message(self, event: dict) -> None:
        sender = str(event.get("user_id", ""))
        group_id = str(event.get("group_id", ""))
        raw = event.get("raw_message", "")
        match = GLOBAL_BLACK_RE.fullmatch(str(raw))
        if not match:
            return
        if not any(g["group_id"] == group_id for g in self.db.groups(enabled_only=True)):
            return
        if sender not in self.admins():
            self.db.log("拒绝未授权命令", sender, group_id, str(raw))
            return
        target = match.group(1)
        self.global_blacklist(target, f"管理员 {sender} 通过 {target}T 指令添加", kick=True)
        self.client.call_async("send_group_msg", {"group_id": int(group_id), "message": f"已将 {target} 加入全局黑名单，并从所有已管理群移除。"})

    def global_blacklist(self, qq: str, remark: str = "人工添加", kick: bool = True) -> None:
        self.db.add_entry(qq, "black", "global", remark=remark)
        self.db.log("加入全局黑名单", qq, detail=remark)
        if kick:
            for group in self.db.groups(enabled_only=True):
                self.client.call_async("set_group_kick", {"group_id": int(group["group_id"]), "user_id": int(qq), "reject_add_request": True})
        self.refresh()

    def sync_groups(self) -> list[dict]:
        groups = self.client.call("get_group_list") or []
        for group in groups:
            self.db.upsert_group(str(group["group_id"]), str(group.get("group_name", "")))
        return groups

    def group_member_count(self, group_id: str) -> int:
        members = self.client.call("get_group_member_list", {"group_id": int(group_id), "no_cache": True}) or []
        return len(members)
