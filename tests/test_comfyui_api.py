"""ComfyUI's REST surface, exercised without a Qt thread in sight.

These were always transport tests, and they used to reach the transport by
building a `ComfyUIClient` through ``__new__`` and setting three attributes on it
by hand -- because the real constructor is a ``QThread``'s, and every consumer of
the HTTP half was made to carry Qt with it. The HTTP half is its own object now
(:mod:`origenerator.comfyui_api`), so each of these constructs one. The websocket
half's tests stay in tests/test_comfyui_client.py.

Every call is mocked at urllib: nothing here touches the network.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from origenerator.comfyui_api import ComfyUIApi, comfyui_responding, format_prompt_error


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
    client = ComfyUIApi(client_id="test-client")

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
    client = ComfyUIApi(client_id="test-client")
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
    with patch("urllib.request.urlopen", side_effect=err), pytest.raises(Exception) as excinfo:
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
    assert format_prompt_error("<html>502 Bad Gateway</html>") == "<html>502 Bad Gateway</html>"
    assert format_prompt_error("") == "Bad Request"
    assert format_prompt_error(
        json.dumps({"error": {"message": "Prompt has no outputs"}})
    ) == "Prompt has no outputs"

def test_fetch_queue_returns_running_and_pending_ids():
    client = ComfyUIApi()
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
    client = ComfyUIApi()
    body = json.dumps({
        "queue_running": [[0, "run-1", {}, {}, []]],
        "queue_pending": [[1, "pend-1", {}, {}, []]],
    }).encode()

    with patch("urllib.request.urlopen", return_value=_mock_response(200, body)):
        ids = client.fetch_running()

    assert ids == {"run-1"}

def _queue_client(body: dict, client_id="ours-client"):
    """A bare client, with its own id, whose one /queue call answers with ``body``."""
    client = ComfyUIApi(client_id=client_id)
    return client, patch("urllib.request.urlopen",
                         return_value=_mock_response(200, json.dumps(body).encode()))

def _entry(number, prompt_id, client_id):
    return [number, prompt_id, {}, {"client_id": client_id}, []]

def test_foreign_backlog_counts_only_another_apps_work():
    # The user's own jobs ahead are things they asked for and can see; another
    # client's are the ones this app can neither show nor stop.
    client, urlopen = _queue_client({
        "queue_running": [_entry(0, "theirs", "some-other-app")],
        "queue_pending": [_entry(1, "also-theirs", "some-other-app"),
                          _entry(2, "ours", "ours-client")],
    })
    with urlopen:
        assert client.foreign_backlog("ours") == 2

def test_our_own_queue_is_not_a_foreign_wait():
    # The reported confusion: three of his own jobs read as "waiting in ComfyUI",
    # sending him hunting for phantom jobs that were his.
    client, urlopen = _queue_client({
        "queue_running": [_entry(0, "mine-running", "ours-client")],
        "queue_pending": [_entry(1, "mine-next", "ours-client"),
                          _entry(2, "ours", "ours-client")],
    })
    with urlopen:
        assert client.foreign_backlog("ours") == 0

def test_foreign_backlog_orders_by_queue_number_not_list_position():
    # /queue returns pending items heap-ordered, so position in the list says
    # nothing about who runs first — only the queue number does.
    client, urlopen = _queue_client({
        "queue_running": [],
        "queue_pending": [_entry(9, "later", "some-other-app"),
                          _entry(3, "ours", "ours-client"),
                          _entry(1, "sooner", "some-other-app")],
    })
    with urlopen:
        assert client.foreign_backlog("ours") == 1  # only "sooner" is really ahead

def test_foreign_backlog_is_none_once_comfyui_starts_it():
    client, urlopen = _queue_client({
        "queue_running": [_entry(0, "ours", "ours-client")],
        "queue_pending": [],
    })
    with urlopen:
        assert client.foreign_backlog("ours") is None  # not waiting: it's executing

def test_foreign_backlog_is_none_for_a_prompt_that_has_left_the_queue():
    client, urlopen = _queue_client({"queue_running": [], "queue_pending": []})
    with urlopen:
        assert client.foreign_backlog("finished-or-never-there") is None

def test_foreign_backlog_falls_back_to_what_is_executing_when_unnumbered():
    # A malformed entry with no queue number still yields the one thing that's
    # certainly ahead of it, rather than claiming nothing is.
    client, urlopen = _queue_client({
        "queue_running": [_entry(0, "theirs", "some-other-app")],
        "queue_pending": [_entry("?", "ours", "ours-client")],
    })
    with urlopen:
        assert client.foreign_backlog("ours") == 1

def test_an_entry_with_no_client_id_counts_as_someone_elses():
    # We only ever recognize our own id; anything unattributable isn't ours.
    client, urlopen = _queue_client({
        "queue_running": [[0, "mystery", {}, {}, []]],
        "queue_pending": [_entry(1, "ours", "ours-client")],
    })
    with urlopen:
        assert client.foreign_backlog("ours") == 1

def test_foreign_queue_separates_theirs_running_from_theirs_pending():
    # Split because they're cleared differently: pending ones are deleted out of
    # the queue, the executing one can only be interrupted.
    client, urlopen = _queue_client({
        "queue_running": [_entry(0, "theirs-running", "some-other-app")],
        "queue_pending": [_entry(1, "theirs-next", "some-other-app"),
                          _entry(2, "ours", "ours-client"),
                          _entry(3, "theirs-later", "some-other-app")],
    })
    with urlopen:
        foreign = client.foreign_queue()

    assert foreign.running == ["theirs-running"]
    assert foreign.pending == ["theirs-next", "theirs-later"]  # never "ours"
    assert foreign.total == 3

def test_foreign_queue_is_empty_when_the_queue_is_all_ours():
    client, urlopen = _queue_client({
        "queue_running": [_entry(0, "mine-running", "ours-client")],
        "queue_pending": [_entry(1, "mine-next", "ours-client")],
    })
    with urlopen:
        assert client.foreign_queue().total == 0

def test_clear_foreign_queue_drops_theirs_and_interrupts_the_one_running():
    # The reported mess: a batch of background experiments from a branch preview
    # sitting on the shared server, in nobody's ledger, in the way of every
    # Generate. Deleting the pending ones alone would leave the one mid-render
    # holding the GPU, so what's executing is stopped too.
    client = ComfyUIApi(client_id="ours-client")
    queue = {
        "queue_running": [_entry(0, "theirs-running", "some-other-app")],
        "queue_pending": [_entry(1, "theirs-a", "some-other-app"),
                          _entry(2, "ours", "ours-client"),
                          _entry(3, "theirs-b", "some-other-app")],
    }
    posted = []

    def fake_urlopen(req, **kwargs):
        # A body — even the empty one /interrupt posts — marks a write, not a read.
        if not isinstance(req, str) and req.data is not None:
            posted.append((req.full_url, req.data))
            return _mock_response(200, b"{}")
        return _mock_response(200, json.dumps(queue).encode())

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        dropped = client.clear_foreign_queue()

    assert dropped == 3  # two pending of theirs, plus the one they had running
    deletes = [json.loads(d) for u, d in posted if u.endswith("/queue")]
    assert deletes == [{"delete": ["theirs-a", "theirs-b"]}]  # one call, never "ours"
    assert [u for u, _ in posted if u.endswith("/interrupt")]

def test_clear_foreign_queue_leaves_our_own_running_job_alone():
    # /interrupt stops whatever is executing right now, so between reading the
    # queue and calling it their job can have finished and ours have started.
    # Re-reading first is what keeps a clear from killing the user's own run.
    client = ComfyUIApi(client_id="ours-client")
    states = [
        {"queue_running": [_entry(0, "theirs-running", "some-other-app")],
         "queue_pending": [_entry(1, "theirs-a", "some-other-app")]},
        {"queue_running": [_entry(2, "ours", "ours-client")], "queue_pending": []},
    ]
    posted = []

    def fake_urlopen(req, **kwargs):
        if not isinstance(req, str) and req.data is not None:
            posted.append(req.full_url)
            return _mock_response(200, b"{}")
        state = states.pop(0) if len(states) > 1 else states[0]
        return _mock_response(200, json.dumps(state).encode())

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        dropped = client.clear_foreign_queue()

    assert dropped == 1  # only the pending one they had; nothing was interrupted
    assert not [u for u in posted if u.endswith("/interrupt")]

def test_clear_foreign_queue_touches_nothing_when_the_queue_is_all_ours():
    client, urlopen = _queue_client({
        "queue_running": [_entry(0, "mine", "ours-client")],
        "queue_pending": [_entry(1, "mine-next", "ours-client")],
    })
    with urlopen as m:
        assert client.clear_foreign_queue() == 0
    assert not [c for c in m.call_args_list if getattr(c[0][0], "data", None)]

def test_cancel_prompts_deletes_a_whole_backlog_in_one_call():
    # One round trip, not one per job — the caller is the GUI thread and the
    # backlog can be another app's whole batch.
    client = ComfyUIApi()
    with patch("urllib.request.urlopen", return_value=_mock_response(200, b"{}")) as m:
        client.cancel_prompts(["a", "b", "c"])

    assert m.call_count == 1
    assert json.loads(m.call_args[0][0].data) == {"delete": ["a", "b", "c"]}

def test_queue_reads_on_the_poll_path_use_the_short_timeout():
    # These run on the GUI thread every couple of seconds. Under the generous
    # _HTTP_TIMEOUT_S a wedged server would freeze the window half a minute at a
    # time; the shorter deadline costs a skipped reading instead.
    from origenerator.comfyui_client import _HTTP_TIMEOUT_S, _POLL_TIMEOUT_S

    assert _POLL_TIMEOUT_S < _HTTP_TIMEOUT_S
    client, urlopen = _queue_client({"queue_running": [], "queue_pending": []})
    for call in (client.foreign_queue, lambda: client.foreign_backlog("x")):
        with urlopen as m:
            call()
        assert m.call_args.kwargs.get("timeout") == _POLL_TIMEOUT_S

def test_interrupt_posts_to_interrupt_endpoint():
    client = ComfyUIApi()
    with patch("urllib.request.urlopen", return_value=_mock_response(200, b"")) as m:
        client.interrupt()
    req = m.call_args[0][0]
    assert req.full_url == "http://127.0.0.1:8188/interrupt"
    assert req.data == b""  # a body forces a POST

def test_cancel_prompt_deletes_from_queue():
    client = ComfyUIApi()
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
    client = ComfyUIApi(client_id="test-client")
    body = json.dumps({"pid": {}, "queue_running": [], "queue_pending": []}).encode()
    calls = [
        lambda: client.submit_job({"1": {"class_type": "T", "inputs": {}}}, "pid"),
        client.interrupt,
        lambda: client.cancel_prompt("pid"),
        lambda: client.fetch_history("pid"),
        client.fetch_queue,
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


# --- a submit the server answered too late ----------------------------------------

def _answering(*answers):
    """A urlopen that works through ``answers`` in order -- each a response to
    return or an exception to raise -- and repeats the last one after."""
    answers = list(answers)

    def urlopen(req, timeout=None):
        answer = answers.pop(0) if len(answers) > 1 else answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    return patch("urllib.request.urlopen", side_effect=urlopen)


def _by_url(**bodies):
    """A urlopen that times out on the POST and answers each GET by the last
    path segment of its URL (``queue``, ``history``) with the body named for it."""

    def urlopen(req, timeout=None):
        if not isinstance(req, str):
            raise TimeoutError("timed out")  # the POST
        return _mock_response(200, json.dumps(bodies[req.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
                                                     if "/history/" not in req else "history"]).encode())

    return patch("urllib.request.urlopen", side_effect=urlopen)


def _fake_clock():
    """``time.sleep`` and ``time.monotonic`` on one clock that only sleeps advance."""
    now = [0.0]
    sleep = patch("origenerator.comfyui_api.time.sleep", side_effect=lambda s: now.__setitem__(0, now[0] + s))
    mono = patch("origenerator.comfyui_api.time.monotonic", side_effect=lambda: now[0])
    return now, sleep, mono


def test_a_submit_answered_too_late_stands_once_comfyui_lists_the_prompt():
    # ComfyUI logs "got prompt" as the request lands and validates it on its
    # event loop; a validation that takes a minute (2026-09-05: 50 s for a
    # two-scene clip whose one-scene twin took a tenth of one) answers nothing
    # meanwhile, so the POST times out on a prompt the server has and goes on
    # to run. Declared failed, that job ran untracked and its clip never reached
    # the gallery. So a submit whose answer is late asks whether the prompt is
    # listed before it gives up -- and asks again while the same stall swallows
    # the reads.
    client = ComfyUIApi(client_id="ours-client")
    listed = json.dumps({"queue_running": [_entry(1, "our-id", "ours-client")],
                         "queue_pending": []}).encode()
    now, sleep, mono = _fake_clock()
    with _answering(TimeoutError("timed out"), TimeoutError("timed out"),
                    _mock_response(200, listed)), sleep, mono:
        assert client.submit_job({"1": {"class_type": "Test", "inputs": {}}}, "our-id") == "our-id"
    assert now[0] > 0  # it waited between asks rather than hammering a stalled server


def test_a_submit_answered_too_late_stands_once_the_prompt_is_in_history():
    # A short prompt can be finished by the time the server answers again: it is
    # gone from the queue and in /history, and that is the same acceptance.
    client = ComfyUIApi(client_id="ours-client")
    now, sleep, mono = _fake_clock()
    with _by_url(queue={"queue_running": [], "queue_pending": []},
                 history={"our-id": {"outputs": {}, "status": {"completed": True}}}), sleep, mono:
        assert client.submit_job({"1": {"class_type": "Test", "inputs": {}}}, "our-id") == "our-id"


def test_a_submit_the_server_answers_without_the_prompt_fails_after_a_grace_period():
    # Once the server is answering and does not list the prompt, the POST it
    # took first gets a little longer to land, and then the submit is what it
    # looks like: not taken. Well short of the whole wait, so a real refusal
    # is not a two-minute freeze.
    client = ComfyUIApi(client_id="ours-client")
    now, sleep, mono = _fake_clock()
    with _by_url(queue={"queue_running": [], "queue_pending": []}, history={}), sleep, mono, \
            pytest.raises(RuntimeError, match="never listed"):
        client.submit_job({"1": {"class_type": "Test", "inputs": {}}}, "our-id")
    assert 10 <= now[0] < 60


def test_a_submit_the_server_never_answers_fails_at_the_end_of_the_wait():
    client = ComfyUIApi(client_id="ours-client")
    now, sleep, mono = _fake_clock()
    with _answering(TimeoutError("timed out")), sleep, mono, \
            pytest.raises(RuntimeError, match="never listed"):
        client.submit_job({"1": {"class_type": "Test", "inputs": {}}}, "our-id")
    assert 100 <= now[0] <= 130


def test_a_submit_refused_outright_is_not_waited_on():
    # A connection refused is a server that is not there; nothing to ask.
    client = ComfyUIApi(client_id="ours-client")
    refused = urllib.error.URLError(ConnectionRefusedError(111, "refused"))
    with _answering(refused), patch("origenerator.comfyui_api.time.sleep") as sleep, \
            pytest.raises(urllib.error.URLError):
        client.submit_job({"1": {"class_type": "Test", "inputs": {}}}, "our-id")
    assert not sleep.called
