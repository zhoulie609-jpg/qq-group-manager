import tempfile
import unittest
import sys
import types
from pathlib import Path

if "websocket" not in sys.modules:
    websocket_stub = types.ModuleType("websocket")
    websocket_stub.WebSocketApp = object
    sys.modules["websocket"] = websocket_stub

from qq_group_manager.db import Database
from qq_group_manager.service import GLOBAL_BLACK_RE, ManagerService


class FakeClient:
    def __init__(self):
        self.calls = []

    def call_async(self, action, params=None):
        self.calls.append((action, params or {}))


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.service = ManagerService(self.db, lambda _x: None, lambda: None)
        self.fake = FakeClient()
        self.service.client = self.fake

    def tearDown(self):
        self.tmp.cleanup()

    def test_command_format_is_strict(self):
        self.assertEqual(GLOBAL_BLACK_RE.fullmatch("123456T").group(1), "123456")
        self.assertEqual(GLOBAL_BLACK_RE.fullmatch(" 123456t ").group(1), "123456")
        self.assertIsNone(GLOBAL_BLACK_RE.fullmatch("拉黑123456T"))

    def test_group_rule_overrides_global(self):
        self.db.add_entry("123456", "black", "global")
        self.db.add_entry("123456", "white", "group", "888")
        self.assertEqual(self.db.status("123456", "777"), "black")
        self.assertEqual(self.db.status("123456", "888"), "white")

    def test_authorized_t_command_blacklists_and_kicks_all_enabled_groups(self):
        self.db.set_setting("admin_qqs", "111,222")
        self.db.upsert_group("1001", "A", 1)
        self.db.upsert_group("1002", "B", 1)
        self.service.handle_event({
            "post_type": "message", "message_type": "group", "user_id": 111,
            "group_id": 1001, "raw_message": "987654T",
        })
        self.assertEqual(self.db.status("987654", "1001"), "black")
        kicks = [c for c in self.fake.calls if c[0] == "set_group_kick"]
        self.assertEqual(len(kicks), 2)
        self.assertTrue(all(c[1]["reject_add_request"] for c in kicks))

    def test_unauthorized_t_command_is_ignored(self):
        self.db.set_setting("admin_qqs", "111")
        self.db.upsert_group("1001", "A", 1)
        self.service.handle_event({
            "post_type": "message", "message_type": "group", "user_id": 333,
            "group_id": 1001, "raw_message": "987654T",
        })
        self.assertIsNone(self.db.status("987654", "1001"))

    def test_command_from_unmanaged_group_is_ignored(self):
        self.db.set_setting("admin_qqs", "111")
        self.service.handle_event({
            "post_type": "message", "message_type": "group", "user_id": 111,
            "group_id": 9999, "raw_message": "987654T",
        })
        self.assertIsNone(self.db.status("987654", "9999"))

    def test_blacklisted_join_is_rejected_with_reason(self):
        self.db.upsert_group("1001", "A", 1)
        self.db.add_entry("987654", "black", "global")
        self.db.set_setting("reject_reason", "黑名单自动拒绝")
        self.service.handle_event({
            "post_type": "request", "request_type": "group", "group_id": 1001,
            "user_id": 987654, "flag": "abc", "sub_type": "add",
        })
        self.assertEqual(self.fake.calls[0][0], "set_group_add_request")
        self.assertFalse(self.fake.calls[0][1]["approve"])
        self.assertEqual(self.fake.calls[0][1]["reason"], "黑名单自动拒绝")


if __name__ == "__main__":
    unittest.main()
