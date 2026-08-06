from __future__ import annotations

import sqlite3
import threading
from pathlib import Path


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS managed_groups (
                    group_id TEXT PRIMARY KEY,
                    group_name TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS access_list (
                    qq TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('black','white')),
                    scope TEXT NOT NULL DEFAULT 'global',
                    group_id TEXT NOT NULL DEFAULT '',
                    remark TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (qq, kind, scope, group_id)
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    qq TEXT NOT NULL DEFAULT '',
                    group_id TEXT NOT NULL DEFAULT '',
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def get_setting(self, key: str, default: str = "") -> str:
        with self.lock:
            row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def upsert_group(self, group_id: str, name: str, enabled: int | None = None) -> None:
        with self.lock, self.conn:
            if enabled is None:
                self.conn.execute(
                    "INSERT INTO managed_groups(group_id,group_name,enabled) VALUES(?,?,0) "
                    "ON CONFLICT(group_id) DO UPDATE SET group_name=excluded.group_name",
                    (group_id, name),
                )
            else:
                self.conn.execute(
                    "INSERT INTO managed_groups(group_id,group_name,enabled) VALUES(?,?,?) "
                    "ON CONFLICT(group_id) DO UPDATE SET group_name=excluded.group_name,enabled=excluded.enabled",
                    (group_id, name, enabled),
                )

    def groups(self, enabled_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM managed_groups" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY group_name"
        with self.lock:
            return [dict(x) for x in self.conn.execute(sql).fetchall()]

    def set_group_enabled(self, group_id: str, enabled: bool) -> None:
        with self.lock, self.conn:
            self.conn.execute("UPDATE managed_groups SET enabled=? WHERE group_id=?", (int(enabled), group_id))

    def add_entry(self, qq: str, kind: str, scope: str = "global", group_id: str = "", remark: str = "") -> None:
        if kind not in {"black", "white"} or scope not in {"global", "group"}:
            raise ValueError("invalid access-list entry")
        group_id = group_id if scope == "group" else ""
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO access_list(qq,kind,scope,group_id,remark) VALUES(?,?,?,?,?) "
                "ON CONFLICT(qq,kind,scope,group_id) DO UPDATE SET remark=excluded.remark,created_at=CURRENT_TIMESTAMP",
                (qq, kind, scope, group_id, remark),
            )
            self.conn.execute("DELETE FROM access_list WHERE qq=? AND kind<>? AND scope=? AND group_id=?", (qq, kind, scope, group_id))

    def remove_entry(self, qq: str, kind: str, scope: str, group_id: str = "") -> None:
        with self.lock, self.conn:
            self.conn.execute(
                "DELETE FROM access_list WHERE qq=? AND kind=? AND scope=? AND group_id=?",
                (qq, kind, scope, group_id if scope == "group" else ""),
            )

    def entries(self) -> list[dict]:
        with self.lock:
            return [dict(x) for x in self.conn.execute("SELECT * FROM access_list ORDER BY created_at DESC").fetchall()]

    def status(self, qq: str, group_id: str) -> str | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT kind FROM access_list WHERE qq=? AND ((scope='group' AND group_id=?) OR scope='global') "
                "ORDER BY CASE scope WHEN 'group' THEN 0 ELSE 1 END LIMIT 1",
                (qq, group_id),
            ).fetchone()
        return row[0] if row else None

    def log(self, action: str, qq: str = "", group_id: str = "", detail: str = "") -> None:
        with self.lock, self.conn:
            self.conn.execute("INSERT INTO audit_log(action,qq,group_id,detail) VALUES(?,?,?,?)", (action, qq, group_id, detail))

    def logs(self, limit: int = 300) -> list[dict]:
        with self.lock:
            return [dict(x) for x in self.conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

