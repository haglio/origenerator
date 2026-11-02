from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from PyQt6.QtCore import QThread, pyqtSignal

from origenerator.comfyui_api import (  # noqa: F401
    _HTTP_TIMEOUT_S,
    _POLL_TIMEOUT_S,
    ComfyUIApi,
    ForeignQueue,
    comfyui_responding,
    format_prompt_error,
)
from origenerator.comfyui_inputs import ComfyFolders

logger = logging.getLogger(__name__)

# ComfyUI binary frames: 4-byte big-endian event type, then (preview) a 4-byte image-format tag, then the image.
_PREVIEW_IMAGE_EVENT = 1
_PREVIEW_IMAGE_OFFSET = 8
_WHAT_THREW_AND_WHERE = ("node_id", "node_type", "exception_type", "exception_message",
                         "traceback")

class ComfyUIClient(QThread):
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    progress = pyqtSignal(str, str, int, int)
    node_executing = pyqtSignal(str, str)
    job_completed = pyqtSignal(str, dict)
    job_error = pyqtSignal(str, str)
    queue_status = pyqtSignal(int)
    preview_image = pyqtSignal(str, bytes)

    def __init__(self, host: str = "127.0.0.1", port: int = 8188,
                 client_id: str | None = None, parent=None, *, folders: ComfyFolders):
        super().__init__(parent)
        # ComfyUI sends a job's messages only to the websocket client id that submitted it.
        self.api = ComfyUIApi(host, port, client_id, folders=folders)
        self._running = False
        self._loop = None
        self._task = None
        self._executing_prompt_id: str | None = None

    host = property(lambda self: self.api.host)
    port = property(lambda self: self.api.port)
    client_id = property(lambda self: self.api.client_id)
    base_url = property(lambda self: self.api.base_url)
    folders = property(lambda self: self.api.folders)

    def submit_job(self, workflow_payload: dict, prompt_id: str) -> str:
        return self.api.submit_job(workflow_payload, prompt_id)

    def interrupt(self, prompt_id: str | None = None):
        return self.api.interrupt(prompt_id)

    def free_memory(self):
        return self.api.free_memory()

    def cancel_prompt(self, prompt_id: str):
        return self.api.cancel_prompt(prompt_id)

    def cancel_prompts(self, prompt_ids):
        return self.api.cancel_prompts(prompt_ids)

    def fetch_history(self, prompt_id: str) -> dict:
        return self.api.fetch_history(prompt_id)

    def forget_history(self, prompt_id: str):
        return self.api.forget_history(prompt_id)

    def fetch_queue(self) -> set[str]:
        return self.api.fetch_queue()

    def executing_prompts(self) -> set[str]:
        return self.api.executing_prompts()

    def foreign_backlog(self, prompt_id: str) -> int | None:
        return self.api.foreign_backlog(prompt_id)

    def foreign_queue(self) -> ForeignQueue:
        return self.api.foreign_queue()

    def clear_foreign_queue(self) -> int:
        return self.api.clear_foreign_queue()

    @property
    def ws_url(self) -> str:
        return f"ws://{self.host}:{self.port}/ws?clientId={self.client_id}"

    def run(self):
        self._running = True
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._ws_loop())
        finally:
            loop.close()
            self._loop = None
            self._task = None

    async def _ws_loop(self):
        import websockets  # noqa: PLC0415 (optional: only a live server needs it)
        self._task = asyncio.current_task()
        try:
            while self._running:
                try:
                    async with websockets.connect(self.ws_url) as ws:
                        self.connected.emit()
                        logger.info("WebSocket connected to %s", self.ws_url)
                        async for message in ws:
                            if not self._running:
                                break
                            if isinstance(message, str):
                                self._handle_ws_message(message)
                            elif isinstance(message, (bytes, bytearray)):
                                self._handle_ws_binary(bytes(message))
                except Exception as e:
                    logger.warning("WebSocket error: %s, reconnecting in 3s", e)
                    self.disconnected.emit()
                    if self._running:
                        await asyncio.sleep(3)
        except asyncio.CancelledError:
            pass

    def stop(self):
        self._running = False
        loop, task = self._loop, self._task
        if loop is None or task is None:
            return
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(task.cancel)

    def _handle_ws_message(self, raw: str):
        msg = json.loads(raw)
        msg_type = msg.get("type")
        data = msg.get("data", {})

        if msg_type == "status":
            remaining = data.get("status", {}).get("exec_info", {}).get("queue_remaining", 0)
            self.queue_status.emit(remaining)

        elif msg_type == "executing":
            prompt_id = data.get("prompt_id", "")
            node_id = data.get("node")
            if node_id is None:
                self._executing_prompt_id = None
                self._on_job_finished(prompt_id)
            else:
                self._executing_prompt_id = prompt_id
                self._on_node_executing(prompt_id, node_id)

        elif msg_type == "progress":
            prompt_id = data.get("prompt_id", "")
            # After a reconnect ComfyUI's replayed "executing" has no prompt_id; a progress event names it.
            if prompt_id:
                self._executing_prompt_id = prompt_id
            # A reconnect mid-pass never sees the "executing" frame; ComfyUI names the node on every progress event.
            self.progress.emit(prompt_id, str(data.get("node") or ""),
                               data.get("value", 0), data.get("max", 0))

        elif msg_type == "execution_error":
            self.job_error.emit(
                data.get("prompt_id", ""),
                json.dumps({field: data[field] for field in _WHAT_THREW_AND_WHERE
                            if field in data}),
            )

    def _handle_ws_binary(self, raw: bytes):
        if len(raw) < _PREVIEW_IMAGE_OFFSET:
            return
        event = int.from_bytes(raw[0:4], "big")
        if event != _PREVIEW_IMAGE_EVENT:
            return
        self.preview_image.emit(
            self._executing_prompt_id or "", raw[_PREVIEW_IMAGE_OFFSET:]
        )

    def _on_node_executing(self, prompt_id: str, node_id: str):
        self.node_executing.emit(prompt_id, node_id)

    def _on_job_finished(self, prompt_id: str):
        try:
            history = self.fetch_history(prompt_id)
            self.job_completed.emit(prompt_id, history)
        except Exception as e:
            self.job_error.emit(prompt_id, str(e))
