from __future__ import annotations

import json
import struct

from origenerator.comfyui_api import ComfyUIApi
from origenerator.comfyui_client import ComfyUIClient
from origenerator.comfyui_inputs import ComfyFolders
from origenerator.output_places import OutputPlaces
from tests.comfyui_folders import SUITE_FOLDERS


def test_stop_interrupts_reconnect_sleep_promptly(qtbot):
    client = ComfyUIClient(host="127.0.0.1", port=59999, folders=SUITE_FOLDERS)
    cold_start_under_load_ms = 15000
    with qtbot.waitSignal(client.disconnected, timeout=cold_start_under_load_ms):
        client.start()
    client.stop()
    # Windows swallows a quick relaunch while the closing instance still owns the taskbar identity.
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
    client = ComfyUIClient(folders=SUITE_FOLDERS)
    left_by_a_reconnect = ""
    client._executing_prompt_id = left_by_a_reconnect

    client._handle_ws_message(json.dumps({
        "type": "progress", "data": {"prompt_id": "job1", "value": 3, "max": 10},
    }))

    assert client._executing_prompt_id == "job1"

def test_progress_carries_the_node_that_took_the_step(qtbot):
    client = ComfyUIClient(folders=SUITE_FOLDERS)
    seen = []
    client.progress.connect(lambda *args: seen.append(args))

    client._handle_ws_message(json.dumps({
        "type": "progress",
        "data": {"prompt_id": "job1", "node": "24", "value": 3, "max": 50},
    }))
    client._handle_ws_message(json.dumps({
        "type": "progress", "data": {"prompt_id": "job1", "value": 4, "max": 50},
    }))

    assert seen == [("job1", "24", 3, 50), ("job1", "", 4, 50)]

def test_a_failed_run_arrives_saying_what_threw_and_nothing_its_node_was_given(qtbot):
    client = ComfyUIClient(folders=SUITE_FOLDERS)
    seen = []
    client.job_error.connect(lambda pid, message: seen.append((pid, json.loads(message))))

    client._handle_ws_message(json.dumps({"type": "execution_error", "data": {
        "prompt_id": "job1", "node_id": "6", "node_type": "CLIPTextEncode",
        "executed": ["4"], "exception_message": "example failure",
        "exception_type": "RuntimeError", "traceback": ['  File "nodes.py", line 1'],
        "current_inputs": {"text": ["gamma form, an example scene unfolds"]},
        "current_outputs": ["4"],
    }}))

    assert seen == [("job1", {
        "node_id": "6", "node_type": "CLIPTextEncode",
        "exception_message": "example failure", "exception_type": "RuntimeError",
        "traceback": ['  File "nodes.py", line 1'],
    })]

def test_reuses_a_supplied_client_id(qtbot):
    client = ComfyUIClient(client_id="stable-id", folders=SUITE_FOLDERS)

    assert client.client_id == "stable-id"
    assert "clientId=stable-id" in client.ws_url

def test_mints_a_distinct_client_id_when_none_supplied(qtbot):
    assert ComfyUIClient(folders=SUITE_FOLDERS).client_id
    assert ComfyUIClient(folders=SUITE_FOLDERS).client_id != ComfyUIClient(folders=SUITE_FOLDERS).client_id

def test_binary_preview_emits_image_tagged_with_current_prompt(qtbot):
    client = ComfyUIClient(folders=SUITE_FOLDERS)
    client._executing_prompt_id = "p1"
    received = []
    client.preview_image.connect(lambda pid, data: received.append((pid, data)))

    msg = struct.pack(">I", 1) + struct.pack(">I", 2) + b"PNG-BYTES"
    client._handle_ws_binary(msg)

    assert received == [("p1", b"PNG-BYTES")]

def test_binary_non_preview_event_is_ignored(qtbot):
    client = ComfyUIClient(folders=SUITE_FOLDERS)
    client._executing_prompt_id = "p1"
    received = []
    client.preview_image.connect(lambda pid, data: received.append((pid, data)))

    client._handle_ws_binary(struct.pack(">I", 3) + b"not-an-image")

    assert received == []


def test_a_binary_frame_too_short_to_hold_a_preview_is_ignored(qtbot):
    client = ComfyUIClient(folders=SUITE_FOLDERS)
    client._executing_prompt_id = "p1"
    received = []
    client.preview_image.connect(lambda pid, data: received.append((pid, data)))

    client._handle_ws_binary(struct.pack(">I", 1) + b"abc")

    assert received == []


def test_the_client_hands_its_folders_to_the_api(qtbot, tmp_path):
    folders = ComfyFolders(input=tmp_path / "input", places=OutputPlaces.in_one_folder(tmp_path / "output"),
                           temp=tmp_path / "temp")

    client = ComfyUIClient(folders=folders)

    assert client.api.folders == folders


def test_the_client_forwards_every_rest_call():
    rest_calls = {name for name, attr in vars(ComfyUIApi).items()
                  if callable(attr) and not name.startswith("_")}

    assert rest_calls <= set(vars(ComfyUIClient)), (
        "every caller that holds a client already makes these calls on it")
