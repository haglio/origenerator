from __future__ import annotations

import json
from pathlib import Path

import pytest

from origenerator.site_chrome import (
    PORT_FILE,
    ChromeRefused,
    DevTools,
    SiteChrome,
    SitePage,
    chrome_here,
    command_line,
)


class FakeConnection:
    def __init__(self, answer=lambda method, params: {}, *, first=()):
        self._answer = answer
        self._waiting = list(first)
        self.asked: list[tuple[str, dict]] = []
        self.closed = False

    def send(self, text: str) -> None:
        sent = json.loads(text)
        self.asked.append((sent["method"], sent["params"]))
        try:
            self._waiting.append({"id": sent["id"],
                                  "result": self._answer(sent["method"], sent["params"])})
        except ChromeRefused as refused:
            self._waiting.append({"id": sent["id"], "error": {"message": str(refused)}})

    def recv(self) -> str:
        return json.dumps(self._waiting.pop(0))

    def close(self) -> None:
        self.closed = True


def test_an_answer_is_the_one_to_what_was_asked_whatever_the_chrome_says_first():
    connection = FakeConnection(lambda method, params: {"frameId": "made-up"},
                                first=[{"method": "Page.frameNavigated", "params": {}}])

    assert DevTools(connection).ask("Page.navigate", url="https://example.com/") == {
        "frameId": "made-up"}
    assert connection.asked == [("Page.navigate", {"url": "https://example.com/"})]


def test_what_the_chrome_refuses_is_raised_with_what_was_asked():
    def refuse(method, params):
        raise ChromeRefused("no such page")

    with pytest.raises(ChromeRefused, match=r"Page\.navigate: no such page"):
        DevTools(FakeConnection(refuse)).ask("Page.navigate", url="https://example.com/")


def _page(evaluated):
    connection = FakeConnection(
        lambda method, params: evaluated(params) if method == "Runtime.evaluate" else {})
    return SitePage(DevTools(connection)), connection


def test_a_page_reads_what_an_expression_comes_to():
    page, connection = _page(lambda params: {"result": {"type": "number", "value": 3}})

    assert page.read("1 + 2") == 3
    assert connection.asked[-1] == ("Runtime.evaluate", {
        "expression": "1 + 2", "awaitPromise": True, "returnByValue": True})


def test_a_page_goes_to_an_address():
    page, connection = _page(lambda params: {})

    page.go_to("https://example.com/create")

    assert connection.asked[-1] == ("Page.navigate", {"url": "https://example.com/create"})


def test_a_script_that_throws_on_the_page_is_raised():
    page, _connection = _page(lambda params: {"result": {}, "exceptionDetails": {"text": "Uncaught"}})

    with pytest.raises(ChromeRefused, match="Uncaught"):
        page.run("throw 1")


def test_a_page_is_told_to_act_as_the_window_in_front_so_typing_reaches_it():
    _the_page, connection = _page(lambda params: {})

    assert connection.asked == [("Emulation.setFocusEmulationEnabled", {"enabled": True})]


class FakeStarted:
    def __init__(self, command, profile: Path, port: str):
        self.command = command
        self.running = True
        self.ended = False
        (profile / PORT_FILE).write_text(f"{port}\n/devtools/chrome/made-up", encoding="utf-8")

    def is_running(self) -> bool:
        return self.running

    def end(self) -> None:
        self.ended = True
        self.running = False


class Chromes:
    def __init__(self, tmp_path):
        self.profile = tmp_path / "profile"
        self.started: list[tuple[str, FakeStarted]] = []
        self.connections: dict[str, FakeConnection] = {}
        self.read: list[str] = []
        self.answers = True
        self.chrome = SiteChrome(
            self.profile, Path("chrome.exe"),
            start_unseen=lambda command: self._start("unseen", command),
            start_seen=lambda command: self._start("seen", command),
            connect=self._connect, read_json=self._read_json)

    def _start(self, how: str, command):
        started = FakeStarted(command, self.profile, "50123")
        self.started.append((how, started))
        return started

    def _read_json(self, address: str):
        if not self.answers:
            raise OSError("refused")
        self.read.append(address)
        if address.endswith("/json/list"):
            return [{"type": "service_worker", "webSocketDebuggerUrl": "ws://worker"},
                    {"type": "page", "webSocketDebuggerUrl": "ws://page"}]
        return {"webSocketDebuggerUrl": "ws://whole"}

    def _connect(self, address: str):
        def answer(method, params):
            if method == "Browser.close":
                self.started[-1][1].running = False
            return {}

        return self.connections.setdefault(address, FakeConnection(answer))


def test_a_chrome_opens_unseen_on_its_own_profile_and_hands_back_its_page(tmp_path):
    chromes = Chromes(tmp_path)

    page = chromes.chrome.open("https://example.com/create")

    (how, started), = chromes.started
    assert how == "unseen"
    assert started.command == command_line(Path("chrome.exe"), chromes.profile,
                                           "https://example.com/create")
    assert chromes.read == ["http://127.0.0.1:50123/json/list"]
    page.go_to("https://example.com/video")
    assert chromes.connections["ws://page"].asked[-1][0] == "Page.navigate"


def test_a_chrome_asked_to_be_seen_is_started_where_it_shows(tmp_path):
    chromes = Chromes(tmp_path)

    chromes.chrome.open(seen=True)

    assert [how for how, _started in chromes.started] == ["seen"]


def test_a_port_left_by_an_earlier_chrome_is_not_taken_for_this_ones(tmp_path):
    chromes = Chromes(tmp_path)
    chromes.profile.mkdir()
    (chromes.profile / PORT_FILE).write_text("49999\n/old", encoding="utf-8")

    chromes.chrome.open()

    assert chromes.read == ["http://127.0.0.1:50123/json/list"]


def test_closing_asks_the_chrome_to_close_so_it_keeps_who_is_signed_in(tmp_path):
    chromes = Chromes(tmp_path)
    chromes.chrome.open()
    assert chromes.chrome.is_open()

    chromes.chrome.close()

    assert chromes.connections["ws://whole"].asked == [("Browser.close", {})]
    assert chromes.connections["ws://page"].closed
    assert chromes.started[0][1].ended
    assert not chromes.chrome.is_open()


def test_a_chrome_that_will_not_answer_is_ended_all_the_same(tmp_path):
    chromes = Chromes(tmp_path)
    chromes.chrome.open()
    chromes.answers = False

    chromes.chrome.close()

    assert chromes.started[0][1].ended


def test_closing_a_chrome_never_opened_does_nothing(tmp_path):
    chromes = Chromes(tmp_path)

    chromes.chrome.close()

    assert chromes.started == []


def test_the_command_line_names_the_profile_and_asks_for_a_port_of_the_chromes_choosing(tmp_path):
    line = command_line(Path("chrome.exe"), tmp_path, "about:blank")

    assert line[0] == "chrome.exe"
    assert f"--user-data-dir={tmp_path}" in line
    assert "--remote-debugging-port=0" in line
    assert "--mute-audio" in line
    assert line[-1] == "about:blank"


def test_chrome_is_found_under_the_first_folder_that_holds_it(tmp_path):
    chrome = tmp_path / "second" / "Google" / "Chrome" / "Application" / "chrome.exe"
    chrome.parent.mkdir(parents=True)
    chrome.write_bytes(b"")

    assert chrome_here({"PROGRAMFILES": str(tmp_path / "first"),
                        "LOCALAPPDATA": str(tmp_path / "second")}) == chrome
    assert chrome_here({}) is None
