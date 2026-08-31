"""ComfyUI's websocket event pump, on a Qt thread.

Live progress, the executing node, preview frames and completion come back over
a websocket, and each is re-emitted as a Qt signal for the UI to connect to. The
loop reconnects on its own, and ``stop`` cancels whatever it is awaiting so the
process closing behind it exits at once.

The REST half is :mod:`origenerator.comfyui_api`, which needs no Qt at all;
:class:`ComfyUIClient` holds one and forwards every call, so a consumer that
already has a client is unaffected and one that needs only HTTP can take the api
instead.
"""

import asyncio
import json
import logging

from PyQt6.QtCore import QThread, pyqtSignal

# Re-exported: the api's module-scope surface reached this app through here for
# as long as there was only one module, and the gui package still imports two of
# these from this name.
from origenerator.comfyui_api import (  # noqa: F401
    _HTTP_TIMEOUT_S,
    _POLL_TIMEOUT_S,
    ComfyUIApi,
    ForeignQueue,
    comfyui_responding,
    format_prompt_error,
)

logger = logging.getLogger(__name__)

# ComfyUI binary websocket frames lead with a 4-byte big-endian event type.
_PREVIEW_IMAGE_EVENT = 1
# A preview frame's payload is then a 4-byte image-format tag followed by the
# encoded image, so the displayable bytes start at offset 8.
_PREVIEW_IMAGE_OFFSET = 8

class ComfyUIClient(QThread):
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    progress = pyqtSignal(str, int, int)  # prompt_id, value, max
    node_executing = pyqtSignal(str, str)  # prompt_id, node_id
    job_completed = pyqtSignal(str, dict)  # prompt_id, history_data
    job_error = pyqtSignal(str, str)  # prompt_id, error_message
    queue_status = pyqtSignal(int)  # queue_remaining
    preview_image = pyqtSignal(str, bytes)  # executing prompt_id, image bytes

    def __init__(self, host: str = "127.0.0.1", port: int = 8188,
                 client_id: str | None = None, parent=None):
        super().__init__(parent)
        # A stable client id is what lets a relaunch reconnect to a job still
        # running in ComfyUI: ComfyUI routes that job's progress, preview and
        # completion messages only to the websocket client id that submitted it, so
        # reusing the persisted id — rather than minting a fresh one each launch —
        # keeps those live updates flowing to the reconnected session. A fresh uuid
        # is minted when none is supplied (a read-only gallery, or a test).
        self.api = ComfyUIApi(host, port, client_id)
        self._running = False
        self._loop = None  # the thread's asyncio loop, for cross-thread wakeups
        self._task = None  # the running _ws_loop task, so stop() can cancel it
        # The prompt ComfyUI is currently executing, so preview frames (which
        # carry no id of their own) can be attributed to the right job.
        self._executing_prompt_id: str | None = None

    # --- what the api answers for ------------------------------------------
    #
    # Forwarded rather than reached through, because every consumer of a client
    # already spells these and there are seventeen call sites of them outside
    # this module. A consumer that wants only these should take a
    # :class:`~origenerator.comfyui_api.ComfyUIApi` instead of a client.

    host = property(lambda self: self.api.host)
    port = property(lambda self: self.api.port)
    client_id = property(lambda self: self.api.client_id)
    base_url = property(lambda self: self.api.base_url)

    def submit_job(self, workflow_payload: dict, prompt_id: str) -> str:
        return self.api.submit_job(workflow_payload, prompt_id)

    def interrupt(self):
        return self.api.interrupt()

    def cancel_prompt(self, prompt_id: str):
        return self.api.cancel_prompt(prompt_id)

    def cancel_prompts(self, prompt_ids):
        return self.api.cancel_prompts(prompt_ids)

    def fetch_history(self, prompt_id: str) -> dict:
        return self.api.fetch_history(prompt_id)

    def fetch_queue(self) -> set[str]:
        return self.api.fetch_queue()

    def fetch_running(self) -> set[str]:
        return self.api.fetch_running()

    def foreign_backlog(self, prompt_id: str) -> int | None:
        return self.api.foreign_backlog(prompt_id)

    def foreign_queue(self) -> ForeignQueue:
        return self.api.foreign_queue()

    def clear_foreign_queue(self) -> int:
        return self.api.clear_foreign_queue()

    # --- the websocket half -------------------------------------------------

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
        import websockets
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
            pass  # stop() cancelled the loop; unwind quietly so the thread ends

    def stop(self):
        """Stop the websocket loop and end the thread without delay.

        Flipping ``_running`` alone is not enough: the loop spends most of its
        time awaiting a websocket message or parked in the reconnect sleep, and
        would only notice the flag once that await returns (up to 3s later).
        Cancelling the task interrupts whatever it is awaiting right now, so the
        thread — and the process closing behind it — exits at once.
        """
        self._running = False
        loop, task = self._loop, self._task
        if loop is None or task is None:
            return
        try:
            loop.call_soon_threadsafe(task.cancel)
        except RuntimeError:
            pass  # loop already finished and closed — nothing left to interrupt

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
            # A progress event names the prompt currently executing. Adopt it as the
            # executing prompt so preview frames (which carry no id of their own)
            # attribute to the right job — in particular right after a reconnect,
            # where ComfyUI's replayed "executing" arrives with no prompt_id and so
            # can't set this itself.
            if prompt_id:
                self._executing_prompt_id = prompt_id
            self.progress.emit(prompt_id, data.get("value", 0), data.get("max", 0))

        elif msg_type == "execution_error":
            self.job_error.emit(
                data.get("prompt_id", ""),
                json.dumps(data),
            )

    def _handle_ws_binary(self, raw: bytes):
        """Emit ComfyUI live-preview frames, tagged with the executing prompt.

        Only preview-image frames are understood; any other binary event (and
        truncated frames) are ignored. The frame carries no prompt id, so it is
        attributed to whichever prompt is currently executing.
        """
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
