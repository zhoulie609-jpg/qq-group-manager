from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .db import Database
from .service import GLOBAL_BLACK_RE, ManagerService


def data_dir() -> Path:
    root = Path(os.getenv("APPDATA", Path.home())) / "QQGroupManager"
    root.mkdir(parents=True, exist_ok=True)
    return root


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("QQ群管机器人")
        self.geometry("1080x720")
        self.minsize(900, 600)
        self.db = Database(data_dir() / "manager.db")
        self.ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.service = ManagerService(self.db, self.notify, self.schedule_refresh)
        self.member_counts: dict[str, str] = {}
        self._build()
        self.after(100, self._drain_ui)
        self.refresh_all()

    def _build(self):
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")
        ttk.Label(top, text="QQ群管机器人", font=("Microsoft YaHei UI", 18, "bold")).pack(side="left")
        self.status_var = tk.StringVar(value="未连接")
        ttk.Label(top, textvariable=self.status_var).pack(side="right")

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._groups_tab()
        self._lists_tab()
        self._audit_tab()
        self._settings_tab()

    def _groups_tab(self):
        frame = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(frame, text="首页")
        bar = ttk.Frame(frame)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="同步群列表", command=self.sync_groups).pack(side="left")
        ttk.Button(bar, text="刷新人数", command=self.refresh_counts).pack(side="left", padx=8)
        ttk.Button(bar, text="启用/停用", command=self.toggle_group).pack(side="left")
        self.group_tree = ttk.Treeview(frame, columns=("enabled", "id", "name", "count"), show="headings")
        for col, title, width in (("enabled", "管理", 70), ("id", "群号", 160), ("name", "群名称", 360), ("count", "人数", 90)):
            self.group_tree.heading(col, text=title); self.group_tree.column(col, width=width)
        self.group_tree.pack(fill="both", expand=True)

    def _lists_tab(self):
        frame = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(frame, text="插件")
        plugin_box = ttk.LabelFrame(frame, text="插件管理", padding=10)
        plugin_box.pack(fill="x", pady=(0, 12))
        self.plugin_state_var = tk.StringVar()
        self._refresh_plugin_state()
        ttk.Label(plugin_box, text="全局黑名单", font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        ttk.Label(plugin_box, text="作者：QQGroupManager　版本：1.0.0　说明：全局黑白名单、入群审核、跨群移除").pack(side="left", padx=20)
        ttk.Label(plugin_box, textvariable=self.plugin_state_var).pack(side="right", padx=8)
        ttk.Button(plugin_box, text="启用", command=lambda: self.set_plugin_enabled(True)).pack(side="right", padx=3)
        ttk.Button(plugin_box, text="禁用", command=lambda: self.set_plugin_enabled(False)).pack(side="right", padx=3)
        ttk.Button(plugin_box, text="重载", command=self.reload_plugin).pack(side="right", padx=3)
        command_bar = ttk.Frame(frame)
        command_bar.pack(fill="x", pady=(0, 10))
        ttk.Label(command_bar, text="快捷指令").pack(side="left")
        self.command_var = tk.StringVar()
        command_entry = ttk.Entry(command_bar, textvariable=self.command_var, width=28)
        command_entry.pack(side="left", padx=8)
        command_entry.bind("<Return>", lambda _event: self.run_quick_command())
        ttk.Button(command_bar, text="执行", command=self.run_quick_command).pack(side="left")
        ttk.Label(command_bar, text="输入 QQ号T，例如 123456789T：全局拉黑并从所有已启用群移除", foreground="#555").pack(side="left", padx=10)
        form = ttk.Frame(frame); form.pack(fill="x", pady=(0, 8))
        self.qq_var, self.remark_var = tk.StringVar(), tk.StringVar()
        self.kind_var, self.scope_var, self.list_group_var = tk.StringVar(value="black"), tk.StringVar(value="global"), tk.StringVar()
        for label, widget in (
            ("QQ号", ttk.Entry(form, textvariable=self.qq_var, width=16)),
            ("类型", ttk.Combobox(form, textvariable=self.kind_var, values=("black", "white"), width=9, state="readonly")),
            ("范围", ttk.Combobox(form, textvariable=self.scope_var, values=("global", "group"), width=9, state="readonly")),
            ("群号", ttk.Entry(form, textvariable=self.list_group_var, width=14)),
            ("备注", ttk.Entry(form, textvariable=self.remark_var, width=28)),
        ):
            ttk.Label(form, text=label).pack(side="left", padx=(0, 3)); widget.pack(side="left", padx=(0, 8))
        ttk.Button(form, text="添加", command=self.add_entry).pack(side="left")
        ttk.Button(form, text="移除", command=self.remove_entry).pack(side="left", padx=6)
        self.list_tree = ttk.Treeview(frame, columns=("qq", "kind", "scope", "group", "remark", "time"), show="headings")
        for col, title, width in (("qq", "QQ号", 130), ("kind", "名单", 80), ("scope", "范围", 80), ("group", "群号", 130), ("remark", "备注", 350), ("time", "时间", 150)):
            self.list_tree.heading(col, text=title); self.list_tree.column(col, width=width)
        self.list_tree.pack(fill="both", expand=True)

    def _audit_tab(self):
        frame = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(frame, text="日志")
        bar = ttk.Frame(frame); bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="通过选中申请", command=lambda: self.review(True)).pack(side="left")
        ttk.Button(bar, text="拒绝选中申请", command=lambda: self.review(False)).pack(side="left", padx=8)
        self.log_tree = ttk.Treeview(frame, columns=("time", "action", "qq", "group", "detail"), show="headings")
        for col, title, width in (("time", "时间", 150), ("action", "动作", 130), ("qq", "QQ号", 120), ("group", "群号", 120), ("detail", "详情", 430)):
            self.log_tree.heading(col, text=title); self.log_tree.column(col, width=width)
        self.log_tree.pack(fill="both", expand=True)

    def _settings_tab(self):
        frame = ttk.Frame(self.tabs, padding=18)
        self.tabs.add(frame, text="账号与设置")
        self.ws_var = tk.StringVar(value=self.db.get_setting("ws_url", "ws://127.0.0.1:3001"))
        self.token_var = tk.StringVar(value=self.db.get_setting("token", ""))
        self.admins_var = tk.StringVar(value=self.db.get_setting("admin_qqs", ""))
        self.reject_var = tk.StringVar(value=self.db.get_setting("reject_reason", "该账号在黑名单中，已自动拒绝"))
        self.napcat_var = tk.StringVar(value=self.db.get_setting("napcat_path", ""))
        fields = [("OneBot WebSocket", self.ws_var), ("Access Token", self.token_var), ("管理员 QQ（逗号分隔）", self.admins_var), ("黑名单拒绝备注", self.reject_var), ("NapCat 启动程序", self.napcat_var)]
        for row, (label, var) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=7)
            ttk.Entry(frame, textvariable=var, width=70, show="*" if "Token" in label else "").grid(row=row, column=1, sticky="ew", padx=10)
        frame.columnconfigure(1, weight=1)
        ttk.Button(frame, text="选择 NapCat", command=self.pick_napcat).grid(row=4, column=2)
        buttons = ttk.Frame(frame); buttons.grid(row=5, column=1, sticky="w", pady=15)
        ttk.Button(buttons, text="保存并连接", command=self.save_connect).pack(side="left")
        ttk.Button(buttons, text="启动 NapCat / 扫码登录", command=self.launch_napcat).pack(side="left", padx=8)
        ttk.Label(frame, text="安全提示：只有这里配置的管理员 QQ 才能使用“QQ号T”全局拉黑指令。\n扫码和登录态由 NapCat/QQ 处理，本程序不读取或保存 QQ 密码。", foreground="#555").grid(row=6, column=0, columnspan=3, sticky="w")

    def notify(self, text: str): self.ui_queue.put(("status", text))
    def schedule_refresh(self): self.ui_queue.put(("refresh", None))

    def _drain_ui(self):
        try:
            while True:
                kind, value = self.ui_queue.get_nowait()
                if kind == "status": self.status_var.set(str(value))
                elif kind == "refresh": self.refresh_all()
        except queue.Empty:
            pass
        self.after(100, self._drain_ui)

    def refresh_all(self):
        self._fill(self.group_tree, [("是" if g["enabled"] else "否", g["group_id"], g["group_name"], self.member_counts.get(g["group_id"], "—")) for g in self.db.groups()], key=1)
        self._fill(self.list_tree, [(e["qq"], e["kind"], e["scope"], e["group_id"], e["remark"], e["created_at"]) for e in self.db.entries()])
        self._fill(self.log_tree, [(e["created_at"], e["action"], e["qq"], e["group_id"], e["detail"]) for e in self.db.logs()])

    @staticmethod
    def _fill(tree, rows, key=None):
        tree.delete(*tree.get_children())
        for row in rows: tree.insert("", "end", iid=str(row[key]) if key is not None else None, values=row)

    def save_connect(self):
        for key, var in (("ws_url", self.ws_var), ("token", self.token_var), ("admin_qqs", self.admins_var), ("reject_reason", self.reject_var), ("napcat_path", self.napcat_var)):
            self.db.set_setting(key, var.get().strip())
        self.service.client.connect(self.ws_var.get(), self.token_var.get())

    def sync_groups(self): self._background(self._sync_groups)
    def _sync_groups(self): self.service.sync_groups(); self.schedule_refresh(); self.notify("群列表同步完成")

    def refresh_counts(self): self._background(self._refresh_counts)
    def _refresh_counts(self):
        for g in self.db.groups(enabled_only=True):
            try: self.member_counts[g["group_id"]] = str(self.service.group_member_count(g["group_id"]))
            except Exception as exc: self.member_counts[g["group_id"]] = f"错误: {exc}"
            self.schedule_refresh()
        self.notify("群人数刷新完成")

    def toggle_group(self):
        selected = self.group_tree.selection()
        if not selected: return
        gid = selected[0]; current = self.group_tree.item(gid, "values")[0] == "是"
        self.db.set_group_enabled(gid, not current); self.refresh_all()

    def add_entry(self):
        qq = self.qq_var.get().strip()
        if not qq.isdigit(): return messagebox.showerror("输入错误", "QQ号必须为数字")
        scope, gid = self.scope_var.get(), self.list_group_var.get().strip()
        if scope == "group" and not gid.isdigit(): return messagebox.showerror("输入错误", "群范围必须填写群号")
        if self.kind_var.get() == "black" and scope == "global":
            self.service.global_blacklist(qq, self.remark_var.get().strip() or "前端人工添加", kick=True)
        else:
            self.db.add_entry(qq, self.kind_var.get(), scope, gid, self.remark_var.get().strip()); self.refresh_all()

    def run_quick_command(self):
        raw = self.command_var.get()
        match = GLOBAL_BLACK_RE.fullmatch(raw)
        if not match:
            return messagebox.showerror("指令错误", "格式应为 QQ号T，例如：123456789T")
        qq = match.group(1)
        if not messagebox.askyesno("确认全局拉黑", f"将 {qq} 加入全局黑名单，并尝试从所有已启用群移除？"):
            return
        self.service.global_blacklist(qq, "桌面前端快捷指令添加", kick=True)
        self.command_var.set("")
        messagebox.showinfo("完成", f"{qq} 已加入全局黑名单")

    def remove_entry(self):
        selected = self.list_tree.selection()
        if not selected: return
        values = self.list_tree.item(selected[0], "values")
        self.db.remove_entry(values[0], values[1], values[2], values[3]); self.refresh_all()

    def _refresh_plugin_state(self):
        enabled = self.db.get_setting("blacklist_plugin_enabled", "1") == "1"
        self.plugin_state_var.set("● 已启用" if enabled else "○ 已禁用")

    def set_plugin_enabled(self, enabled: bool):
        self.db.set_setting("blacklist_plugin_enabled", "1" if enabled else "0")
        self._refresh_plugin_state()
        self.db.log("启用插件" if enabled else "禁用插件", detail="全局黑名单")
        self.refresh_all()

    def reload_plugin(self):
        self.db.log("重载插件", detail="全局黑名单")
        self.refresh_all()
        messagebox.showinfo("插件", "全局黑名单插件已重载")

    def review(self, approve: bool):
        selected = self.log_tree.selection()
        if not selected: return
        values = self.log_tree.item(selected[0], "values")
        if values[1] != "待人工审核": return messagebox.showinfo("提示", "请选择“待人工审核”记录")
        parts = str(values[4]).split("|", 2)
        if len(parts) < 2: return
        flag, subtype = parts[0].removeprefix("flag="), parts[1].removeprefix("sub_type=")
        params = {"flag": flag, "sub_type": subtype, "approve": approve}
        if not approve: params["reason"] = self.reject_var.get()
        self.service.client.call_async("set_group_add_request", params)
        self.db.log("人工通过" if approve else "人工拒绝", values[2], values[3], values[4]); self.refresh_all()

    def pick_napcat(self):
        path = filedialog.askopenfilename(filetypes=[("Windows 程序", "*.exe"), ("所有文件", "*.*")])
        if path: self.napcat_var.set(path)

    def launch_napcat(self):
        path = self.napcat_var.get().strip()
        if not path or not Path(path).exists(): return messagebox.showerror("未配置", "请先选择 NapCat 启动程序")
        try: subprocess.Popen([path], cwd=str(Path(path).parent))
        except Exception as exc: return messagebox.showerror("启动失败", str(exc))
        messagebox.showinfo("已启动", "请在 NapCat/QQ 弹出的窗口中扫码登录，再点击“保存并连接”。")

    def _background(self, fn):
        def run():
            try: fn()
            except Exception as exc: self.notify(f"操作失败: {exc}")
        threading.Thread(target=run, daemon=True).start()

    def destroy(self):
        self.service.client.disconnect(); super().destroy()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
