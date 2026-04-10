import json
from unittest.mock import patch, MagicMock

from origenerator.comfyui_client import ComfyUIClient


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
