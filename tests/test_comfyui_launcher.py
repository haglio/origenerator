from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from origenerator import comfyui_launcher
from origenerator.comfyui_launcher import bring_up, ensure_comfyui_server
from origenerator.gui.loading_screen import LoadingCanceled

COMFYUI_DIR = Path("C:/x/ComfyUIApp/ComfyUI")


class _ComfyUIApp:
    def __init__(self, starting):
        self.starting = list(starting)

    def server_starting(self):
        return self.starting.pop(0) if len(self.starting) > 1 else self.starting[0]


def _bring_up(monkeypatch, app, answers):
    answers = list(answers)
    monkeypatch.setattr(comfyui_launcher, "load", lambda comfyui_dir: app)
    monkeypatch.setattr(comfyui_launcher, "comfyui_responding",
                        lambda host, port: answers.pop(0) if len(answers) > 1 else answers[0])
    started = MagicMock()
    monkeypatch.setattr(comfyui_launcher, "ensure_comfyui_server", started)
    waits = iter(range(50))

    def sleep(seconds):
        if next(waits, None) is None:
            raise AssertionError("still waiting after 50 looks")

    return bring_up(MagicMock(), "127.0.0.1", 8188, COMFYUI_DIR, sleep=sleep), started


def test_bringing_comfyui_up_waits_for_the_start_under_way_and_starts_nothing(monkeypatch):
    came_up, started = _bring_up(monkeypatch, _ComfyUIApp(starting=[True]),
                                 answers=[False, False, True])

    assert came_up is True
    started.assert_not_called()


def test_with_nothing_starting_it_comfyui_is_started_the_way_the_launch_starts_it(monkeypatch):
    came_up, started = _bring_up(monkeypatch, _ComfyUIApp(starting=[False, True]),
                                 answers=[False, False, True])

    assert came_up is True
    _logger, host, port, comfyui_dir = started.call_args.args
    assert (host, port, comfyui_dir) == ("127.0.0.1", 8188, COMFYUI_DIR)


def test_a_start_that_ends_without_comfyui_answering_is_given_up_on_at_once(monkeypatch):
    came_up, _started = _bring_up(monkeypatch, _ComfyUIApp(starting=[False]), answers=[False])

    assert came_up is False


def test_a_start_under_way_that_ends_without_comfyui_answering_is_given_up_on_then(monkeypatch):
    came_up, started = _bring_up(monkeypatch, _ComfyUIApp(starting=[True, True, False]),
                                 answers=[False])

    assert came_up is False
    started.assert_not_called()


def test_ensure_server_warns_when_port_held_by_non_comfyui():
    logger = MagicMock()
    with patch("origenerator.comfyui_launcher.comfyui_responding", return_value=False), \
         patch("socket.create_connection"), \
         patch("importlib.util.spec_from_file_location") as mock_spec:
        ensure_comfyui_server(logger, "127.0.0.1", 8188, COMFYUI_DIR)

    mock_spec.assert_not_called()
    assert logger.warning.called
    msg = logger.warning.call_args[0][0].lower()
    assert "occupied" in msg or "not comfyui" in msg


def test_ensure_server_noop_when_comfyui_already_responding():
    logger = MagicMock()
    with patch("origenerator.comfyui_launcher.comfyui_responding", return_value=True), \
         patch("importlib.util.spec_from_file_location") as mock_spec:
        ensure_comfyui_server(logger, "127.0.0.1", 8188, COMFYUI_DIR)

    mock_spec.assert_not_called()
    logger.warning.assert_not_called()


def test_ensure_server_forwards_status_and_pump_callbacks_to_launcher():
    logger = MagicMock()
    on_status = MagicMock()
    pump_events = MagicMock()
    fake_server = MagicMock()
    fake_server.start.return_value = MagicMock(started=True, pid=4321, error=None)

    with patch("origenerator.comfyui_launcher.comfyui_responding", return_value=False), \
         patch("socket.create_connection", side_effect=OSError), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("importlib.util.spec_from_file_location"), \
         patch("importlib.util.module_from_spec", return_value=fake_server):
        ensure_comfyui_server(
            logger, "127.0.0.1", 8188, COMFYUI_DIR,
            on_status=on_status, pump_events=pump_events,
        )

    fake_server.start.assert_called_once()
    kwargs = fake_server.start.call_args.kwargs
    assert kwargs["on_status"] is on_status
    assert kwargs["pump_events"] is pump_events


def test_a_loading_canceled_while_comfyui_starts_is_no_failure_to_start_it():
    fake_server = MagicMock()
    fake_server.start.side_effect = LoadingCanceled

    with patch("origenerator.comfyui_launcher.comfyui_responding", return_value=False), \
         patch("socket.create_connection", side_effect=OSError), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("importlib.util.spec_from_file_location"), \
         patch("importlib.util.module_from_spec", return_value=fake_server), \
         pytest.raises(LoadingCanceled):
        ensure_comfyui_server(MagicMock(), "127.0.0.1", 8188, COMFYUI_DIR)
