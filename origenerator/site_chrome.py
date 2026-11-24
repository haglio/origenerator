from __future__ import annotations

import json
import logging
import os
import subprocess
import urllib.request
from collections.abc import Callable
from pathlib import Path

from app_support.threading_utils import wait_until
from websockets.sync.client import connect

from origenerator.unseen_desktop import start_unseen

logger = logging.getLogger(__name__)

PORT_FILE = "DevToolsActivePort"
STARTS_WITHIN_S = 60.0
ENDS_WITHIN_S = 15.0
_CHROME_UNDER = ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")
_CHROME = Path("Google") / "Chrome" / "Application" / "chrome.exe"


class ChromeRefused(Exception):
    pass


def chrome_here(environ=os.environ) -> Path | None:
    return next((chrome for under in _CHROME_UNDER
                 if environ.get(under) and (chrome := Path(environ[under]) / _CHROME).is_file()),
                None)


def command_line(chrome: Path, profile: Path, address: str) -> list[str]:
    return [str(chrome), f"--user-data-dir={profile}", "--remote-debugging-port=0",
            "--no-first-run", "--no-default-browser-check", "--mute-audio",
            "--window-size=1400,1000", address]


class DevTools:
    def __init__(self, connection):
        self._connection = connection
        self._asked = 0

    def ask(self, method: str, **params) -> dict:
        self._asked += 1
        self._connection.send(json.dumps({"id": self._asked, "method": method, "params": params}))
        while True:
            said = json.loads(self._connection.recv())
            if said.get("id") != self._asked:
                continue
            if "error" in said:
                raise ChromeRefused(f"{method}: {said['error'].get('message', '')}")
            return said.get("result", {})

    def close(self) -> None:
        self._connection.close()


class SitePage:
    def __init__(self, devtools: DevTools):
        self._devtools = devtools
        devtools.ask("Emulation.setFocusEmulationEnabled", enabled=True)

    def go_to(self, address: str) -> None:
        self._devtools.ask("Page.navigate", url=address)

    def run(self, script: str) -> None:
        self._evaluated(script)

    def read(self, expression: str):
        return self._evaluated(expression).get("value")

    def _evaluated(self, expression: str) -> dict:
        answer = self._devtools.ask("Runtime.evaluate", expression=expression, awaitPromise=True,
                                    returnByValue=True)
        if "exceptionDetails" in answer:
            raise ChromeRefused(answer["exceptionDetails"].get("text", "the page threw"))
        return answer.get("result", {})


class _StartedSeen:
    def __init__(self, command: list[str]):
        self._process = subprocess.Popen(command)

    def is_running(self) -> bool:
        return self._process.poll() is None

    def end(self) -> None:
        if self.is_running():
            self._process.terminate()


def _connected(address: str):
    return connect(address, max_size=None)


def _read_json(address: str):
    with urllib.request.urlopen(address) as answered:
        return json.load(answered)


class SiteChrome:
    def __init__(self, profile: Path, chrome: Path, *,
                 start_unseen: Callable = start_unseen, start_seen: Callable = _StartedSeen,
                 connect: Callable = _connected, read_json: Callable = _read_json,
                 until: Callable = wait_until):
        self._profile, self._chrome = Path(profile), Path(chrome)
        self._start = {False: start_unseen, True: start_seen}
        self._connect, self._read_json, self._until = connect, read_json, until
        self._started = None
        self._page: DevTools | None = None

    def open(self, address: str = "about:blank", *, seen: bool = False) -> SitePage:
        self._profile.mkdir(parents=True, exist_ok=True)
        port_file = self._profile / PORT_FILE
        port_file.unlink(missing_ok=True)
        self._started = self._start[seen](command_line(self._chrome, self._profile, address))
        self._until(lambda: _port_in(port_file) is not None, timeout=STARTS_WITHIN_S)
        listed = self._read_json(f"{self._at()}/json/list")
        first = next(page for page in listed if page.get("type") == "page")
        self._page = DevTools(self._connect(first["webSocketDebuggerUrl"]))
        return SitePage(self._page)

    def is_open(self) -> bool:
        return self._started is not None and self._started.is_running()

    def close(self) -> None:
        if self._started is None:
            return
        started, self._started = self._started, None
        try:
            if self._page is not None:
                self._page.close()
            whole = DevTools(self._connect(self._read_json(f"{self._at()}/json/version")
                                           ["webSocketDebuggerUrl"]))
            whole.ask("Browser.close")
            whole.close()
            self._until(lambda: not started.is_running(), timeout=ENDS_WITHIN_S)
        except Exception as gone:
            logger.info("The Chrome for sites did not close when asked, so it is ended: %r", gone)
        finally:
            self._page = None
            started.end()

    def _at(self) -> str:
        return f"http://127.0.0.1:{_port_in(self._profile / PORT_FILE)}"


def _port_in(port_file: Path) -> str | None:
    try:
        lines = port_file.read_text(encoding="utf-8").split()
    except OSError:
        return None
    return lines[0] if lines else None
