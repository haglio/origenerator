from __future__ import annotations

import pytest
from funestra.console import (
    OSR2_DRIVING,
    OSR2_PARKED,
    OSR2_RETRACTED,
)
from funestra.hud_osr2 import state_for
from funestra.modes import Osr2State
from funestra.volume import VolumeHud
from PyQt6.QtCore import (
    QPoint,
    Qt,
)
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (
    QApplication,
    QLineEdit,
    QWidget,
)

from origenerator import (
    gallery,
    osr2_driver,
)
from origenerator.comfyui_client import ComfyUIClient
from origenerator.gui import generate_config_panel as gcp_module
from origenerator.gui import (
    omnipause,
)
from origenerator.gui.gallery_view import GalleryView
from tests import gestures
from tests.comfyui_folders import SUITE_FOLDERS
from tests.gallery_view_support import (
    _REROLL_HISTORY,
    FakeActions,
    FakeDB,
    _a_slideshow_standing_on_its_own,
    _aim_slideshow,
    _double_click_slideshow,
    _FakeRadio,
    _generating_tile,
    _image,
    _keys_are_the_gallerys,
    _on_screen,
    _open_leaf,
    _png_bytes,
    _press_ctrl_f,
    _press_enter,
    _press_escape,
    _preview_of,
    _reroll_client,
    _resolve_by_id,
    _seeded_db,
    _select_first_leaf,
    _selected_folder,
    _shown_view_with_one_image,
    _SignalMotion,
    _tab_with_prompts,
)
from tests.lit_switches import lit_in
from tests.osr2_fakes import FakeBroker
from tests.slideshow_hud_support import engine_of, funestra_of
from tests.test_osr2_driver import ACTIONS, FakePlayer

pytestmark = pytest.mark.usefixtures("_stub_preview_resolution")


# --- Drive OSR2: one global toggle, following whatever video is in front ----


class _FakeDriver:
    parked_by_the_pause = False

    def __init__(self):
        self.started = []
        self.stopped = 0
        self.active = False

    def start(self, player, actions):
        self.started.append((player, actions))
        self.active = True

    def stop(self):
        self.stopped += 1
        self.active = False

    def trace(self, count, seconds):
        """What the console asks a driver for while it has the device. These
        cases carry no scripted video, so there is no line to draw — the same
        empty answer the real driver gives for one."""
        return ()


def _osr2_view(qtbot):
    """A gallery with both drive sources stubbed: the funscript driver, and the
    motion the one switch falls back to when there is no script to follow."""
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), client=ComfyUIClient(folders=SUITE_FOLDERS),
                       osr2_motion=_SignalMotion())
    qtbot.addWidget(view)
    driver = _FakeDriver()
    view._osr2_driver = driver
    view.osr2_control.script = driver
    return view, driver, view._info_tabs.current_config_panel()


def test_the_consoles_control_group_is_the_apps_one_osr2_switch(qtbot):
    """The whole point of the group: from a slideshow there was no way to reach
    the toolbar's switch at all, and now there is no toolbar switch to reach."""
    view, driver, panel = _osr2_view(qtbot)
    panel.osr2_drive_target = lambda: ("A.mp4", "player-A", "actions-A")

    view.osr2_control.set_state(OSR2_DRIVING)
    assert driver.started == [("player-A", "actions-A")]
    assert view.osr2_control.state() == OSR2_DRIVING

    view.osr2_control.set_state(OSR2_PARKED)
    assert driver.stopped == 1
    assert view.osr2_control.isChecked() is False


def test_parking_from_the_console_stills_the_motion_at_home_and_keeps_the_device(qtbot):
    view, _driver, _panel = _osr2_view(qtbot)

    view.osr2_control.set_state(OSR2_PARKED)

    assert view.osr2_control.engaged() is True
    assert ("hold", OSR2_PARKED) in view._osr2_motion.calls
    assert view.osr2_control.state() == OSR2_PARKED


def test_a_hold_stands_the_funscript_down_and_puts_the_motion_on_the_device(qtbot):
    """A script driving through a park is the device ignoring the hold, which is
    what the console would be lying about.  The stilled motion is what takes the
    device to that end and keeps it there."""
    view, driver, panel = _osr2_view(qtbot)
    panel.osr2_drive_target = lambda: ("A.mp4", "player-A", "actions-A")
    view.osr2_control.set_state(OSR2_DRIVING)
    assert driver.started
    assert view._osr2_motion.active is False

    view.osr2_control.set_state(OSR2_PARKED)

    assert driver.stopped == 1
    assert view._osr2_motion.active is True
    assert ("hold", OSR2_PARKED) in view._osr2_motion.calls


def test_driving_after_a_hold_gives_the_script_the_device_back(qtbot):
    view, driver, panel = _osr2_view(qtbot)
    panel.osr2_drive_target = lambda: ("A.mp4", "player-A", "actions-A")
    view.osr2_control.set_state(OSR2_PARKED)

    view.osr2_control.set_state(OSR2_DRIVING)

    assert ("release",) in view._osr2_motion.calls
    assert driver.started[-1] == ("player-A", "actions-A")
    assert view._osr2_motion.active is False


def _logging(log, name, inner):
    def logged(*args):
        log.append(name)
        return inner(*args)
    return logged


def _handoff_log(view, driver):
    """Every take and give-back of the device by either driver, in order."""
    log = []
    for name, owner, method in (("script takes", driver, "start"),
                                ("script lets go", driver, "stop"),
                                ("motion takes", view._osr2_motion, "start"),
                                ("motion lets go", view._osr2_motion, "stop")):
        setattr(owner, method, _logging(log, name, getattr(owner, method)))
    return log


def test_the_motion_lets_go_before_the_script_takes_the_device(qtbot):
    """Each driver puts back what it found when it took the device -- the OSR2's
    auto flag among it -- so one that takes over before the other has let go
    finds the device already taken, and later puts that back.  A hold handed to
    a script that way left OSR2 auto switched off for every app."""
    view, driver, panel = _osr2_view(qtbot)
    panel.osr2_drive_target = lambda: ("A.mp4", "player-A", "actions-A")
    view.osr2_control.set_state(OSR2_PARKED)
    log = _handoff_log(view, driver)

    view.osr2_control.set_state(OSR2_DRIVING)

    assert log == ["motion lets go", "script takes"]


def test_the_script_lets_go_before_the_motion_takes_the_device(qtbot):
    view, driver, panel = _osr2_view(qtbot)
    panel.osr2_drive_target = lambda: ("A.mp4", "player-A", "actions-A")
    view.osr2_control.set_state(OSR2_DRIVING)
    log = _handoff_log(view, driver)

    view.osr2_control.set_state(OSR2_PARKED)

    assert log == ["script lets go", "motion takes"]


def test_every_console_over_the_device_hears_that_it_was_re_aimed(qtbot):
    """The panel redraws on this: which driver has the device moves with the
    video in front, not only with a press."""
    view, _driver, panel = _osr2_view(qtbot)
    heard = []
    view.osr2_control.settled.connect(lambda: heard.append(True))

    view.osr2_control.set_state(OSR2_DRIVING)

    assert heard


def test_global_toggle_drives_the_front_video_and_untoggling_stops(qtbot):
    view, driver, panel = _osr2_view(qtbot)
    panel.osr2_drive_target = lambda: ("A.mp4", "player-A", "actions-A")

    view.osr2_control.setChecked(True)  # the one global switch, on
    assert driver.started == [("player-A", "actions-A")]

    view.osr2_control.setChecked(False)  # off
    assert driver.stopped == 1


def test_toggle_on_with_no_video_shown_moves_instead(qtbot):
    # "Genau mode when no funscript is going": with nothing scripted in front,
    # the one switch drives the device from the app's own motion rather than
    # sitting armed and doing nothing.
    view, driver, panel = _osr2_view(qtbot)
    panel.osr2_drive_target = lambda: None  # front tab isn't showing a scripted video

    view.osr2_control.setChecked(True)
    assert driver.started == []
    assert view._osr2_motion.active

    view.osr2_control.setChecked(False)  # off is parked: the motion stilled at home
    assert view._osr2_motion.held == OSR2_PARKED


def test_space_flips_the_one_switch_rather_than_the_motion_alone(qtbot):
    # Space is genau's "drives" key and the switch is the same control, so it has
    # to reach the switch: routed to the motion directly it would start a second
    # source alongside a funscript the switch already had streaming.
    view, driver, panel = _osr2_view(qtbot)
    panel.osr2_drive_target = lambda: ("A.mp4", "pA", "aA")
    _on_screen(qtbot, view, 1400, 900)
    view.osr2_control.setChecked(True)
    assert driver.started == [("pA", "aA")]
    assert not view._osr2_motion.active

    gestures.press_key(view, Qt.Key.Key_Space)

    assert not view.osr2_control.isChecked()      # the switch went off, not the motion
    assert driver.stopped >= 1
    assert view._osr2_motion.held == OSR2_PARKED


def test_space_after_a_click_in_the_info_pane_drives_rather_than_pressing_it_again(qtbot):
    view, _driver, _panel = _osr2_view(qtbot)
    section = next(iter(_tab_with_prompts(view)._param_form._sections.values()))
    _on_screen(qtbot, view, 1400, 900)
    gestures.click(section._header, section._header.rect().center())
    folded = section.is_collapsed()
    assert QApplication.focusWidget() is section._header

    gestures.press_key(view, Qt.Key.Key_Space)

    assert view.osr2_control.isChecked()
    assert section.is_collapsed() == folded


def test_a_slideshow_gets_space_wired_to_the_switch(qtbot):
    # Every surface that answers the motion keys has to send Space to the one
    # switch rather than to the motion it was handed — the slideshow as much as the
    # main window, since a slideshow is where the device is usually driven from.
    view, _driver, _panel = _osr2_view(qtbot)
    slideshow = _double_click_slideshow(view, qtbot)
    assert slideshow._actions.drive_toggle == view.toggle_osr2_drive


def test_browsing_to_a_new_video_retargets_the_running_driver(qtbot):
    view, driver, panel = _osr2_view(qtbot)
    panel.osr2_drive_target = lambda: ("A.mp4", "pA", "aA")
    view.osr2_control.setChecked(True)
    assert driver.started[-1] == ("pA", "aA")

    panel.osr2_drive_target = lambda: ("B.mp4", "pB", "aB")
    panel.displayed_changed.emit()  # user browsed to another video in the same tab
    assert driver.started[-1] == ("pB", "aB")  # re-aimed at B


def test_switching_to_a_tab_without_a_scripted_video_stops_driving(qtbot):
    view, driver, panel = _osr2_view(qtbot)
    panel.osr2_drive_target = lambda: ("A.mp4", "pA", "aA")
    view.osr2_control.setChecked(True)
    assert driver.started

    view._info_tabs._add_subtab()  # a fresh, blank tab comes to the front
    assert driver.stopped >= 1


def test_the_control_state_round_trips_for_persistence(qtbot):
    view, _driver, _panel = _osr2_view(qtbot)
    assert view.osr2_state() == OSR2_PARKED

    for state in (OSR2_PARKED, OSR2_DRIVING):
        view.restore_osr2_state(state)
        assert view.osr2_state() == state, state


def test_a_session_saved_under_retracted_or_control_off_reopens_parked(qtbot):
    view, _driver, _panel = _osr2_view(qtbot)

    for saved in (OSR2_RETRACTED, "control_off"):
        view.restore_osr2_state(saved)
        assert view.osr2_state() == OSR2_PARKED, saved


def _radio_view(qtbot):
    radio = _FakeRadio()
    view = GalleryView(FakeDB([]), actions=FakeActions(), radio=radio)
    qtbot.addWidget(view)
    return view, radio


def test_the_radio_switch_tunes_the_radio_in_and_silences_it(qtbot):
    view, radio = _radio_view(qtbot)
    assert (radio.starts, radio.stops) == (0, 0)  # off until asked

    view._bank.radio.setChecked(True)
    assert radio.starts == 1

    view._bank.radio.setChecked(False)
    assert radio.stops == 1


def test_the_radio_switch_round_trips_for_persistence(qtbot):
    view, radio = _radio_view(qtbot)
    assert view.radio_enabled() is False

    view.set_radio_enabled(True)

    assert view.radio_enabled() is True
    assert view._bank.radio.isChecked()
    assert radio.starts == 1  # restoring the switch actually starts it playing


def test_the_rooms_pause_reaches_the_radio_and_the_motion(qtbot):
    radio, motion = _FakeRadio(), _SignalMotion()
    view = GalleryView(FakeDB([]), actions=FakeActions(), radio=radio,
                       osr2_motion=motion)
    qtbot.addWidget(view)

    view.set_room_paused(True)
    assert (radio.frozen, motion.frozen) == (True, True)

    view.set_room_paused(False)
    assert (radio.frozen, motion.frozen) == (False, False)


def test_the_rooms_pause_holds_a_scripted_videos_drive_still(qtbot, monkeypatch):
    broker = FakeBroker()
    monkeypatch.setattr(osr2_driver, "Osr2Broker", lambda *a, **k: broker)
    view = GalleryView(FakeDB([]), actions=FakeActions(), osr2_motion=_SignalMotion())
    qtbot.addWidget(view)
    panel = view._info_tabs.current_config_panel()
    panel.osr2_drive_target = lambda: ("A.mp4", FakePlayer(pos=100), ACTIONS)
    view.osr2_control.setChecked(True)

    view.set_room_paused(True)
    view.osr2_control.script.poll()

    assert broker.positions == []


def test_a_double_click_plays_the_visible_folder_in_its_own_order(qtbot, monkeypatch):
    # Left/Right step through the folder: the slideshow is built from the visible
    # items' media, in the browser's order, starting on the one already shown.
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2),
            _image("i3", "a cat", 50, 3)]
    view = GalleryView(FakeDB(rows), actions=FakeActions())
    qtbot.addWidget(view)
    monkeypatch.setattr(
        gallery, "resolve_preview",
        lambda row, places: (f"{row['prompt_id']}.png", "image"),
    )
    view.refresh()
    _open_leaf(view)
    view._on_thumbnail_clicked("i2")  # i2 is the shown/selected item

    slideshow = _double_click_slideshow(view, qtbot)

    order = view._browser.listed_prompt_ids()
    # Each entry carries its generation's id, so the slideshow's Up and Down can name
    # what to trash and what to bookmark, and its stored thumbnail, which is the
    # only still a video has for the neighbor previews.
    assert slideshow._set.playlist._items == [(f"{pid}.png", "image", pid, None)
                                          for pid in order]
    assert slideshow._set.playlist.order == list(range(len(order)))  # the browser's order
    assert slideshow._set.playlist.current()[2] == "i2"  # opened on the shown item
    slideshow.close()


def test_a_double_click_while_auto_generate_runs_opens_the_folder_on_the_shown_image(
        qtbot, tmp_path, monkeypatch):
    by_id = lambda row, places: (f"{row['prompt_id']}.png", "image")
    monkeypatch.setattr(gallery, "resolve_preview", by_id)
    monkeypatch.setattr(gcp_module, "resolve_preview", by_id)
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._bank.auto.click()
    _generating_tile(view).selected.emit()  # watching Auto-Generate in the tab
    landed = view._live_jobs[key].prompt_id
    client.job_completed.emit(landed, _REROLL_HISTORY)  # the tab shows it; the next runs

    slideshow = _preview_of(view).open_fullscreen()
    qtbot.addWidget(slideshow.shown)
    funestra_of(slideshow.shown)

    assert [slide.prompt_id for slide in slideshow._set.playlist.in_play_order()] == \
        view.listed_prompt_ids()
    assert slideshow._set.playlist.current().prompt_id == landed
    qtbot.keyClick(slideshow.shown, Qt.Key.Key_Down)
    assert view._enhance.run_of(view.row_for(landed)) is not None
    slideshow.close()


def test_a_double_click_on_an_image_from_another_folder_opens_that_folder(
        qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    rows = [_image("a1", "a cat", 50, 1), _image("b1", "a dog", 50, 1),
            _image("b2", "a dog", 50, 2)]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["b1"])
    folder_b = view.listed_prompt_ids()
    view._tree.setCurrentItem(view._leaf_by_id["a1"])

    slideshow = view._slideshows.open_on_preview(("b1.png", "image"), "b1")
    qtbot.addWidget(slideshow.shown)

    assert [slide.prompt_id for slide in slideshow._set.playlist.in_play_order()] == folder_b
    assert slideshow._set.playlist.current().prompt_id == "b1"
    slideshow.close()


def test_stepping_a_double_clicked_slideshow_re_aims_the_osr2(qtbot):
    # Stepping to another video re-aims the one device at the newly shown video.
    view, driver, _panel = _osr2_view(qtbot)
    view.osr2_control.setChecked(True)
    slideshow = _double_click_slideshow(view, qtbot, target=("A.mp4", "pA", "aA"))
    assert driver.started[-1] == ("pA", "aA")

    _aim_slideshow(view, slideshow, ("B.mp4", "pB", "aB"))  # Left/Right landed on another video
    assert driver.started[-1] == ("pB", "aB")
    slideshow.close()


def test_a_slideshow_opened_with_the_switch_off_drives_nothing(qtbot):
    # Double-clicking a video open once took the device whatever the switch said.
    view, driver, _panel = _osr2_view(qtbot)
    slideshow = _double_click_slideshow(view, qtbot, target=("A.mp4", "pA", "aA"))

    assert driver.started == []
    slideshow.close()


# --- the video in front, by the run it came from ------------------------------


def test_the_video_in_front_is_the_front_tab_s_while_no_slideshow_is_up(qtbot):
    view, _driver, panel = _osr2_view(qtbot)
    panel.video_on_screen = lambda: "alpha-1"

    assert view.video_in_front() == "alpha-1"


def test_a_slideshow_up_is_what_is_in_front_of_the_tab(qtbot):
    view, _driver, panel = _osr2_view(qtbot)
    panel.video_on_screen = lambda: "alpha-1"
    slideshow = _double_click_slideshow(view, qtbot)
    slideshow.video_on_screen = lambda: "beta-1"

    assert view.video_in_front() == "beta-1"
    slideshow.close()
    assert view.video_in_front() == "alpha-1"


# --- watching a folder that is auto-generating, and the app-global motion -----


def _auto_generating_view(qtbot, monkeypatch, rows):
    """A gallery on a settings leaf whose Auto-Generate reports active, built on a stubbed
    motion so no device backend spins up."""
    view = GalleryView(FakeDB(rows), actions=FakeActions(), client=ComfyUIClient(folders=SUITE_FOLDERS),
                       osr2_motion=_SignalMotion())
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    key = _selected_folder(view)
    monkeypatch.setattr(view._auto, "is_active", lambda k: k == key)
    return view, key


def test_double_clicking_a_generating_preview_opens_it_fullscreen(qtbot, monkeypatch):
    # A folder Auto-Generate runs in used to answer this gesture with the auto-generate
    # montage — a second slideshow, for a double-click that means "this one,
    # bigger". Watching the frames come in is what fullscreen is for.
    _resolve_by_id(monkeypatch)
    view, _key = _auto_generating_view(qtbot, monkeypatch, [_image("i1", "a cat", 50, 1)])
    panel = view._info_tabs.current_config_panel()
    panel._preview.show_frame(_png_bytes())  # Auto-Generate's generation, streaming

    win = panel._preview.open_fullscreen()

    qtbot.addWidget(win.shown)
    assert win is not None
    assert view._slideshows.showing is win
    assert [slide.prompt_id for slide in win.whole_set()] == ["i1"]
    win.close()


def test_a_funscript_coming_into_view_takes_the_device_off_the_motion(qtbot, monkeypatch):
    # The one switch picks the source, and a script beats the motion: turning it
    # on over an image moves it, and browsing to a scripted video hands the device
    # to the funscript rather than leaving both streaming at it.
    view, _key = _auto_generating_view(qtbot, monkeypatch, [_image("i1", "a cat", 50, 1)])
    driver = _FakeDriver()
    view._osr2_driver = driver
    panel = view._info_tabs.current_config_panel()
    panel.osr2_drive_target = lambda: None

    view.osr2_control.setChecked(True)
    assert view._osr2_motion.active
    assert driver.started == []

    panel.osr2_drive_target = lambda: ("A.mp4", "pA", "aA")
    panel.displayed_changed.emit()

    assert driver.started == [("pA", "aA")]
    assert not view._osr2_motion.active  # the motion stood down for the script


def test_a_slideshow_standing_on_its_own_plays_the_radio_while_its_image_is_up(
        qtbot, monkeypatch):
    radio = _FakeRadio()
    _view, slideshow = _a_slideshow_standing_on_its_own(qtbot, monkeypatch, radio=radio)
    engine_of(slideshow.shown).showing_image = True

    slideshow.shown._pane.tick()

    assert radio.held[-1].ticked == (True, 100, False)


def test_a_move_of_a_standing_slideshows_volume_turns_the_radio_on(qtbot, monkeypatch):
    radio = _FakeRadio()
    view, slideshow = _a_slideshow_standing_on_its_own(qtbot, monkeypatch, radio=radio)

    slideshow._actions.volume_moved(VolumeHud(volume=40, muted=False))

    assert view._bank.radio.isChecked()
    assert radio.starts == 1


def test_the_next_standing_slideshow_opens_at_the_volume_the_last_was_left_at(
        qtbot, monkeypatch):
    view, slideshow = _a_slideshow_standing_on_its_own(qtbot, monkeypatch, radio=_FakeRadio())
    slideshow._actions.volume_moved(VolumeHud(volume=40, muted=False))
    slideshow.close()

    view._slideshows.start()

    engine = engine_of(view._slideshows.showing.shown)
    assert (engine.volume, engine.muted) == (40, False)


def test_a_standing_slideshows_volume_comes_back_after_a_restart(qtbot, monkeypatch):
    first, slideshow = _a_slideshow_standing_on_its_own(qtbot, monkeypatch, radio=_FakeRadio())
    slideshow._actions.volume_moved(VolumeHud(volume=40, muted=True))
    saved = first.remembered_slideshows()

    second = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), actions=FakeActions(),
                         client=ComfyUIClient(folders=SUITE_FOLDERS), radio=_FakeRadio())
    qtbot.addWidget(second)
    second.remember_slideshows(saved)
    second.refresh()
    _open_leaf(second)
    second._slideshows.start()
    qtbot.addWidget(second._slideshows.showing.shown)

    engine = engine_of(second._slideshows.showing.shown)
    assert (engine.volume, engine.muted) == (40, True)


def _click_the_slide(slideshow):
    """A click on the slideshow's slide, clear of its HUD and of the corners that
    open it, through the window the Funestra draws into."""
    engine_of(slideshow.shown)
    slideshow.shown.showFullScreen()
    QTest.qWaitForWindowExposed(slideshow.shown)
    window = slideshow.shown._pane._window
    gestures.click(window, QPoint(window.width() * 3 // 4, window.height() * 3 // 4))


def test_a_click_on_a_slideshow_pauses_the_device_the_sound_and_the_slides_with_it(
        qtbot, monkeypatch):
    radio, motion = _FakeRadio(), _SignalMotion()
    _view, slideshow = _a_slideshow_standing_on_its_own(qtbot, monkeypatch, radio=radio,
                                                        osr2_motion=motion)

    _click_the_slide(slideshow)
    assert (slideshow.shown._paused, motion.frozen, radio.frozen, omnipause.frozen()) == (
        True, True, True, True)

    _click_the_slide(slideshow)
    assert (slideshow.shown._paused, motion.frozen, radio.frozen, omnipause.frozen()) == (
        False, False, False, False)
    slideshow.close()


def _double_click_the_slide(slideshow):
    window = slideshow.shown._pane._window
    gestures.double_click(window, QPoint(window.width() * 3 // 4, window.height() * 3 // 4))


@pytest.mark.parametrize("leave", [_double_click_the_slide, _press_enter],
                         ids=["a double-click on the slide", "Enter"])
def test_leaving_a_paused_slideshow_leaves_the_room_paused(qtbot, monkeypatch, leave):
    radio, motion = _FakeRadio(), _SignalMotion()
    _view, slideshow = _a_slideshow_standing_on_its_own(qtbot, monkeypatch, radio=radio,
                                                        osr2_motion=motion)
    _click_the_slide(slideshow)

    leave(slideshow)
    qtbot.waitUntil(lambda: not slideshow.shown.isVisible())

    assert (motion.frozen, radio.frozen, omnipause.frozen()) == (True, True, True)


def test_closing_a_slideshow_leaves_the_motion_running(qtbot, monkeypatch):
    # The motion is app-global: dismissing a view must not park the device.
    _resolve_by_id(monkeypatch)
    view, _key = _auto_generating_view(qtbot, monkeypatch, [_image("i1", "a cat", 50, 1)])
    view._slideshows.start()
    qtbot.addWidget(view._slideshows.showing.shown)
    # And its Space reaches the one switch, like every other surface's.
    assert view._slideshows.showing._actions.drive_toggle == view.toggle_osr2_drive
    view.osr2_control.setChecked(True)
    view._slideshows.showing.close()
    assert view._osr2_motion.active


def test_esc_holds_a_running_motion_still(qtbot, monkeypatch):
    view, _key = _auto_generating_view(qtbot, monkeypatch, [_image("i1", "a cat", 50, 1)])
    # Esc is the gallery's here — no dialog and no fullscreen view up. Said
    # outright, because which window Qt calls active is ambient in a test process
    # (a fullscreen view another test opened and closed can still hold it).
    monkeypatch.setattr(view, "_other_window_owns_keys", lambda: False)
    view.osr2_control.setChecked(True)
    assert view._osr2_motion.active
    assert view._handle_escape() is True
    assert view._osr2_motion.frozen


def test_the_motion_keys_work_in_core_too(qtbot, monkeypatch):
    # "Always available": the same keys the fullscreen views answer are routed
    # app-wide by the gallery's event filter, under its own-keys guards.
    view, _key = _auto_generating_view(qtbot, monkeypatch, [_image("i1", "a cat", 50, 1)])
    _on_screen(qtbot, view, 1400, 900)

    gestures.press_key(view, Qt.Key.Key_L)

    assert ("speed", 5) in view._osr2_motion.calls


def test_the_number_pads_7_and_9_change_the_travel_as_the_row_above_the_letters_does(
        qtbot, monkeypatch):
    view, _key = _auto_generating_view(qtbot, monkeypatch, [_image("i1", "a cat", 50, 1)])
    _on_screen(qtbot, view, 1400, 900)

    gestures.press_key(view, Qt.Key.Key_9, Qt.KeyboardModifier.KeypadModifier)

    assert ("amplitude", 10) in view._osr2_motion.calls


def test_watching_a_video_fullscreen_drives_nothing_with_the_toggle_off(qtbot):
    # The toggle governs a slideshow as much as the tab preview: double-clicking a video
    # to watch it doesn't take the device on its own.
    view, driver, _panel = _osr2_view(qtbot)
    assert not view.osr2_control.isChecked()

    slideshow = _double_click_slideshow(view, qtbot, target=("F.mp4", "pF", "aF"))

    assert driver.started == []
    slideshow.close()


def test_turning_the_toggle_on_over_an_open_slideshow_drives_its_video(qtbot):
    # …and turning it on while one is up drives what's on screen, without closing it.
    view, driver, _panel = _osr2_view(qtbot)
    slideshow = _double_click_slideshow(view, qtbot, target=("F.mp4", "pF", "aF"))

    view.osr2_control.setChecked(True)

    assert driver.started[-1] == ("pF", "aF")
    slideshow.close()


def test_untoggling_while_a_slideshows_video_drives_stops_the_device(qtbot):
    view, driver, _panel = _osr2_view(qtbot)
    view.osr2_control.setChecked(True)
    slideshow = _double_click_slideshow(view, qtbot, target=("F.mp4", "pF", "aF"))
    assert driver.started

    view.osr2_control.setChecked(False)

    assert driver.stopped >= 1
    slideshow.close()


def test_closing_the_slideshow_stops_driving_with_no_tab_video_behind_it(qtbot):
    view, driver, _panel = _osr2_view(qtbot)
    view.osr2_control.setChecked(True)
    slideshow = _double_click_slideshow(view, qtbot, target=("F.mp4", "pF", "aF"))
    assert driver.started

    slideshow.close()

    assert driver.stopped >= 1


def test_the_slideshows_video_overrides_the_toggle_target_then_hands_back(qtbot):
    # With the toggle already driving the front-tab video, opening a video fullscreen
    # re-aims the one device at the slideshow's player; closing hands it back.
    view, driver, panel = _osr2_view(qtbot)
    panel.osr2_drive_target = lambda: ("A.mp4", "pA", "aA")
    view.osr2_control.setChecked(True)
    assert driver.started[-1] == ("pA", "aA")

    slideshow = _double_click_slideshow(view, qtbot, target=("F.mp4", "pF", "aF"))
    assert driver.started[-1] == ("pF", "aF")

    slideshow.close()
    assert driver.started[-1] == ("pA", "aA")  # back to the toggle's video


def test_a_slideshow_with_nothing_scripted_takes_the_device_off_the_tabs_funscript(qtbot):
    # The surface in front answers for the device alone: a slideshow opening on an
    # image hands the OSR2 to the motion, the way a Funestra hands back to it
    # between scripted videos.  Falling through to the front tab left that tab's
    # funscript driving under a slideshow it has nothing to do with, until the slideshow
    # happened to reach a scripted video of its own.
    view, driver, panel = _osr2_view(qtbot)
    panel.osr2_drive_target = lambda: ("A.mp4", "pA", "aA")
    view.osr2_control.setChecked(True)
    assert driver.started == [("pA", "aA")]

    slideshow = _double_click_slideshow(view, qtbot)  # an image: nothing scripted on screen

    assert driver.stopped >= 1
    assert view._osr2_motion.active
    slideshow.close()


def _driving_the_device(qtbot):
    view, _driver, panel = _osr2_view(qtbot)
    _keys_are_the_gallerys(view)
    panel.osr2_drive_target = lambda: ("A.mp4", "pA", "aA")
    view.osr2_control.setChecked(True)
    return view


def test_esc_pauses_the_room_with_the_focus_inside_a_tab(qtbot):
    # The driven video usually lives in the focused info-pane tab, where the gallery
    # doesn't own Delete/Undo.
    view = _driving_the_device(qtbot)
    view._gallery_owns_keys = lambda **_kw: False

    assert _press_escape(view) is True
    assert omnipause.frozen()
    assert view.osr2_control.isChecked()


def _typing_in_a_text_field(qtbot, monkeypatch):
    field = QLineEdit()
    qtbot.addWidget(field)
    # Said outright rather than clicked into: which widget Qt calls focused is
    # ambient offscreen, and it answers None however the focus was set.
    monkeypatch.setattr(QApplication, "focusWidget", staticmethod(lambda: field))


def test_esc_leaves_an_open_find_its_own_key(qtbot, tmp_path, monkeypatch):
    view, _db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    positive, _negative = _tab_with_prompts(view).prompt_fields()
    positive.setPlainText("a cat")  # something for the find to search
    _press_ctrl_f(view, monkeypatch)
    assert view._find_bar.isVisible()

    assert view._handle_escape() is False
    assert not omnipause.frozen()


@pytest.mark.parametrize("paused", [False, True], ids=["a playing room", "a paused room"])
def test_esc_in_a_text_field_is_the_fields_own_even_with_the_osr2_moving(
        qtbot, monkeypatch, paused):
    # Renaming a folder, writing a prompt: Esc there is how you take it back.
    view = _driving_the_device(qtbot)
    view.set_room_paused(paused)
    _typing_in_a_text_field(qtbot, monkeypatch)

    assert _press_escape(view) is False
    assert omnipause.frozen() is paused


def test_the_console_hints_that_esc_pauses_the_room(qtbot):
    view, _driver, _panel = _osr2_view(qtbot)
    assert view._motion_panel.toolTip().endswith(" · Esc pauses")


def test_esc_defers_to_a_fullscreen_window(qtbot, monkeypatch):
    # A fullscreen preview or the slideshow is a separate top-level window that uses
    # Esc to close. The gallery's app-wide filter sees Esc first, so it must defer
    # when another window is active rather than swallow Esc to stop the OSR2.
    view, driver, panel = _osr2_view(qtbot)
    panel.osr2_drive_target = lambda: ("A.mp4", "pA", "aA")
    view.osr2_control.setChecked(True)
    fullscreen = QWidget()
    qtbot.addWidget(fullscreen)
    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: fullscreen))

    handled = _press_escape(view)

    assert handled is False
    assert driver.stopped == 0


def test_another_active_window_owns_the_keys(qtbot, monkeypatch):
    # The shared guard under both Esc and Delete: when a separate top-level window
    # (a fullscreen preview / the slideshow) is active, the gallery yields its keys.
    view, _driver, _panel = _osr2_view(qtbot)
    # Which window Qt calls active is ambient in a test process — a fullscreen
    # slideshow another test opened and closed can still hold it — so both sides of
    # the guard are said here rather than inherited.
    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: None))
    assert view._other_window_owns_keys() is False  # only the gallery is up

    other = QWidget()
    qtbot.addWidget(other)
    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: other))
    assert view._other_window_owns_keys() is True

    # And a dialog or a combo's dropdown with no window of its own under it: the
    # filter is installed on the application, so without this it eats the keys the
    # popup was opened to take.
    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: None))
    monkeypatch.setattr(QApplication, "activePopupWidget", staticmethod(lambda: other))
    assert view._other_window_owns_keys() is True

    monkeypatch.setattr(QApplication, "activePopupWidget", staticmethod(lambda: None))
    monkeypatch.setattr(QApplication, "activeModalWidget", staticmethod(lambda: other))
    assert view._other_window_owns_keys() is True


def _a_gallery_with_its_slideshow_in_front(qtbot, tmp_path, monkeypatch):
    """A gallery on screen with the sound on and a standalone Slideshow over it,
    active: where a key pressed at the Slideshow lands."""
    monkeypatch.setattr(gallery, "resolve_preview",
                        lambda row, places: ("g0.png", "image"))
    radio = _FakeRadio()
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client(), radio=radio)
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view.show()
    view._bank.radio.setChecked(True)
    view._slideshows.start()
    slideshow = view._slideshows.showing
    qtbot.addWidget(slideshow.shown)
    slideshow.shown.activateWindow()
    QTest.qWaitForWindowActive(slideshow.shown)
    return view, radio, slideshow


def test_esc_at_a_standalone_slideshow_pauses_the_whole_room_and_leaves_it_up(
        qtbot, tmp_path, monkeypatch):
    view, radio, slideshow = _a_gallery_with_its_slideshow_in_front(qtbot, tmp_path, monkeypatch)

    gestures.press_key(slideshow.shown, Qt.Key.Key_Escape)

    assert omnipause.frozen()
    assert radio.frozen
    assert view._slideshows.showing is slideshow
    assert slideshow.shown.isVisible()
    assert view._bank.radio.isChecked()


def test_esc_at_a_standalone_slideshow_has_its_osr2_line_say_parked_until_a_second_plays(
        qtbot, tmp_path, monkeypatch):
    view, _radio, slideshow = _a_gallery_with_its_slideshow_in_front(qtbot, tmp_path, monkeypatch)
    view.osr2_control.setChecked(True)

    gestures.press_key(slideshow.shown, Qt.Key.Key_Escape)
    assert _osr2_line(slideshow) == OSR2_PARKED

    gestures.press_key(slideshow.shown, Qt.Key.Key_Escape)
    assert _osr2_line(slideshow) == Osr2State.ROBOT_HAND


def _osr2_line(slideshow):
    device = slideshow.shown.hud_device
    return state_for(device.osr2, device.osr2_control, paused=device.paused)


def _press_escape_at_the_gallery(view):
    if not view.isActiveWindow():
        view.show()
        view.activateWindow()
        QTest.qWaitForWindowActive(view)
    gestures.press_key(view, Qt.Key.Key_Escape)


def test_esc_in_the_gallery_pauses_the_whole_room_and_a_second_plays_it_again(
        qtbot, tmp_path, monkeypatch):
    view, radio, key = _startable_view(qtbot, tmp_path, monkeypatch)
    del view._other_window_owns_keys
    view._toggle_auto(True)
    view._bank.radio.setChecked(True)

    _press_escape_at_the_gallery(view)
    assert omnipause.frozen()
    assert radio.frozen
    assert view._auto.is_active(key)
    assert view._bank.radio.isChecked()

    _press_escape_at_the_gallery(view)
    assert not omnipause.frozen()
    assert not radio.frozen


def test_esc_in_the_gallery_lights_the_sound_switch_yellow_and_a_second_blue_again(
        qtbot, tmp_path, monkeypatch):
    view, _bed, _key = _startable_view(qtbot, tmp_path, monkeypatch)
    del view._other_window_owns_keys
    view._bank.radio.setChecked(True)

    _press_escape_at_the_gallery(view)
    assert lit_in(view._bank.radio) == "yellow"

    _press_escape_at_the_gallery(view)
    assert lit_in(view._bank.radio) == "blue"


def _startable_view(qtbot, tmp_path, monkeypatch):
    """A gallery on a folder Auto-Generate can run in, idle — the app as it opens."""
    monkeypatch.setattr(gallery, "resolve_preview",
                        lambda row, places: ("g0.png", "image"))
    radio = _FakeRadio()
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client(), radio=radio)
    qtbot.addWidget(view)
    _keys_are_the_gallerys(view)
    view.refresh()
    return view, radio, _select_first_leaf(view)


def test_esc_on_a_freshly_opened_app_pauses_the_room_rather_than_starting_anything(
        qtbot, tmp_path, monkeypatch):
    view, radio, key = _startable_view(qtbot, tmp_path, monkeypatch)
    del view._other_window_owns_keys

    _press_escape_at_the_gallery(view)

    assert omnipause.frozen()
    assert view._slideshows.showing is None
    assert radio.starts == 0
    assert not view._auto.is_active(key)
    assert not view.osr2_control.isChecked()


def test_esc_leaves_the_mic_listening(qtbot, tmp_path, monkeypatch):
    # Speaking is how anything gets going again without reaching for the keyboard.
    view, _bed, _key = _startable_view(qtbot, tmp_path, monkeypatch)
    del view._other_window_owns_keys
    view._bank.mic.setChecked(True)

    _press_escape_at_the_gallery(view)

    assert omnipause.frozen()
    assert view._bank.mic.isChecked()
    assert view._voice.listener.commands_on
