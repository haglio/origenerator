from __future__ import annotations

import ctypes
import logging
import os
import shutil
import socket
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from app_support.file_channel import publish_whole
from funestra.funestra import Channels
from funestra.funestra_verbs import QUIT
from funestra.program.genau_launch import GenauLaunch
from funestra.program.launch import Asked, launch_command
from funestra.program.placement import WindowPlacement
from funestra.program.window_verbs import (
    WINDOW_HIDE,
    WINDOW_MINIMIZE,
    WINDOW_NOT_ON_TOP,
    WINDOW_ON_TOP,
    WINDOW_SHOW,
    window_place,
)
from PySide6.QtWidgets import QApplication

from origenerator.config import PROJECT_DIR
from origenerator.fun_time_mode import FunestraChannel, Rect
from origenerator.funestras_engine import offer_the_copy_beside_the_checkouts
from origenerator.gui.taskbar_identity import TaskbarIdentity

logger = logging.getLogger(__name__)

_FILES = ("playlist.tsv", "cmd.txt", "status.txt", "hud.json", "asks.txt", "paused.txt")
_GENAUS_FILES = ("genau_cmd.txt", "genau_paused.txt", "genau_status.txt", "genau_drive.txt",
                 "genau_flicks.tsv")
_ANY_PROGRAM = 0xFFFFFFFF


def _let_a_program_take_the_keyboard() -> None:
    # Windows lets a window come to the front only if the program in front allows it; the program
    # with the window is a child of the one this app started, so its process id is not known here.
    if sys.platform == "win32":
        ctypes.WinDLL("user32").AllowSetForegroundWindow(_ANY_PROGRAM)


def a_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def genau_beside(folder: Path) -> GenauLaunch:
    command, paused, status, drive, flicks = (folder / name for name in _GENAUS_FILES)
    return GenauLaunch(command=command, paused=paused, status=status, drive=drive, flicks=flicks,
                       beat_port=0)


def _the_interpreter_that_is_not_pythonw() -> Path:
    here = Path(sys.executable)
    plain = here.with_name("python.exe")
    return plain if plain.exists() else here


@dataclass(frozen=True)
class Wearing:
    title: str = "Slideshow"
    taskbar_identity: str | None = None
    icon: Path | None = None


AS_IT_COMES = Wearing()


class FunestraProgram:
    def __init__(self, folder: Path, *, wearing: Wearing = AS_IT_COMES, python_exe: Path | None = None,
                 popen=subprocess.Popen, app_pid: int | None = None,
                 let_it_take_the_keyboard=_let_a_program_take_the_keyboard,
                 free_port=a_free_port) -> None:
        self._folder = Path(folder)
        self.wearing = wearing
        self._python_exe = python_exe
        self._popen = popen
        self._app_pid = app_pid
        self._process = None
        self._let_it_take_the_keyboard = let_it_take_the_keyboard
        self._free_port = free_port
        self.place: Rect | None = None
        self.minimized = False
        playlist, command, status, hud, asks, paused = (self._folder / name for name in _FILES)
        self.channel = FunestraChannel(playlist, command, status, hud)
        self.asks_file = asks
        self.paused_file = paused
        self.genau = genau_beside(self._folder)

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        self._folder.mkdir(parents=True, exist_ok=True)
        offer_the_copy_beside_the_checkouts()
        channel = self.channel
        self.genau = replace(self.genau, beat_port=self._free_port())
        command = launch_command(
            self._python_exe or _the_interpreter_that_is_not_pythonw(),
            Channels(playlist=channel.playlist, command=channel.command_file,
                     status=channel.status_file, hud=channel.hud_file,
                     dashboard_cmd=self.asks_file, paused=self.paused_file),
            WindowPlacement(title=self.wearing.title, icon=self.wearing.icon,
                            taskbar_identity=self.wearing.taskbar_identity),
            Asked(hidden=True, keys=True,
                  ends_with=os.getpid() if self._app_pid is None else self._app_pid),
            genau=self.genau)
        self._process = self._popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        logger.info("Started a Funestra of this app's own, waiting for its list")

    def show_on(self, place: Rect) -> None:
        self.place, self.minimized = place, False
        self._let_it_take_the_keyboard()
        self.channel.send(window_place(place.x, place.y, place.width, place.height))
        self.channel.send(WINDOW_SHOW)

    def hide(self) -> None:
        self.channel.send(WINDOW_HIDE)

    def minimize(self) -> None:
        self.minimized = True
        self.channel.send(WINDOW_MINIMIZE)

    def stand_on_top(self, on: bool) -> None:
        self.channel.send(WINDOW_ON_TOP if on else WINDOW_NOT_ON_TOP)

    def set_paused(self, paused: bool) -> None:
        publish_whole(self.paused_file, "1" if paused else "0")

    def end(self) -> None:
        if self._process is None:
            return
        self.channel.send(QUIT)
        self.place = None


def worn_by_this_app(taskbar: TaskbarIdentity | None = None) -> Wearing:
    application = QApplication.instance()
    if taskbar is None and application is not None:
        taskbar = application.findChild(TaskbarIdentity)
    own_app = None if taskbar is None else taskbar.own_app
    icon = PROJECT_DIR / "icon.ico" if own_app is None else own_app.icon
    return Wearing(taskbar_identity=None if taskbar is None else taskbar.wearing[0],
                   icon=icon if icon.is_file() else None)


def _started(folder: Path, wearing: Wearing) -> FunestraProgram:
    program = FunestraProgram(folder, wearing=wearing)
    program.start()
    return program


class OwnFunestras:
    def __init__(self, folder: Path, *,
                 started: Callable[[Path, Wearing], FunestraProgram] | None = None,
                 wearing: Callable[[], Wearing] = worn_by_this_app) -> None:
        self._folder = Path(folder)
        self._start = started
        self._wearing = wearing
        self._count = 0
        self._waiting: FunestraProgram | None = None

    def have_one_waiting(self) -> None:
        if self._waiting is None or not self._waiting.running:
            self._waiting = self._one_more(self._wearing())

    def take(self) -> FunestraProgram:
        waiting, self._waiting = self._waiting, None
        if waiting is not None and waiting.running:
            return waiting
        return self._one_more(self._wearing())

    def _one_more(self, wearing: Wearing) -> FunestraProgram:
        if self._count == 0:
            shutil.rmtree(self._folder, ignore_errors=True)
        self._count += 1
        return (self._start or _started)(self._folder / str(self._count), wearing)

    def end_the_one_waiting(self) -> None:
        waiting, self._waiting = self._waiting, None
        if waiting is not None:
            waiting.end()
