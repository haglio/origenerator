"""ComfyUI's REST surface: everything this app asks the server over HTTP.

Qt-free on purpose, and that is the whole point of it being its own module. It
used to live on ``ComfyUIClient``, which is a ``QThread`` running a websocket
event pump -- so every consumer of the eleven calls below needed Qt, including
the ones whose own docstrings claim not to: ``completion`` says it is kept
"Qt-free so the reconciler can use it without a running UI", and ``inflight``
and ``base_backfill`` are pure, yet all three took a client that could only be a
thread.

``ComfyUIClient`` holds one of these and forwards every one of its methods, so
nothing that already has a client had to change. What is new is that a unit
needing only the HTTP half can declare THIS, and be handed one -- or a stub --
with no Qt anywhere.

The websocket half stays where it must: it emits Qt signals from a thread.
"""
import json
import logging
import urllib.error
import urllib.request
import uuid
from typing import NamedTuple

logger = logging.getLogger(__name__)

# Every HTTP call to ComfyUI carries this timeout. Without one, a wedged or
# swap-thrashed server hangs the calling thread forever — the GUI thread for a
# submit/cancel (the whole app freezes), or the websocket thread for a history
# fetch (no job ever completes again). Generous, because a busy server that IS
# answering can legitimately take a while; it's a socket-inactivity limit, not a
# total-transfer one, so even a large /view download streams fine under it.
_HTTP_TIMEOUT_S = 30.0

# Queue reads the GUI repeats on its poll timer get a much tighter deadline. They
# run on the GUI thread every couple of seconds, so a wedged server under the
# generous limit above would freeze the window for half a minute at a time; under
# this one it costs a skipped reading.
_POLL_TIMEOUT_S = 2.0


class ForeignQueue(NamedTuple):
    """What clients other than this one have on ComfyUI's queue right now.

    ``running`` is what ComfyUI is executing for them (at most one), ``pending``
    what waits behind it. Split because they're cleared differently: a pending
    prompt is deleted out of the queue, while the executing one can only be
    interrupted.
    """

    running: list[str]
    pending: list[str]

    @property
    def total(self) -> int:
        return len(self.running) + len(self.pending)


def format_prompt_error(body: str) -> str:
    """Turn ComfyUI's 400 ``/prompt`` body into a one-line, human-readable reason.

    A rejected prompt returns JSON with ``node_errors`` — per failing node, its
    ``class_type`` and one or more ``errors`` whose ``details`` say what's wrong
    (e.g. ``LoadImage: image - Invalid image file: foo.png``). That detail is
    what makes a 400 actionable; ``urllib``'s own ``HTTPError`` string throws it
    away as a bare "Bad Request". Falls back to the top-level ``error`` message,
    then to the raw body, when the shape isn't the expected one.
    """
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return body.strip() or "Bad Request"
    if not isinstance(data, dict):
        return body.strip() or "Bad Request"
    parts = []
    for node_id, info in (data.get("node_errors") or {}).items():
        label = info.get("class_type") or f"node {node_id}"
        for err in info.get("errors") or []:
            detail = err.get("details") or err.get("message") or ""
            parts.append(f"{label}: {detail}" if detail else label)
    if parts:
        return "; ".join(parts)
    error = data.get("error") or {}
    reason = ": ".join(p for p in (error.get("message"), error.get("details")) if p)
    return reason or body.strip() or "Bad Request"


def _queue_prompt_id(item):
    """The prompt id of a ``/queue`` entry — element 1 of its tuple — or ``None``."""
    if isinstance(item, (list, tuple)) and len(item) > 1:
        return item[1]
    return None


def _queue_number(item):
    """A ``/queue`` entry's queue number (element 0), which orders execution."""
    if isinstance(item, (list, tuple)) and item and isinstance(item[0], (int, float)):
        return item[0]
    return None


def _queue_client_id(item):
    """Which websocket client submitted a ``/queue`` entry, from its extra_data."""
    extra = item[3] if isinstance(item, (list, tuple)) and len(item) > 3 else None
    return extra.get("client_id") if isinstance(extra, dict) else None


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


class ComfyUIApi:
    """The eleven HTTP calls, over nothing but urllib.

    *client_id* is what ComfyUI routes a job's websocket messages to and what
    tells this app's queue entries from another client's; a fresh uuid is minted
    when none is given (a read-only gallery, or a test).
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8188,
                 client_id: str | None = None):
        self.host = host
        self.port = port
        self.client_id = client_id or str(uuid.uuid4())

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def submit_job(self, workflow_payload: dict, prompt_id: str) -> str:
        """Queue a prompt on ComfyUI under our own ``prompt_id``.

        ComfyUI honors a caller-supplied ``prompt_id`` (minting its own only when
        none is given), so passing ours makes its websocket signals and its
        ``/history`` entry for this job key on the same id the DB row uses. That
        one shared id is what lets a job be matched live and, after a restart,
        reconnected to. Returns the id for symmetry; it always equals ``prompt_id``.
        """
        self._post_prompt(workflow_payload, prompt_id)
        return prompt_id

    def interrupt(self):
        """Stop the prompt ComfyUI is currently executing."""
        req = urllib.request.Request(
            f"{self.base_url}/interrupt",
            data=b"",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
            resp.read()

    def cancel_prompt(self, prompt_id: str):
        """Remove a still-queued prompt so it never starts executing."""
        self.cancel_prompts([prompt_id])

    def cancel_prompts(self, prompt_ids):
        """Remove several still-queued prompts at once.

        ``/queue`` takes a list, so clearing a backlog is one round trip rather
        than one per job — which matters when the caller is the GUI thread and
        the backlog is a whole batch of another app's experiments.
        """
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
            # ComfyUI explains a rejected prompt in the response body (which node
            # and why); HTTPError's own string is only "Bad Request". Surface the
            # body so the failure is actionable rather than opaque.
            detail = e.read().decode("utf-8", "replace")
            raise RuntimeError(format_prompt_error(detail)) from e

    def fetch_history(self, prompt_id: str) -> dict:
        url = f"{self.base_url}/history/{prompt_id}"
        with urllib.request.urlopen(url, timeout=_HTTP_TIMEOUT_S) as resp:
            data = json.loads(resp.read())
            return data.get(prompt_id, {})

    def fetch_queue(self) -> set[str]:
        """The prompt ids ComfyUI is currently running or has pending.

        Used at startup to tell a job still in flight from one that has gone.
        """
        return self._queue_ids("queue_running", "queue_pending")

    def fetch_running(self) -> set[str]:
        """Just the prompt ids ComfyUI is executing right now.

        :meth:`interrupt` stops whatever is executing, whoever submitted it — so
        a caller that wants to stop its own job checks this first.
        """
        return self._queue_ids("queue_running")

    def foreign_backlog(self, prompt_id: str) -> int | None:
        """How many prompts from *other* clients ComfyUI will run before ``prompt_id``.

        The user's own jobs ahead of it deliberately don't count: those are things
        they asked for, the first of them is on screen being generated, and calling
        that a wait "in ComfyUI" turns their own queue into a phantom they go
        hunting for. What's worth reporting is work this app didn't launch —
        another Origenerator instance, another app on the same server — which they
        can neither see here nor cancel. ``None`` when the prompt isn't queued at
        all: ComfyUI is executing it already, or it has left the queue.
        """
        data = self._fetch_queue_data(timeout=_POLL_TIMEOUT_S)
        pending = data.get("queue_pending", [])
        mine = next((it for it in pending if _queue_prompt_id(it) == prompt_id), None)
        if mine is None:
            return None
        running = data.get("queue_running", [])
        number = _queue_number(mine)
        if number is None:
            ahead = list(running)  # unnumbered: all that's certain is what's executing
        else:
            # Pending entries come back heap-ordered rather than run-ordered, so a
            # position in the list says nothing — the queue number is what orders them.
            ahead = list(running) + [
                it for it in pending
                if (n := _queue_number(it)) is not None and n < number
            ]
        return sum(1 for it in ahead if _queue_client_id(it) != self.client_id)

    def foreign_queue(self) -> ForeignQueue:
        """Everything on ComfyUI's queue that this app did not submit.

        ComfyUI is a shared server that outlives whatever queued on it, so its
        queue can be full of work no window here accounts for — another
        Origenerator instance, a branch preview whose background experiments
        outlived it, another app entirely. Until it's read, the first sign of it
        is a fresh Generate landing behind a pile of jobs the user never asked
        for. Reading it lets a surface say so beforehand, and
        :meth:`clear_foreign_queue` is what gets rid of it.
        """
        data = self._fetch_queue_data(timeout=_POLL_TIMEOUT_S)
        return ForeignQueue(running=self._their_ids(data, "queue_running"),
                            pending=self._their_ids(data, "queue_pending"))

    def clear_foreign_queue(self) -> int:
        """Drop another app's work off ComfyUI, and report how much went.

        This app's own jobs are never touched: those are what the user asked
        for, and they're visible and cancellable here already. Pending ones go
        by deletion; one already executing can only be stopped by ``/interrupt``,
        which stops whatever is running *now* — so what's executing is re-read
        after the deletion and interrupted only if it's still one of theirs,
        rather than a job of ours that has since started.
        """
        foreign = self.foreign_queue()
        if not foreign.total:
            return 0
        if foreign.pending:
            self.cancel_prompts(foreign.pending)
        theirs_still_running = self.fetch_running() & set(foreign.running)
        if theirs_still_running:
            self.interrupt()
        return len(foreign.pending) + len(theirs_still_running)

    def _their_ids(self, data: dict, section: str) -> list[str]:
        """The prompt ids in a ``/queue`` section some other client submitted.

        We only ever recognize our own id, so an entry with none — a client that
        didn't identify itself — counts as someone else's rather than ours.
        """
        return [
            pid for item in data.get(section, [])
            if (pid := _queue_prompt_id(item)) is not None
            and _queue_client_id(item) != self.client_id
        ]

    def _queue_ids(self, *sections: str) -> set[str]:
        """The prompt ids in the named ``/queue`` sections."""
        data = self._fetch_queue_data()
        return {
            pid for key in sections for item in data.get(key, [])
            if (pid := _queue_prompt_id(item)) is not None
        }

    def _fetch_queue_data(self, timeout: float = _HTTP_TIMEOUT_S) -> dict:
        """``/queue`` as ``{queue_running: [...], queue_pending: [...]}``, each
        entry a tuple of ``(number, prompt_id, prompt, ...)``. Callers that read
        it on the GUI's poll timer pass the shorter ``_POLL_TIMEOUT_S``."""
        url = f"{self.base_url}/queue"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
