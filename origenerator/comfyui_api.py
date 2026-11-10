from __future__ import annotations

import http.client
import json
import logging
import time
import urllib.error
import urllib.request
import uuid
from typing import NamedTuple

from origenerator.comfyui_inputs import ComfyFolders, within_reach

logger = logging.getLogger(__name__)

# A busy ComfyUI that is answering can take a while. urllib's timeout limits a silence on the
# socket, never the whole transfer, so ComfyUI streams a large download under it.
_HTTP_TIMEOUT_S = 30.0

_POLL_TIMEOUT_S = 2.0

# ComfyUI validates a prompt on its event loop after logging it and answers nothing meanwhile.
# Validating one two-scene video took it fifty seconds.
# ComfyUI still runs a prompt whose POST answer nobody waited for.
_ACCEPTANCE_WAIT_S = 120.0
# ComfyUI takes the POST before any ask, and the prompt can still be landing in its queue when it first answers one.
_ACCEPTANCE_GRACE_S = 15.0
_ACCEPTANCE_POLL_S = 3.0
# A stalled ComfyUI answers no ask at all, however long each one waits.
_ACCEPTANCE_READ_TIMEOUT_S = 10.0


class ForeignQueue(NamedTuple):
    running: list[str]
    pending: list[str]

    @property
    def total(self) -> int:
        return len(self.running) + len(self.pending)


def format_prompt_error(body: str) -> str:
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return body.strip() or "Bad Request"
    if not isinstance(data, dict):
        return body.strip() or "Bad Request"
    parts = [_node_refusal(info.get("class_type") or f"node {node_id}", err)
             for node_id, info in (data.get("node_errors") or {}).items()
             for err in info.get("errors") or []]
    if parts:
        return "; ".join(parts)
    error = data.get("error") or {}
    reason = ": ".join(p for p in (error.get("message"), error.get("details")) if p)
    return reason or body.strip() or "Bad Request"


def _node_refusal(node: str, error: dict) -> str:
    missing = (error.get("extra_info") or {}).get("received_value")
    if error.get("type") == "value_not_in_list" and missing is not None:
        return f"{node} can't find {missing}"
    detail = error.get("details") or error.get("message") or ""
    return f"{node}: {detail}" if detail else node


def format_execution_error(message: str) -> str:
    try:
        data = json.loads(message)
    except (json.JSONDecodeError, TypeError):
        data = None
    if not isinstance(data, dict):
        return (message or "").strip() or "The run failed."
    lines = (data.get("exception_message") or "").strip().splitlines()
    first = lines[0].strip() if lines else ""
    node = data.get("node_type") or data.get("node_id")
    if node and first:
        return f"{node} failed: {first}"
    return first or (f"{node} failed." if node else "The run failed.")


def _timed_out(error: BaseException) -> bool:
    # CPython's urllib: a read that times out raises TimeoutError; a connect that does wraps one in URLError
    if isinstance(error, TimeoutError):
        return True
    return isinstance(error, urllib.error.URLError) and isinstance(error.reason, TimeoutError)


def unreachable(error: BaseException) -> bool:
    return isinstance(error, urllib.error.URLError) and isinstance(error.reason, ConnectionRefusedError)


def _queue_prompt_id(item):
    if isinstance(item, (list, tuple)) and len(item) > 1:
        return item[1]
    return None


def _queue_number(item):
    if isinstance(item, (list, tuple)) and item and isinstance(item[0], (int, float)):
        return item[0]
    return None


_EXTRA_DATA_AT = 3


def _queue_client_id(item):
    extra = item[_EXTRA_DATA_AT] if isinstance(item, (list, tuple)) and len(item) > _EXTRA_DATA_AT else None
    return extra.get("client_id") if isinstance(extra, dict) else None


def comfyui_responding(host: str, port: int, timeout: float = 2.0) -> bool:
    url = f"http://{host}:{port}/system_stats"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except (OSError, ValueError, http.client.HTTPException):
        return False
    return isinstance(data, dict) and "system" in data


class _RealClock:
    def __call__(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class ComfyUIApi:
    def __init__(self, host: str = "127.0.0.1", port: int = 8188,
                 client_id: str | None = None, *, folders: ComfyFolders,
                 clock=None):
        self.host = host
        self.port = port
        self.client_id = client_id or str(uuid.uuid4())
        self.folders = folders
        clock = clock or _RealClock()
        self._clock = clock
        self._sleep = clock.sleep

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def submit_job(self, workflow_payload: dict, prompt_id: str) -> str:
        # ComfyUI honors a caller-supplied prompt_id, so its websocket signals and /history key on ours
        workflow_payload = within_reach(workflow_payload, self.folders)
        try:
            self._post_prompt(workflow_payload, prompt_id)
        except Exception as e:
            if not _timed_out(e):
                raise
            if not self._await_acceptance(prompt_id):
                raise RuntimeError(
                    "ComfyUI took too long to answer the submit and never listed the prompt"
                ) from e
            logger.info("Submit of %s was answered late; ComfyUI lists it", prompt_id)
        return prompt_id

    def _await_acceptance(self, prompt_id: str) -> bool:
        deadline = self._clock() + _ACCEPTANCE_WAIT_S
        absent_since = None
        while True:
            try:
                if self._lists_prompt(prompt_id):
                    return True
                absent_since = absent_since if absent_since is not None else self._clock()
            except Exception as e:
                logger.debug("Still waiting on ComfyUI to list %s: %s", prompt_id, e)
            now = self._clock()
            if now >= deadline:
                return False
            if absent_since is not None and now - absent_since >= _ACCEPTANCE_GRACE_S:
                return False
            self._sleep(_ACCEPTANCE_POLL_S)

    def _lists_prompt(self, prompt_id: str) -> bool:
        data = self._fetch_queue_data(timeout=_ACCEPTANCE_READ_TIMEOUT_S)
        queued = {
            pid for key in ("queue_running", "queue_pending") for item in data.get(key, [])
            if (pid := _queue_prompt_id(item)) is not None
        }
        if prompt_id in queued:
            return True
        return bool(self._history_entry(prompt_id, timeout=_ACCEPTANCE_READ_TIMEOUT_S))

    def interrupt(self, prompt_id: str | None = None):
        # ComfyUI takes its interrupt as a POST, and urllib sends one only for a request with a body.
        body = json.dumps({"prompt_id": prompt_id}).encode() if prompt_id else b""
        req = urllib.request.Request(
            f"{self.base_url}/interrupt",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
            resp.read()

    def free_memory(self):
        # ComfyUI keeps the last run's models loaded; this flag is acted on before its next prompt
        body = json.dumps({"unload_models": True, "free_memory": True}).encode()
        req = urllib.request.Request(
            f"{self.base_url}/free",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
            resp.read()

    def cancel_prompt(self, prompt_id: str):
        self.cancel_prompts([prompt_id])

    def cancel_prompts(self, prompt_ids):
        body = json.dumps({"delete": list(prompt_ids)}).encode()
        req = urllib.request.Request(
            f"{self.base_url}/queue",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
            resp.read()

    def _post_prompt(self, workflow_payload: dict, prompt_id: str) -> dict:
        body = json.dumps({
            "prompt": workflow_payload,
            "client_id": self.client_id,
            "prompt_id": prompt_id,
        }).encode()
        req = urllib.request.Request(
            f"{self.base_url}/prompt",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            # ComfyUI says which node refused a prompt and why in the response body, which urllib's
            # own HTTPError string leaves out as a bare "Bad Request".
            detail = e.read().decode("utf-8", "replace")
            raise RuntimeError(format_prompt_error(detail)) from e

    def fetch_history(self, prompt_id: str) -> dict:
        return self._history_entry(prompt_id, timeout=_HTTP_TIMEOUT_S)

    def forget_history(self, prompt_id: str):
        body = json.dumps({"delete": [prompt_id]}).encode()
        req = urllib.request.Request(
            f"{self.base_url}/history",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
            resp.read()

    def _history_entry(self, prompt_id: str, timeout: float) -> dict:
        url = f"{self.base_url}/history/{prompt_id}"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read())
            return data.get(prompt_id, {})

    def fetch_queue(self) -> set[str]:
        return self._queue_ids("queue_running", "queue_pending")

    def executing_prompts(self) -> set[str]:
        return self._queue_ids("queue_running", timeout=_POLL_TIMEOUT_S)

    def foreign_backlog(self, prompt_id: str) -> int | None:
        data = self._fetch_queue_data(timeout=_POLL_TIMEOUT_S)
        pending = data.get("queue_pending", [])
        mine = next((it for it in pending if _queue_prompt_id(it) == prompt_id), None)
        if mine is None:
            return None
        running = data.get("queue_running", [])
        number = _queue_number(mine)
        if number is None:
            ahead = list(running)
        else:
            # ComfyUI returns pending entries heap-ordered; the queue number orders them
            ahead = list(running) + [
                it for it in pending
                if (n := _queue_number(it)) is not None and n < number
            ]
        return sum(1 for it in ahead if _queue_client_id(it) != self.client_id)

    def foreign_queue(self) -> ForeignQueue:
        data = self._fetch_queue_data(timeout=_POLL_TIMEOUT_S)
        return ForeignQueue(running=self._their_ids(data, "queue_running"),
                            pending=self._their_ids(data, "queue_pending"))

    def clear_foreign_queue(self) -> int:
        foreign = self.foreign_queue()
        if foreign.pending:
            self.cancel_prompts(foreign.pending)
        for prompt_id in foreign.running:
            self.interrupt(prompt_id)
        return foreign.total

    def _their_ids(self, data: dict, section: str) -> list[str]:
        return [
            pid for item in data.get(section, [])
            if (pid := _queue_prompt_id(item)) is not None
            and _queue_client_id(item) != self.client_id
        ]

    def _queue_ids(self, *sections: str, timeout: float = _HTTP_TIMEOUT_S) -> set[str]:
        data = self._fetch_queue_data(timeout=timeout)
        return {
            pid for key in sections for item in data.get(key, [])
            if (pid := _queue_prompt_id(item)) is not None
        }

    def _fetch_queue_data(self, timeout: float = _HTTP_TIMEOUT_S) -> dict:
        url = f"{self.base_url}/queue"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
