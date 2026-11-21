from __future__ import annotations

import subprocess
from pathlib import Path

from app_support.file_channel import read_paused_state
from app_support.win32 import TaskbarApp
from funestra.funestra_verbs import QUIT
from funestra.program.cli import build_parser
from funestra.program.window_verbs import (
    WINDOW_FRONT,
    WINDOW_HIDE,
    WINDOW_MINIMIZE,
    WINDOW_SHOW,
    window_place,
)

from origenerator.fun_time_mode import Rect
from origenerator.gui.funestra_program import (
    FunestraProgram,
    OwnFunestras,
    Wearing,
    worn_by_this_app,
)
from origenerator.gui.taskbar_identity import TaskbarIdentity
from tests.own_funestra_support import FakeProgram


class _Started:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.how: list[dict] = []
        self.ended = False

    def __call__(self, command, **how):
        self.commands.append(list(command))
        self.how.append(how)
        return self

    def poll(self):
        return 0 if self.ended else None


def _program(tmp_path, **how):
    started = _Started()
    how.setdefault("let_it_take_the_keyboard", lambda: None)
    program = FunestraProgram(tmp_path / "funestra", popen=started,
                              python_exe=Path("C:/made_up/python.exe"), app_pid=4321, **how)
    return program, started


def _sent(program) -> list[str]:
    return program.channel.command_file.read_text(encoding="utf-8").splitlines()


def test_it_starts_the_funestra_program_hidden_with_no_console_and_ending_with_this_app(tmp_path):
    program, started = _program(tmp_path)

    program.start()

    command, = started.commands
    assert command[:3] == [str(Path("C:/made_up/python.exe")), "-m", "funestra.program"]
    args = build_parser().parse_args(command[3:])
    assert (args.hidden, args.keys, args.ends_with) == (True, True, 4321)
    assert started.how[0]["creationflags"] == subprocess.CREATE_NO_WINDOW


def test_the_program_is_handed_the_files_the_app_reaches_it_through(tmp_path):
    program, started = _program(tmp_path)

    program.start()

    args = build_parser().parse_args(started.commands[0][3:])
    channel = program.channel
    assert (args.playlist, args.command, args.status, args.hud) == (
        channel.playlist, channel.command_file, channel.status_file, channel.hud_file)
    assert (args.dashboard_cmd, args.paused) == (program.asks_file, program.paused_file)
    assert len({args.playlist, args.command, args.status, args.hud, args.dashboard_cmd,
                args.paused}) == 6


def test_it_wears_the_title_identity_and_icon_the_app_gives_it(tmp_path):
    program, started = _program(tmp_path, wearing=Wearing(
        title="Slideshow", taskbar_identity="Made.Up", icon=tmp_path / "icon.ico"))

    program.start()

    args = build_parser().parse_args(started.commands[0][3:])
    assert (args.title, args.taskbar_identity, args.icon) == (
        "Slideshow", "Made.Up", tmp_path / "icon.ico")


def test_shown_on_a_place_it_is_put_there_then_shown(tmp_path):
    program, _started = _program(tmp_path)
    program.start()

    program.show_on(Rect(-1440, 0, 1440, 2560))

    assert _sent(program) == [window_place(-1440, 0, 1440, 2560), WINDOW_SHOW]
    assert program.place == Rect(-1440, 0, 1440, 2560)


def test_hidden_minimized_and_brought_forward_are_the_windows_own_verbs(tmp_path):
    program, _started = _program(tmp_path)
    program.start()

    program.hide()
    program.minimize()
    program.come_forward()

    assert _sent(program) == [WINDOW_HIDE, WINDOW_MINIMIZE, WINDOW_FRONT]


def test_the_pause_is_a_flag_the_program_reads_each_pass(tmp_path):
    program, _started = _program(tmp_path)
    program.start()

    program.set_paused(True)
    assert read_paused_state(program.paused_file) is True
    program.set_paused(False)
    assert read_paused_state(program.paused_file) is False


def test_ended_it_is_told_to_quit_and_is_no_longer_running(tmp_path):
    program, started = _program(tmp_path)
    program.start()
    assert program.running

    program.end()
    started.ended = True

    assert _sent(program) == [QUIT]
    assert not program.running


def test_one_never_started_is_not_running_and_ends_quietly(tmp_path):
    program, started = _program(tmp_path)

    program.end()

    assert not program.running
    assert started.commands == []


def test_the_apps_own_funestra_wears_the_apps_icon_so_the_window_switcher_shows_no_blank_page(qapp):
    assert worn_by_this_app().icon.is_file()


def test_a_previews_funestra_wears_the_previews_icon_not_the_production_one(qapp, tmp_path):
    preview_icon = tmp_path / "preview.ico"
    preview_icon.write_bytes(b"")
    taskbar = TaskbarIdentity(qapp, "Made.Up.App", TaskbarApp("Made Up", preview_icon, "relaunch"),
                              dress=lambda *_worn: None, described=lambda _identity: None)

    assert worn_by_this_app(taskbar).icon == preview_icon


def test_it_joins_whichever_taskbar_button_the_apps_windows_wear(qapp):
    taskbar = TaskbarIdentity(qapp, "Made.Up.App", None, dress=lambda *_worn: None,
                              described=lambda _identity: None)

    assert worn_by_this_app(taskbar).taskbar_identity == "Made.Up.App"
    taskbar.join("Made.Up.Session")
    assert worn_by_this_app(taskbar).taskbar_identity == "Made.Up.Session"


def _own(tmp_path):
    made = []

    def started(folder, wearing):
        program = FakeProgram(folder, wearing)
        program.start()
        made.append(program)
        return program

    return OwnFunestras(tmp_path / "funestras", started=started, wearing=Wearing), made


def test_one_is_kept_waiting_so_a_slideshow_opens_without_waiting_for_a_program_to_start(tmp_path):
    own, made = _own(tmp_path)

    own.have_one_waiting()
    own.have_one_waiting()

    assert len(made) == 1
    assert own.take() is made[0]


def test_the_one_taken_is_gone_from_the_wait_and_the_next_asked_for_is_another(tmp_path):
    own, made = _own(tmp_path)
    own.have_one_waiting()
    taken = own.take()

    own.have_one_waiting()

    assert len(made) == 2
    assert own.take() is made[1] is not taken


def test_with_none_waiting_one_is_started_on_the_spot(tmp_path):
    own, made = _own(tmp_path)

    assert own.take() is made[0]


def test_a_waiting_one_that_died_is_replaced(tmp_path):
    own, made = _own(tmp_path)
    own.have_one_waiting()
    made[0].ended = True

    own.have_one_waiting()

    assert own.take() is made[1]


def test_each_has_a_folder_of_its_own_and_the_last_runs_leftovers_are_cleared(tmp_path):
    stale = tmp_path / "funestras" / "7" / "cmd.txt"
    stale.parent.mkdir(parents=True)
    stale.write_text("QUIT", encoding="utf-8")
    own, _made = _own(tmp_path)

    first, second = own.take(), own.take()

    assert not stale.exists()
    assert first.channel.command_file.parent != second.channel.command_file.parent


def test_the_one_still_waiting_is_ended_with_the_app(tmp_path):
    own, made = _own(tmp_path)
    own.have_one_waiting()

    own.end_the_one_waiting()
    own.end_the_one_waiting()

    assert made[0].ended
    assert own.take() is not made[0]


def test_a_program_about_to_be_shown_is_let_take_the_keyboard_first(tmp_path):
    order = []
    program, _started = _program(tmp_path, let_it_take_the_keyboard=lambda: order.append("let"))
    program.start()

    program.show_on(Rect(0, 0, 800, 600))

    assert order == ["let"]
    assert _sent(program)[-1] == WINDOW_SHOW


def test_it_knows_it_is_minimized_until_it_is_shown_again(tmp_path):
    program, _started = _program(tmp_path)
    program.start()

    program.minimize()
    assert program.minimized
    program.show_on(Rect(0, 0, 800, 600))

    assert not program.minimized
