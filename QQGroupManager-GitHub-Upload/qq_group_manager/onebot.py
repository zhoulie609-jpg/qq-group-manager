from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from typing import Callable

import websocket


class OneBotClient:
    def __init__(self, on_event: Callable[[dict], None], on_status: Callable[[str], None]):
        self.on_event = on_event
        self.on_status = on_status
        self.ws: websocket.WebSocketApp | None = None
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.pending: dict[str, queue.Queue] = {}
        self.pending_lock = threading.Lock()
        self.url = ""
        self.token = ""

    @property
    def connected(self) -> bool:
        return bool(self.ws and self.ws.sock and self.ws.sock.connected)

    def connect(self, url: str, token: str = "") -> None:
        self.disconnect()
        self.url, self.token = url.strip(), token.strip()
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def disconnect(self) -> None:
        self.stop_event.set()
        if self.ws:
            self.ws.close()
        self.ws = None

    def _run_loop(self) -> None:
        while not self.stop_event.is_set():
            headers = [f"Authorization: Bearer {self.token}"] if self.token else []
            self.ws = websocket.WebSocketApp(
                self.url,
                header=headers,
                on_open=lambda _ws: self.on_status("已连接"),
                on_message=self._on_message,
                on_error=lambda _ws, err: self.on_status(f"连接错误: {err}"),
                on_close=lambda _ws, _code, _msg: self.on_status("未连接"),
            )
            self.ws.run_forever(ping_interval=25, ping_timeout=10)
            if not self.stop_event.wait(3):
                self.on_status("正在重连…")

    def _on_message(self, _ws, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        echo = data.get("echo")
        if echo:
            with self.pending_lock:
                waiter = self.pending.pop(str(echo), None)
            if waiter:
                waiter.put(data)
                return
        if data.get("post_type"):
            self.on_event(data)

    def call(self, action: str, params: dict | None = None, timeout: float = 12) -> object:
        if not self.connected or not self.ws:
            raise ConnectionError("OneBot 尚未连接")
        echo = uuid.uuid4().hex
        waiter: queue.Queue = queue.Queue(maxsize=1)
        with self.pending_lock:
            self.pending[echo] = waiter
        self.ws.send(json.dumps({"action": action, "params": params or {}, "echo": echo}, ensure_ascii=False))
        try:
            response = waiter.get(timeout=timeout)
        except queue.Empty as exc:
            with self.pending_lock:
                self.pending.pop(echo, None)
            raise TimeoutError(f"OneBot 调用超时: {action}") from exc
        if response.get("status") != "ok" or response.get("retcode", 0) != 0:
            raise RuntimeError(response.get("wording") or response.get("message") or f"调用失败: {action}")
        return response.get("data")

    def call_async(self, action: str, params: dict | None = None) -> None:
        def run():
            try:
                self.call(action, params)
            except Exception as exc:
                self.on_status(f"操作失败: {exc}")
        threading.Thread(target=run, daemon=True).start()

