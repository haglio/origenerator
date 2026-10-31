"""The boot's steps, each on its own: a Boot built once, and one collaborator faked
per step, where tests/test_app.py drives the whole launch through ``main``."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from app_support import origenerator_handoff as handoff

from origenerator import app_link
from origenerator.app import WAITING_FOR_THE_OTHER_COPY, Boot
from origenerator.gui.loading_screen import LoadingCanceled
from tests.loading_screens import opened_here

REPO_ROOT = Path(__file__).resolve().parents[1]


def _a_boot(tmp_path, fun_time):
    return Boot(app=MagicMock(), fun_time=fun_time, preview=None, taskbar=None,
                logger=MagicMock(), state_dir=tmp_path / "preview" / "state",
                library_state_dir=tmp_path / "production" / "state")


@pytest.fixture
def boot(qapp, tmp_path):
    return _a_boot(tmp_path, fun_time=None)


@pytest.fixture
def hosted(qapp, tmp_path):
    return _a_boot(tmp_path, fun_time=MagicMock(in_a_headset=False))


@pytest.fixture
def screens():
    """Every loading screen opened, in this process rather than one of its own."""
    opened = []
    with patch("origenerator.gui.loading_screen.LoadingProcess.open",
               side_effect=opened_here(opened)):
        yield opened


# --- the claim on the library -------------------------------------------------


def _copies(claim, *, closing=False, after_the_closing_one=None):
    copies = MagicMock()
    copies.claim_the_library.return_value = claim
    copies.one_is_closing.return_value = closing
    copies.claim_the_library_once_the_closing_one_lets_go.return_value = after_the_closing_one
    return copies


def _a_loading_screen_saying_when_it_goes_down(boot, events):
    boot.loading = MagicMock()
    boot.loading.done.side_effect = lambda: events.append("loading screen down")
    boot.loading.say.side_effect = lambda step: events.append(step)
    return boot.loading


def test_a_free_library_is_claimed_and_the_claim_closes_with_the_app(boot):
    claim = MagicMock()

    assert boot.claim_the_library(_copies(claim)) is None

    assert boot.claim is claim
    claim.closes_with.assert_called_once_with(boot.app)


def test_a_launch_while_another_copy_closes_waits_for_it_on_its_loading_screen(boot):
    events = []
    _a_loading_screen_saying_when_it_goes_down(boot, events)
    claim = MagicMock()

    assert boot.claim_the_library(_copies(None, closing=True, after_the_closing_one=claim)) is None

    assert events == [WAITING_FOR_THE_OTHER_COPY]
    assert boot.claim is claim
    claim.closes_with.assert_called_once_with(boot.app)


def test_a_launch_that_finds_the_library_held_says_so_once_its_screen_is_down_and_stops(boot):
    events = []
    _a_loading_screen_saying_when_it_goes_down(boot, events)
    told = MagicMock(side_effect=lambda *said: events.append(said[-1]))

    with patch("PyQt6.QtWidgets.QMessageBox.information", told):
        assert boot.claim_the_library(_copies(None)) == 1

    assert events == ["loading screen down", "Another copy of Origenerator is already running."]


def test_a_click_on_a_toast_while_another_copy_runs_is_left_to_that_copy_without_a_word(
        boot, monkeypatch):
    monkeypatch.setenv(app_link.CARRIED_IN, "alpha-1")
    told = MagicMock()

    with patch("PyQt6.QtWidgets.QMessageBox.information", told):
        assert boot.claim_the_library(_copies(None)) == 0

    told.assert_not_called()


def test_the_copy_fun_time_opens_goes_on_without_the_library(hosted):
    told = MagicMock()

    with patch("PyQt6.QtWidgets.QMessageBox.information", told):
        assert hosted.claim_the_library(_copies(None)) is None

    assert hosted.claim is None
    told.assert_not_called()


# --- the loading screen -------------------------------------------------------


def test_the_first_thing_the_boot_says_opens_its_loading_screen_and_the_rest_reuses_it(
        boot, screens):
    boot.say("Starting ComfyUI server...")
    boot.say("Opening the image library...")

    assert [screen.panel.status for screen in screens] == ["Opening the image library..."]


def test_the_boot_takes_its_loading_screen_down_when_done(boot, screens):
    boot.say("Starting ComfyUI server...")

    boot.done()

    assert not screens[0].isVisible()


def test_a_boot_that_said_nothing_has_no_loading_screen_to_take_down(boot, screens):
    boot.done()

    assert screens == []


def test_a_boot_fun_time_opened_says_its_steps_to_the_log_and_opens_no_screen(hosted, screens):
    hosted.say("Starting ComfyUI server...")

    assert screens == []
    hosted.logger.info.assert_called_once_with("Boot: %s", "Starting ComfyUI server...")


def test_a_cancel_from_the_loading_screen_stops_the_boot_at_its_next_step(boot, screens):
    boot.say("Starting ComfyUI server...")
    screens[0].reject()

    with pytest.raises(LoadingCanceled):
        boot.stop_if_canceled()


# --- the offer to Fun Time ----------------------------------------------------


def _the_offers_standing_in(boot):
    return [handoff.the_offer_in(place) for place in (boot.state_dir, boot.library_state_dir)]


def test_a_copy_on_its_own_offers_its_window_to_fun_time_as_still_starting(boot):
    boot.offer_to_fun_time()

    me = handoff.this_process()
    assert _the_offers_standing_in(boot) == [handoff.Offer(me, starting=True)] * 2


def test_the_copy_fun_time_opened_offers_itself_to_nobody(hosted):
    hosted.offer_to_fun_time()

    assert _the_offers_standing_in(hosted) == [None, None]


# --- the crash log ------------------------------------------------------------


def test_the_crash_log_is_armed_in_the_copys_own_state_folder(boot):
    boot.arm_the_crash_log()

    assert Path(boot.crash_log.name) == boot.state_dir / "origenerator_crash.log"


def test_the_window_is_watched_for_freezes_before_the_app_runs(boot):
    events = []
    boot.crash_log = object()
    boot.app.exec.side_effect = lambda: events.append("running") or 3

    with patch("origenerator.freeze_watch.watch_the_window",
               side_effect=lambda app, log: events.append(("watching", app, log))):
        assert boot.run() == 3

    assert events == [("watching", boot.app, boot.crash_log), "running"]


def test_a_launch_without_a_crash_log_runs_with_nothing_watching_the_window(boot):
    boot.crash_log = None

    with patch("origenerator.freeze_watch.watch_the_window") as watching:
        boot.run()

    watching.assert_not_called()
    assert boot.freeze_watch is None


# --- the listener for clicked toasts -----------------------------------------


def test_the_boot_listens_for_clicks_on_the_production_checkouts_channel_before_it_has_a_window(
        boot, tmp_path):
    with patch("origenerator.gui.link_listener.LinkListener") as listener:
        boot.listen_for_clicked_toasts(tmp_path / "production")

    listener.assert_called_once_with(checkout=tmp_path / "production", parent=boot.app)
    assert boot.clicked_toasts is listener.return_value


# --- the window, once built ---------------------------------------------------


def _a_window_saying_what_happens_to_it(events):
    window = MagicMock()
    window.show.side_effect = lambda: events.append("shown")
    window.raise_.side_effect = lambda: events.append("fronted")
    return window


def _whose_screen_and_listener_record(boot, events):
    _a_loading_screen_saying_when_it_goes_down(boot, events)
    boot.clicked_toasts = MagicMock()
    boot.clicked_toasts.answer_with.side_effect = (
        lambda go_to: events.append(("clicks go to", go_to)))
    return boot


def test_the_window_goes_up_then_the_loading_screen_down_then_the_window_in_front_then_the_clicks(
        boot):
    events = []
    _whose_screen_and_listener_record(boot, events)
    window = _a_window_saying_what_happens_to_it(events)

    with patch("origenerator.gui.fun_time_watch.FunTimeWatch") as watch:
        watch.return_value.stands_its_offer.return_value = True
        boot.show(window)

    assert events == ["shown", "loading screen down", "fronted",
                      ("clicks go to", window.go_to_generation)]
    assert boot.watch is watch.return_value


def test_a_window_a_session_took_while_it_was_being_built_is_the_sessions_to_show(boot):
    events = []
    _whose_screen_and_listener_record(boot, events)
    window = _a_window_saying_what_happens_to_it(events)

    with patch("origenerator.gui.fun_time_watch.FunTimeWatch") as watch:
        watch.return_value.stands_its_offer.return_value = False
        boot.show(window)

    assert events == ["loading screen down", ("clicks go to", window.go_to_generation)]


def test_the_window_fun_time_opened_is_the_sessions_to_show(hosted):
    events = []
    _whose_screen_and_listener_record(hosted, events)
    window = _a_window_saying_what_happens_to_it(events)

    with patch("origenerator.gui.fun_time_watch.FunTimeWatch") as watch:
        hosted.show(window)

    watch.assert_not_called()
    assert events == ["loading screen down", ("clicks go to", window.go_to_generation)]


# --- a cancel, and a close ----------------------------------------------------


def _a_client_saying_when_it_is_disconnected(events):
    client = MagicMock()
    client.wait.side_effect = lambda ms: events.append("disconnected from ComfyUI")
    return client


def _a_window_saying_when_comfyui_is_handed_its_work(events):
    window = MagicMock()
    window.hand_comfyui_what_runs_while_closed.side_effect = (
        lambda: events.append("ComfyUI handed its work"))
    return window


def _whose_claim_says_when_it_lets_go(boot, events):
    boot.claim = MagicMock()
    boot.claim.let_go.side_effect = lambda: events.append("let go of the library")
    return boot


def test_a_cancel_lets_go_of_comfyui_then_the_library_and_takes_the_screen_down_last(boot):
    events = []
    boot.offer_to_fun_time()
    _whose_claim_says_when_it_lets_go(boot, events)
    _a_loading_screen_saying_when_it_goes_down(boot, events)

    assert boot.cancel(None, _a_client_saying_when_it_is_disconnected(events)) == 0

    assert events == ["disconnected from ComfyUI", "let go of the library", "loading screen down"]
    assert _the_offers_standing_in(boot) == [None, None]


def test_a_cancel_puts_a_window_already_built_away_unseen(boot):
    events = []
    window = _a_window_saying_when_comfyui_is_handed_its_work(events)
    window.close.side_effect = lambda: events.append("window closed")
    boot.loading = MagicMock()

    with patch("origenerator.app._run_the_loop_only_to_quit",
               side_effect=lambda app: events.append(("loop run only to quit", app))):
        boot.cancel(window, MagicMock())

    assert events == ["window closed", ("loop run only to quit", boot.app),
                      "ComfyUI handed its work"]
    window.show.assert_not_called()


def test_a_close_withdraws_the_offer_hands_comfyui_its_work_disconnects_and_lets_go_in_that_order(
        boot):
    events = []
    boot.watch = MagicMock()
    boot.watch.withdraw.side_effect = lambda: events.append("offer withdrawn")
    _whose_claim_says_when_it_lets_go(boot, events)

    boot.close(_a_window_saying_when_comfyui_is_handed_its_work(events),
               _a_client_saying_when_it_is_disconnected(events))

    assert events == ["offer withdrawn", "ComfyUI handed its work", "disconnected from ComfyUI",
                      "let go of the library"]


def test_the_copy_fun_time_opened_closes_with_no_offer_to_withdraw_and_no_claim_to_let_go(hosted):
    events = []

    hosted.close(_a_window_saying_when_comfyui_is_handed_its_work(events),
                 _a_client_saying_when_it_is_disconnected(events))

    assert events == ["ComfyUI handed its work", "disconnected from ComfyUI"]


# --- the ceiling --------------------------------------------------------------

MAX_BOOT_COMPLEXITY = 11


@pytest.mark.repo_check
def test_no_function_of_the_boot_outgrows_the_ceiling():
    """A ceiling that can only come down, on every function in the module that
    boots the app, by the count ruff's C901 keeps: the next thing the launch takes
    on becomes a step of Boot with a test of its own, or seams one out, rather
    than one more branch of the routine."""
    ruff = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", "--isolated", "--select", "C901",
         "--config", f"lint.mccabe.max-complexity = {MAX_BOOT_COMPLEXITY}",
         "--output-format", "concise", "origenerator/app.py"],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", check=False)

    assert ruff.returncode == 0, ruff.stdout + ruff.stderr
