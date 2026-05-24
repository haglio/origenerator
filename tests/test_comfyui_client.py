import json
import urllib.error
from unittest.mock import patch, MagicMock

from origenerator.comfyui_client import ComfyUIClient, comfyui_responding


def _mock_response(status: int, body: bytes):
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_submit_job_posts_correct_payload():
    client = ComfyUIClient.__new__(ComfyUIClient)
    client.host = "127.0.0.1"
    client.port = 8188
    client.client_id = "test-client"

    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(
        {"prompt_id": "resp-uuid", "number": 1}
    ).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        result = client._post_prompt({"1": {"class_type": "Test", "inputs": {}}})

    assert result["prompt_id"] == "resp-uuid"
    call_args = mock_urlopen.call_args[0][0]
    body = json.loads(call_args.data)
    assert body["client_id"] == "test-client"
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
