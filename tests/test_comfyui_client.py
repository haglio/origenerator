"""The websocket event pump, and what it emits.

The REST half's tests are tests/test_comfyui_api.py; what is left here is the
part that needs Qt -- the thread, the signals, and the message handlers that
turn a ComfyUI websocket frame into one.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
import json
import struct

from origenerator.comfyui_client import ComfyUIClient


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
