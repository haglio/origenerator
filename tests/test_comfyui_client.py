import io
import json
import struct
import urllib.error
from unittest.mock import patch, MagicMock

import pytest

from origenerator.comfyui_client import ComfyUIClient, comfyui_responding


def test_stop_interrupts_reconnect_sleep_promptly(qtbot):
    """stop() must interrupt the reconnect backoff, not wait it out.

    The websocket loop parks in ``await asyncio.sleep(3)`` between reconnect
    attempts. If stop() only flips a flag, the thread (and the whole process)
    lingers for the rest of that sleep after the window has already closed, so
    a quick relaunch is swallowed by Windows while the dying instance still
    owns the taskbar identity. stop() must cancel the sleep so the thread ends
    at once.
    """
    client = ComfyUIClient(host="127.0.0.1", port=59999)  # nothing listening
    # Wait for the refused connect to drop the loop into its 3s reconnect sleep.
    # The refusal fires ``disconnected`` almost at once; the generous timeout is a
    # safety net for a cold QThread + asyncio + websockets spin-up under heavy load
    # (a full GUI suite plus sibling agents), not an expected wait.
    with qtbot.waitSignal(client.disconnected, timeout=15000):
        client.start()
    client.stop()
    assert client.wait(1000), "stop() did not end the thread within 1s"


def _mock_response(status: int, body: bytes):
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_submit_job_posts_our_prompt_id_and_returns_it():
    # Origenerator supplies its own prompt_id so ComfyUI keys this job's signals
    # and history on the same id the DB row uses (the basis for reconnecting).
    client = ComfyUIClient.__new__(ComfyUIClient)
    client.host = "127.0.0.1"
    client.port = 8188
    client.client_id = "test-client"

    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(
        {"prompt_id": "our-id", "number": 1}
    ).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        returned = client.submit_job({"1": {"class_type": "Test", "inputs": {}}}, "our-id")

    assert returned == "our-id"
    call_args = mock_urlopen.call_args[0][0]
    body = json.loads(call_args.data)
    assert body["client_id"] == "test-client"
    assert body["prompt_id"] == "our-id"
    assert "1" in body["prompt"]


def test_submit_job_surfaces_comfyui_node_validation_detail_on_400():
    # ComfyUI rejects an invalid prompt with 400 whose *body* names the failing
    # node and why (here: LoadImage's image doesn't resolve). urlopen raises
    # HTTPError, and str(HTTPError) is only "HTTP Error 400: Bad Request" — the
    # useful detail lives in its body. The client must read and surface it.
    client = ComfyUIClient.__new__(ComfyUIClient)
    client.host = "127.0.0.1"
    client.port = 8188
    client.client_id = "test-client"
    body = json.dumps({
        "error": {"message": "Prompt outputs failed validation"},
        "node_errors": {
            "12": {
                "class_type": "LoadImage",
                "errors": [{"details": "image - Invalid image file: foo.png"}],
            }
        },
    }).encode()
    err = urllib.error.HTTPError(
        "http://127.0.0.1:8188/prompt", 400, "Bad Request", {}, io.BytesIO(body)
    )
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(Exception) as excinfo:
            client.submit_job(
                {"12": {"class_type": "LoadImage", "inputs": {"image": "foo.png"}}},
                "our-id",
            )
    message = str(excinfo.value)
    assert "LoadImage" in message
    assert "Invalid image file: foo.png" in message
    assert "Bad Request" not in message  # the bare status is not what we surface


def test_format_prompt_error_falls_back_when_body_is_not_the_expected_json():
    # Not every non-2xx body is ComfyUI's node_errors JSON (a proxy may return
    # HTML, a body may be empty). The formatter must degrade gracefully.
    from origenerator.comfyui_client import format_prompt_error

    assert format_prompt_error("<html>502 Bad Gateway</html>") == "<html>502 Bad Gateway</html>"
    assert format_prompt_error("") == "Bad Request"
    assert format_prompt_error(
        json.dumps({"error": {"message": "Prompt has no outputs"}})
    ) == "Prompt has no outputs"


def test_fetch_queue_returns_running_and_pending_ids():
    client = ComfyUIClient.__new__(ComfyUIClient)
    client.host = "127.0.0.1"
    client.port = 8188
    body = json.dumps({
        "queue_running": [[0, "run-1", {}, {}, []]],
        "queue_pending": [[1, "pend-1", {}, {}, []], [2, "pend-2", {}, {}, []]],
    }).encode()

    with patch("urllib.request.urlopen", return_value=_mock_response(200, body)):
        ids = client.fetch_queue()

    assert ids == {"run-1", "pend-1", "pend-2"}


def test_fetch_running_returns_only_what_is_executing():
    # Telling the executing prompt from a merely queued one is what lets a
    # caller interrupt its own job without stopping someone else's.
    client = ComfyUIClient.__new__(ComfyUIClient)
    client.host = "127.0.0.1"
    client.port = 8188
    body = json.dumps({
        "queue_running": [[0, "run-1", {}, {}, []]],
        "queue_pending": [[1, "pend-1", {}, {}, []]],
    }).encode()

    with patch("urllib.request.urlopen", return_value=_mock_response(200, body)):
        ids = client.fetch_running()

    assert ids == {"run-1"}


def _queue_client(body: dict):
    """A bare client whose one /queue call answers with ``body``."""
    client = ComfyUIClient.__new__(ComfyUIClient)
    client.host = "127.0.0.1"
    client.port = 8188
    return client, patch("urllib.request.urlopen",
                         return_value=_mock_response(200, json.dumps(body).encode()))


def test_queue_backlog_counts_everything_ahead_whoever_queued_it():
    # The point of the number: ComfyUI is shared, so what's holding a submit up is
    # often another client's work this app can't otherwise see.
    client, urlopen = _queue_client({
        "queue_running": [[0, "someone-elses", {}, {}, []]],
        "queue_pending": [[1, "also-theirs", {}, {}, []], [2, "ours", {}, {}, []]],
    })
    with urlopen:
        assert client.queue_backlog("ours") == 2


def test_queue_backlog_orders_by_queue_number_not_list_position():
    # /queue returns pending items heap-ordered, so position in the list says
    # nothing about who runs first — only the queue number does.
    client, urlopen = _queue_client({
        "queue_running": [],
        "queue_pending": [[9, "later", {}, {}, []], [3, "ours", {}, {}, []],
                          [1, "sooner", {}, {}, []]],
    })
    with urlopen:
        assert client.queue_backlog("ours") == 1  # only "sooner" is really ahead


def test_queue_backlog_is_none_once_comfyui_starts_it():
    client, urlopen = _queue_client({
        "queue_running": [[0, "ours", {}, {}, []]],
        "queue_pending": [],
    })
    with urlopen:
        assert client.queue_backlog("ours") is None  # not waiting: it's executing


def test_queue_backlog_is_none_for_a_prompt_that_has_left_the_queue():
    client, urlopen = _queue_client({"queue_running": [], "queue_pending": []})
    with urlopen:
        assert client.queue_backlog("finished-or-never-there") is None


def test_queue_backlog_falls_back_to_what_is_executing_when_unnumbered():
    # A malformed entry with no queue number still yields the one thing that's
    # certainly ahead of it, rather than claiming nothing is.
    client, urlopen = _queue_client({
        "queue_running": [[0, "theirs", {}, {}, []]],
        "queue_pending": [["?", "ours", {}, {}, []]],
    })
    with urlopen:
        assert client.queue_backlog("ours") == 1


def test_parse_ws_executing_none_signals_completion():
    client = ComfyUIClient.__new__(ComfyUIClient)
    messages = []
    client._on_job_finished = lambda pid: messages.append(("finished", pid))
    client._on_node_executing = lambda pid, nid: messages.append(("exec", pid, nid))

    client._handle_ws_message(json.dumps({
        "type": "executing",
        "data": {"node": "5", "prompt_id": "p1"},
    }))
    client._handle_ws_message(json.dumps({
        "type": "executing",
        "data": {"node": None, "prompt_id": "p1"},
    }))

    assert messages == [("exec", "p1", "5"), ("finished", "p1")]


def test_executing_message_tracks_then_clears_current_prompt():
    # Preview frames arrive without a prompt_id, so the client tags them with
    # whichever prompt is currently executing.
    client = ComfyUIClient.__new__(ComfyUIClient)
    client._executing_prompt_id = None
    client._on_job_finished = lambda pid: None
    client._on_node_executing = lambda pid, nid: None

    client._handle_ws_message(json.dumps({
        "type": "executing", "data": {"node": "5", "prompt_id": "p1"},
    }))
    assert client._executing_prompt_id == "p1"

    client._handle_ws_message(json.dumps({
        "type": "executing", "data": {"node": None, "prompt_id": "p1"},
    }))
    assert client._executing_prompt_id is None


def test_progress_event_tags_the_executing_prompt_for_previews(qtbot):
    # After a reconnect, ComfyUI's replayed "executing" carries no prompt_id, so the
    # client can't learn the running job from it. A progress event does name the
    # prompt; the client adopts it as the executing prompt, so the live preview
    # frames that follow (which carry no id of their own) attribute to that job
    # instead of being dropped. Without this, a reconnected run shows no live frame.
    client = ComfyUIClient()
    client._executing_prompt_id = ""  # the empty tag the reconnect replay left behind

    client._handle_ws_message(json.dumps({
        "type": "progress", "data": {"prompt_id": "job1", "value": 3, "max": 10},
    }))

    assert client._executing_prompt_id == "job1"


def test_reuses_a_supplied_client_id(qtbot):
    # Persisting and reusing this id across launches is how a restart reconnects to a
    # job still running in ComfyUI, which targets that job's live websocket messages
    # at the id that submitted it. The id also rides the /ws query so ComfyUI routes
    # the running prompt's messages to this reconnecting socket.
    client = ComfyUIClient(client_id="stable-id")

    assert client.client_id == "stable-id"
    assert "clientId=stable-id" in client.ws_url


def test_mints_a_distinct_client_id_when_none_supplied(qtbot):
    # A read-only gallery or a test needs no persisted id; each gets its own.
    assert ComfyUIClient().client_id
    assert ComfyUIClient().client_id != ComfyUIClient().client_id


def test_binary_preview_emits_image_tagged_with_current_prompt(qtbot):
    client = ComfyUIClient()
    client._executing_prompt_id = "p1"
    received = []
    client.preview_image.connect(lambda pid, data: received.append((pid, data)))

    # ComfyUI frames: 4-byte event type (1 = preview), 4-byte image format, image.
    msg = struct.pack(">I", 1) + struct.pack(">I", 2) + b"PNG-BYTES"
    client._handle_ws_binary(msg)

    assert received == [("p1", b"PNG-BYTES")]


def test_binary_non_preview_event_is_ignored(qtbot):
    client = ComfyUIClient()
    client._executing_prompt_id = "p1"
    received = []
    client.preview_image.connect(lambda pid, data: received.append((pid, data)))

    client._handle_ws_binary(struct.pack(">I", 3) + b"not-an-image")

    assert received == []


def test_interrupt_posts_to_interrupt_endpoint():
    client = ComfyUIClient.__new__(ComfyUIClient)
    client.host = "127.0.0.1"
    client.port = 8188
    with patch("urllib.request.urlopen", return_value=_mock_response(200, b"")) as m:
        client.interrupt()
    req = m.call_args[0][0]
    assert req.full_url == "http://127.0.0.1:8188/interrupt"
    assert req.data == b""  # a body forces a POST


def test_cancel_prompt_deletes_from_queue():
    client = ComfyUIClient.__new__(ComfyUIClient)
    client.host = "127.0.0.1"
    client.port = 8188
    with patch("urllib.request.urlopen", return_value=_mock_response(200, b"{}")) as m:
        client.cancel_prompt("comfy-X")
    req = m.call_args[0][0]
    assert req.full_url == "http://127.0.0.1:8188/queue"
    assert json.loads(req.data) == {"delete": ["comfy-X"]}


def test_every_http_call_carries_a_timeout():
    # Without a timeout, a wedged or swap-thrashed ComfyUI hangs the calling
    # thread forever: the GUI thread on a submit/cancel (the app freezes), or the
    # websocket thread on a history fetch (no job ever completes again). Every
    # HTTP helper must therefore pass one.
    client = ComfyUIClient.__new__(ComfyUIClient)
    client.host = "127.0.0.1"
    client.port = 8188
    client.client_id = "test-client"
    body = json.dumps({"pid": {}, "queue_running": [], "queue_pending": []}).encode()
    calls = [
        lambda: client.submit_job({"1": {"class_type": "T", "inputs": {}}}, "pid"),
        client.interrupt,
        lambda: client.cancel_prompt("pid"),
        lambda: client.fetch_history("pid"),
        client.fetch_queue,
        lambda: client.fetch_output_file("out.png"),
    ]
    for call in calls:
        with patch("urllib.request.urlopen", return_value=_mock_response(200, body)) as m:
            call()
        assert m.call_args.kwargs.get("timeout"), f"{call} passed no timeout"


def test_comfyui_responding_true_for_comfyui_system_stats():
    body = json.dumps({"system": {"os": "nt"}, "devices": []}).encode()
    with patch("urllib.request.urlopen", return_value=_mock_response(200, body)):
        assert comfyui_responding("127.0.0.1", 8188) is True


def test_comfyui_responding_false_when_endpoint_404s():
    # Another app (e.g. a NiceGUI server) occupies the port and 404s.
    err = urllib.error.HTTPError("http://x/system_stats", 404, "Not Found", {}, None)
    with patch("urllib.request.urlopen", side_effect=err):
        assert comfyui_responding("127.0.0.1", 8188) is False


def test_comfyui_responding_false_for_200_that_is_not_comfyui():
    # A different JSON server answering 200 must not be mistaken for ComfyUI.
    body = json.dumps({"message": "hello"}).encode()
    with patch("urllib.request.urlopen", return_value=_mock_response(200, body)):
        assert comfyui_responding("127.0.0.1", 8188) is False
