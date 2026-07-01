import json
import struct
import urllib.error
from unittest.mock import patch, MagicMock

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
    with qtbot.waitSignal(client.disconnected, timeout=3000):
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
