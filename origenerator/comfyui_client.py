import asyncio
import json
import logging
import urllib.parse
import urllib.request
import uuid

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


def comfyui_responding(host: str, port: int, timeout: float = 2.0) -> bool:
    """True only if the server at host:port is actually ComfyUI.

    A bare port check is not enough: another app can occupy the port and
    answer HTTP without being ComfyUI. ComfyUI's /system_stats returns a
    JSON object with a "system" key; anything else means "not ComfyUI".
    """
    url = f"http://{host}:{port}/system_stats"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except Exception:
        return False
    return isinstance(data, dict) and "system" in data


class ComfyUIClient(QThread):
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    job_queued = pyqtSignal(str)  # prompt_id
    progress = pyqtSignal(str, int, int)  # prompt_id, value, max
    node_executing = pyqtSignal(str, str)  # prompt_id, node_id
    job_completed = pyqtSignal(str, dict)  # prompt_id, history_data
    job_error = pyqtSignal(str, str)  # prompt_id, error_message
    queue_status = pyqtSignal(int)  # queue_remaining

    def __init__(self, host: str = "127.0.0.1", port: int = 8188, parent=None):
        super().__init__(parent)
        self.host = host
        self.port = port
        self.client_id = str(uuid.uuid4())
        self._running = False

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def ws_url(self) -> str:
        return f"ws://{self.host}:{self.port}/ws?clientId={self.client_id}"

    def run(self):
        self._running = True
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._ws_loop())

    async def _ws_loop(self):
        import websockets
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
            except Exception as e:
                logger.warning("WebSocket error: %s, reconnecting in 3s", e)
                self.disconnected.emit()
                if self._running:
                    await asyncio.sleep(3)

    def stop(self):
        self._running = False

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
                self._on_job_finished(prompt_id)
            else:
                self._on_node_executing(prompt_id, node_id)

        elif msg_type == "progress":
            self.progress.emit(
                data.get("prompt_id", ""),
                data.get("value", 0),
                data.get("max", 0),
            )

        elif msg_type == "execution_error":
            self.job_error.emit(
                data.get("prompt_id", ""),
                json.dumps(data),
            )

    def _on_node_executing(self, prompt_id: str, node_id: str):
        self.node_executing.emit(prompt_id, node_id)

    def _on_job_finished(self, prompt_id: str):
        try:
            history = self.fetch_history(prompt_id)
            self.job_completed.emit(prompt_id, history)
        except Exception as e:
            self.job_error.emit(prompt_id, str(e))

    def submit_job(self, workflow_payload: dict) -> str:
        result = self._post_prompt(workflow_payload)
        prompt_id = result["prompt_id"]
        self.job_queued.emit(prompt_id)
        return prompt_id

    def _post_prompt(self, workflow_payload: dict) -> dict:
        body = json.dumps({
            "prompt": workflow_payload,
            "client_id": self.client_id,
        }).encode()
        req = urllib.request.Request(
            f"{self.base_url}/prompt",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    def fetch_history(self, prompt_id: str) -> dict:
        url = f"{self.base_url}/history/{prompt_id}"
        with urllib.request.urlopen(url) as resp:
            data = json.loads(resp.read())
            return data.get(prompt_id, {})

    def fetch_output_file(self, filename: str, subfolder: str = "", folder_type: str = "output") -> bytes:
        params = urllib.parse.urlencode({
            "filename": filename,
            "subfolder": subfolder,
            "type": folder_type,
        })
        url = f"{self.base_url}/view?{params}"
        with urllib.request.urlopen(url) as resp:
            return resp.read()
