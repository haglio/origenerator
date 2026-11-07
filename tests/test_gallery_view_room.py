from __future__ import annotations

import pytest
from funestra.hud_osr2 import state_for
from funestra.main_hud import (
    OSR2_DRIVING,
    OSR2_PARKED,
    OSR2_RETRACTED,
)
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
from origenerator.gui import generate_tab as generate_tab_module
from origenerator.gui import (
    omnipause,
)
from origenerator.gui.gallery_view import GalleryView, Shared
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
    _reroll_client,
    _resolve_by_id,
    _seeded_db,
    _select_first_leaf,
    _selected_folder,
    _shown_view_with_one_image,
    _SignalMotion,
    _tab_with_prompts,
    _viewport_of,
)
from tests.lit_switches import lit_in
from tests.osr2_fakes import FakeBroker
from tests.slideshow_hud_support import engine_of, funestra_of
from tests.test_fun_time_gallery import _session
from tests.test_osr2_driver import ACTIONS, FakePlayer

pytestmark = pytest.mark.usefixtures("_stub_preview_resolution")



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
        return ()


def _osr2_view(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), client=ComfyUIClient(folders=SUITE_FOLDERS), shared=Shared(osr2_motion=_SignalMotion()))
    qtbot.addWidget(view)
    driver = _FakeDriver()
    view._osr2_driver = driver
    view.osr2_control.script = driver
    return view, driver, view._generate_pane.current_generate_tab()


def test_the_osr2_controls_control_group_is_the_apps_one_osr2_switch(qtbot):
    view, driver, tab = _osr2_view(qtbot)
    tab.osr2_drive_target = lambda: ("A.mp4", "player-A", "actions-A")

    view.osr2_control.set_state(OSR2_DRIVING)
    assert driver.started == [("player-A", "actions-A")]
    assert view.osr2_control.state() == OSR2_DRIVING

    view.osr2_control.set_state(OSR2_PARKED)
    assert driver.stopped == 1
    assert view.osr2_control.isChecked() is False


def test_parking_from_the_osr2_controls_stills_the_motion_at_home_and_keeps_the_device(qtbot):
    view, _driver, _panel = _osr2_view(qtbot)

    view.osr2_control.set_state(OSR2_PARKED)

    assert view.osr2_control.engaged() is True
    assert ("hold", OSR2_PARKED) in view._osr2_motion.calls
    assert view.osr2_control.state() == OSR2_PARKED


def test_a_hold_stands_the_funscript_down_and_puts_the_motion_on_the_device(qtbot):
    view, driver, tab = _osr2_view(qtbot)
    tab.osr2_drive_target = lambda: ("A.mp4", "player-A", "actions-A")
    view.osr2_control.set_state(OSR2_DRIVING)
    assert driver.started
    assert view._osr2_motion.active is False

    view.osr2_control.set_state(OSR2_PARKED)

    assert driver.stopped == 1
    assert view._osr2_motion.active is True
    assert ("hold", OSR2_PARKED) in view._osr2_motion.calls


def test_driving_after_a_hold_gives_the_script_the_device_back(qtbot):
    view, driver, tab = _osr2_view(qtbot)
    tab.osr2_drive_target = lambda: ("A.mp4", "player-A", "actions-A")
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
    log = []
    for name, owner, method in (("script takes", driver, "start"),
                                ("script lets go", driver, "stop"),
                                ("motion takes", view._osr2_motion, "start"),
                                ("motion lets go", view._osr2_motion, "stop")):
        setattr(owner, method, _logging(log, name, getattr(owner, method)))
    return log


def test_the_motion_lets_go_before_the_script_takes_the_device(qtbot):
    view, driver, tab = _osr2_view(qtbot)
    tab.osr2_drive_target = lambda: ("A.mp4", "player-A", "actions-A")
    view.osr2_control.set_state(OSR2_PARKED)
    log = _handoff_log(view, driver)

    view.osr2_control.set_state(OSR2_DRIVING)

    assert log == ["motion lets go", "script takes"]


def test_the_script_lets_go_before_the_motion_takes_the_device(qtbot):
    view, driver, tab = _osr2_view(qtbot)
    tab.osr2_drive_target = lambda: ("A.mp4", "player-A", "actions-A")
    view.osr2_control.set_state(OSR2_DRIVING)
    log = _handoff_log(view, driver)

    view.osr2_control.set_state(OSR2_PARKED)

    assert log == ["script lets go", "motion takes"]


def test_every_osr2_controls_drawing_over_the_device_hears_that_it_was_re_aimed(qtbot):
    view, _driver, _tab = _osr2_view(qtbot)
    heard = []
    view.osr2_control.settled.connect(lambda: heard.append(True))

    view.osr2_control.set_state(OSR2_DRIVING)

    assert heard


def test_global_toggle_drives_the_front_video_and_untoggling_stops(qtbot):
    view, driver, tab = _osr2_view(qtbot)
    tab.osr2_drive_target = lambda: ("A.mp4", "player-A", "actions-A")

    view.osr2_control.setChecked(True)
    assert driver.started == [("player-A", "actions-A")]

    view.osr2_control.setChecked(False)
    assert driver.stopped == 1


def test_toggle_on_with_no_video_shown_moves_instead(qtbot):
    view, driver, tab = _osr2_view(qtbot)
    tab.osr2_drive_target = lambda: None

    view.osr2_control.setChecked(True)
    assert driver.started == []
    assert view._osr2_motion.active

    view.osr2_control.setChecked(False)
    assert view._osr2_motion.held == OSR2_PARKED


def test_space_flips_the_one_switch_rather_than_the_motion_alone(qtbot):
    view, driver, tab = _osr2_view(qtbot)
    tab.osr2_drive_target = lambda: ("A.mp4", "pA", "aA")
    _on_screen(qtbot, view, 1400, 900)
    view.osr2_control.setChecked(True)
    assert driver.started == [("pA", "aA")]
    assert not view._osr2_motion.active

    gestures.press_key(view, Qt.Key.Key_Space)

    assert not view.osr2_control.isChecked()
    assert driver.stopped >= 1
    assert view._osr2_motion.held == OSR2_PARKED


def test_space_after_a_click_in_the_generate_pane_drives_rather_than_pressing_it_again(qtbot):
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
    view, _driver, _panel = _osr2_view(qtbot)
    slideshow = _double_click_slideshow(view, qtbot)
    assert slideshow._actions.drive_toggle == view.toggle_osr2_drive


def test_browsing_to_a_new_video_retargets_the_running_driver(qtbot):
    view, driver, tab = _osr2_view(qtbot)
    tab.osr2_drive_target = lambda: ("A.mp4", "pA", "aA")
    view.osr2_control.setChecked(True)
    assert driver.started[-1] == ("pA", "aA")

    tab.osr2_drive_target = lambda: ("B.mp4", "pB", "aB")
    tab.displayed_changed.emit()
    assert driver.started[-1] == ("pB", "aB")


def test_switching_to_a_tab_without_a_scripted_video_stops_driving(qtbot):
    view, driver, tab = _osr2_view(qtbot)
    tab.osr2_drive_target = lambda: ("A.mp4", "pA", "aA")
    view.osr2_control.setChecked(True)
    assert driver.started

    view._generate_pane._add_subtab()
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
    view = GalleryView(FakeDB([]), actions=FakeActions(), shared=Shared(radio=radio))
    qtbot.addWidget(view)
    return view, radio


def test_the_radio_switch_tunes_the_radio_in_and_silences_it(qtbot):
    view, radio = _radio_view(qtbot)
    assert (radio.starts, radio.stops) == (0, 0)

    view._buttons.radio.setChecked(True)
    assert radio.starts == 1

    view._buttons.radio.setChecked(False)
    assert radio.stops == 1


def test_the_radio_switch_round_trips_for_persistence(qtbot):
    view, radio = _radio_view(qtbot)
    assert view.radio_enabled() is False

    view.set_radio_enabled(True)

    assert view.radio_enabled() is True
    assert view._buttons.radio.isChecked()
    assert radio.starts == 1


def test_the_rooms_pause_reaches_the_radio_and_the_motion(qtbot):
    radio, motion = _FakeRadio(), _SignalMotion()
    view = GalleryView(FakeDB([]), actions=FakeActions(), shared=Shared(radio=radio, osr2_motion=motion))
    qtbot.addWidget(view)

    view.set_room_paused(True)
    assert (radio.frozen, motion.frozen) == (True, True)

    view.set_room_paused(False)
    assert (radio.frozen, motion.frozen) == (False, False)


def test_the_rooms_pause_holds_a_scripted_videos_drive_still(qtbot, monkeypatch):
    broker = FakeBroker()
    monkeypatch.setattr(osr2_driver, "Osr2Broker", lambda *a, **k: broker)
    view = GalleryView(FakeDB([]), actions=FakeActions(), shared=Shared(osr2_motion=_SignalMotion()))
    qtbot.addWidget(view)
    tab = view._generate_pane.current_generate_tab()
    tab.osr2_drive_target = lambda: ("A.mp4", FakePlayer(pos=100), ACTIONS)
    view.osr2_control.setChecked(True)

    view.set_room_paused(True)
    view.osr2_control.script.poll()

    assert broker.positions == []


def test_a_double_click_plays_the_visible_folder_in_its_own_order(qtbot, monkeypatch):
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
    view._on_thumbnail_clicked("i2")

    slideshow = _double_click_slideshow(view, qtbot)

    order = view._gallery_pane.listed_prompt_ids()
    assert slideshow._set.playlist._items == [(f"{pid}.png", "image", pid, None)
                                          for pid in order]
    assert slideshow._set.playlist.order == list(range(len(order)))
    assert slideshow._set.playlist.current()[2] == "i2"
    slideshow.close()


def test_a_double_click_while_auto_generate_runs_opens_on_the_shown_image_alone(
        qtbot, tmp_path, monkeypatch):
    def by_id(row, places):
        return (f"{row['prompt_id']}.png", "image")
    monkeypatch.setattr(gallery, "resolve_preview", by_id)
    monkeypatch.setattr(generate_tab_module, "resolve_preview", by_id)
    client = _reroll_client()
    view = GalleryView(_seeded_db(tmp_path), client=client)
    qtbot.addWidget(view)
    view.refresh()
    key = _select_first_leaf(view)
    view._buttons.auto.click()
    _generating_tile(view).selected.emit()
    landed = view._live_jobs[key].prompt_id
    client.job_completed.emit(landed, _REROLL_HISTORY)

    slideshow = _viewport_of(view).open_fullscreen()
    qtbot.addWidget(slideshow.shown)
    funestra_of(slideshow.shown)

    assert [slide.prompt_id for slide in slideshow._set.playlist.in_play_order()] == [landed]
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

    slideshow = view._slideshows.open_in_its_folder(("b1.png", "image"), "b1")
    qtbot.addWidget(slideshow.shown)

    assert [slide.prompt_id for slide in slideshow._set.playlist.in_play_order()] == folder_b
    assert slideshow._set.playlist.current().prompt_id == "b1"
    slideshow.close()


def test_stepping_a_double_clicked_slideshow_re_aims_the_osr2(qtbot):
    view, driver, _panel = _osr2_view(qtbot)
    view.osr2_control.setChecked(True)
    slideshow = _double_click_slideshow(view, qtbot, target=("A.mp4", "pA", "aA"))
    assert driver.started[-1] == ("pA", "aA")

    _aim_slideshow(view, slideshow, ("B.mp4", "pB", "aB"))
    assert driver.started[-1] == ("pB", "aB")
    slideshow.close()


def test_a_slideshow_opened_with_the_switch_off_drives_nothing(qtbot):
    view, driver, _panel = _osr2_view(qtbot)
    slideshow = _double_click_slideshow(view, qtbot, target=("A.mp4", "pA", "aA"))

    assert driver.started == []
    slideshow.close()



def test_the_video_in_front_is_the_front_tab_s_while_no_slideshow_is_up(qtbot):
    view, _driver, tab = _osr2_view(qtbot)
    tab.video_on_screen = lambda: "alpha-1"

    assert view.video_in_front() == "alpha-1"


def test_a_slideshow_up_is_what_is_in_front_of_the_tab(qtbot):
    view, _driver, tab = _osr2_view(qtbot)
    tab.video_on_screen = lambda: "alpha-1"
    slideshow = _double_click_slideshow(view, qtbot)
    slideshow.video_on_screen = lambda: "beta-1"

    assert view.video_in_front() == "beta-1"
    slideshow.close()
    assert view.video_in_front() == "alpha-1"



def _auto_generating_view(qtbot, monkeypatch, rows):
    view = GalleryView(FakeDB(rows), actions=FakeActions(), client=ComfyUIClient(folders=SUITE_FOLDERS), shared=Shared(osr2_motion=_SignalMotion()))
    qtbot.addWidget(view)
    view.refresh()
    _open_leaf(view)
    key = _selected_folder(view)
    monkeypatch.setattr(view._auto, "is_active", lambda k: k == key)
    return view, key


def test_double_clicking_a_generating_preview_opens_it_fullscreen(qtbot, monkeypatch):
    _resolve_by_id(monkeypatch)
    view, _key = _auto_generating_view(qtbot, monkeypatch, [_image("i1", "a cat", 50, 1)])
    tab = view._generate_pane.current_generate_tab()
    tab._viewport.show_frame(_png_bytes())

    win = tab._viewport.open_fullscreen()

    qtbot.addWidget(win.shown)
    assert win is not None
    assert view._slideshows.showing is win
    assert [slide.prompt_id for slide in win.whole_set()] == ["i1"]
    win.close()


def test_a_slideshow_closed_before_it_became_active_asks_for_no_keyboard_focus(qtbot, monkeypatch):
    _view, slideshow = _a_slideshow_standing_on_its_own(qtbot, monkeypatch)
    window = slideshow.shown

    window.close()
    QApplication.processEvents()
    window.show()

    assert window.focusWidget() is None


def test_a_funscript_coming_into_view_takes_the_device_off_the_motion(qtbot, monkeypatch):
    view, _key = _auto_generating_view(qtbot, monkeypatch, [_image("i1", "a cat", 50, 1)])
    driver = _FakeDriver()
    view._osr2_driver = driver
    tab = view._generate_pane.current_generate_tab()
    tab.osr2_drive_target = lambda: None

    view.osr2_control.setChecked(True)
    assert view._osr2_motion.active
    assert driver.started == []

    tab.osr2_drive_target = lambda: ("A.mp4", "pA", "aA")
    tab.displayed_changed.emit()

    assert driver.started == [("pA", "aA")]
    assert not view._osr2_motion.active


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

    assert view._buttons.radio.isChecked()
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

    second = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), actions=FakeActions(), client=ComfyUIClient(folders=SUITE_FOLDERS), shared=Shared(radio=_FakeRadio()))
    qtbot.addWidget(second)
    second.remember_slideshows(saved)
    second.refresh()
    _open_leaf(second)
    second._slideshows.start()
    qtbot.addWidget(second._slideshows.showing.shown)

    engine = engine_of(second._slideshows.showing.shown)
    assert (engine.volume, engine.muted) == (40, True)


def _click_the_slide(slideshow):
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
    _resolve_by_id(monkeypatch)
    view, _key = _auto_generating_view(qtbot, monkeypatch, [_image("i1", "a cat", 50, 1)])
    view._slideshows.start()
    qtbot.addWidget(view._slideshows.showing.shown)
    assert view._slideshows.showing._actions.drive_toggle == view.toggle_osr2_drive
    view.osr2_control.setChecked(True)
    view._slideshows.showing.close()
    assert view._osr2_motion.active


def test_esc_holds_a_running_motion_still(qtbot, monkeypatch):
    view, _key = _auto_generating_view(qtbot, monkeypatch, [_image("i1", "a cat", 50, 1)])
    # Qt's active window outlives the test that opened it.
    monkeypatch.setattr(view, "_other_window_owns_keys", lambda: False)
    view.osr2_control.setChecked(True)
    assert view._osr2_motion.active
    assert view._handle_escape(Qt.KeyboardModifier.NoModifier) is True
    assert view._osr2_motion.frozen


def test_the_motion_keys_work_in_core_too(qtbot, monkeypatch):
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
    view, driver, _panel = _osr2_view(qtbot)
    assert not view.osr2_control.isChecked()

    slideshow = _double_click_slideshow(view, qtbot, target=("F.mp4", "pF", "aF"))

    assert driver.started == []
    slideshow.close()


def test_turning_the_toggle_on_over_an_open_slideshow_drives_its_video(qtbot):
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
    view, driver, tab = _osr2_view(qtbot)
    tab.osr2_drive_target = lambda: ("A.mp4", "pA", "aA")
    view.osr2_control.setChecked(True)
    assert driver.started[-1] == ("pA", "aA")

    slideshow = _double_click_slideshow(view, qtbot, target=("F.mp4", "pF", "aF"))
    assert driver.started[-1] == ("pF", "aF")

    slideshow.close()
    assert driver.started[-1] == ("pA", "aA")


def test_a_slideshow_with_nothing_scripted_takes_the_device_off_the_tabs_funscript(qtbot):
    view, driver, tab = _osr2_view(qtbot)
    tab.osr2_drive_target = lambda: ("A.mp4", "pA", "aA")
    view.osr2_control.setChecked(True)
    assert driver.started == [("pA", "aA")]

    slideshow = _double_click_slideshow(view, qtbot)

    assert driver.stopped >= 1
    assert view._osr2_motion.active
    slideshow.close()


def _driving_the_device(qtbot):
    view, _driver, tab = _osr2_view(qtbot)
    _keys_are_the_gallerys(view)
    tab.osr2_drive_target = lambda: ("A.mp4", "pA", "aA")
    view.osr2_control.setChecked(True)
    return view


def test_esc_pauses_the_room_with_the_focus_inside_a_tab(qtbot):
    view = _driving_the_device(qtbot)
    view._gallery_owns_keys = lambda **_kw: False

    assert _press_escape(view) is True
    assert omnipause.frozen()
    assert view.osr2_control.isChecked()


def _typing_in_a_text_field(qtbot, monkeypatch):
    field = QLineEdit()
    qtbot.addWidget(field)
    # Offscreen, Qt's focusWidget answers None however the focus was set.
    monkeypatch.setattr(QApplication, "focusWidget", staticmethod(lambda: field))


def test_esc_leaves_an_open_find_its_own_key(qtbot, tmp_path, monkeypatch):
    view, _db, _file = _shown_view_with_one_image(qtbot, tmp_path)
    positive, _negative = _tab_with_prompts(view).prompt_fields()
    positive.setPlainText("a cat")
    _press_ctrl_f(view, monkeypatch)
    assert view._find_bar.isVisible()

    assert view._handle_escape(Qt.KeyboardModifier.NoModifier) is False
    assert not omnipause.frozen()


@pytest.mark.parametrize("paused", [False, True], ids=["a playing room", "a paused room"])
def test_esc_in_a_text_field_is_the_fields_own_even_with_the_osr2_moving(
        qtbot, monkeypatch, paused):
    view = _driving_the_device(qtbot)
    view.set_room_paused(paused)
    _typing_in_a_text_field(qtbot, monkeypatch)

    assert _press_escape(view) is False
    assert omnipause.frozen() is paused


def test_the_osr2_controls_hint_that_esc_pauses_the_room(qtbot):
    view, _driver, _panel = _osr2_view(qtbot)
    assert view._osr2_controls.toolTip().endswith(" · Esc pauses")


def test_esc_defers_to_a_fullscreen_window(qtbot, monkeypatch):
    view, driver, tab = _osr2_view(qtbot)
    tab.osr2_drive_target = lambda: ("A.mp4", "pA", "aA")
    view.osr2_control.setChecked(True)
    fullscreen = QWidget()
    qtbot.addWidget(fullscreen)
    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: fullscreen))

    handled = _press_escape(view)

    assert handled is False
    assert driver.stopped == 0


def test_another_active_window_owns_the_keys(qtbot, monkeypatch):
    view, _driver, _panel = _osr2_view(qtbot)
    # Qt's active window outlives the test that opened it.
    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: None))
    assert view._other_window_owns_keys() is False

    other = QWidget()
    qtbot.addWidget(other)
    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: other))
    assert view._other_window_owns_keys() is True

    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: None))
    monkeypatch.setattr(QApplication, "activePopupWidget", staticmethod(lambda: other))
    assert view._other_window_owns_keys() is True

    monkeypatch.setattr(QApplication, "activePopupWidget", staticmethod(lambda: None))
    monkeypatch.setattr(QApplication, "activeModalWidget", staticmethod(lambda: other))
    assert view._other_window_owns_keys() is True


def _a_gallery_with_its_slideshow_in_front(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(gallery, "resolve_preview",
                        lambda row, places: ("g0.png", "image"))
    radio = _FakeRadio()
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client(), shared=Shared(radio=radio))
    qtbot.addWidget(view)
    view.refresh()
    _select_first_leaf(view)
    view.show()
    view._buttons.radio.setChecked(True)
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
    assert view._buttons.radio.isChecked()


def test_shift_esc_at_a_standalone_slideshow_closes_it_and_leaves_the_room_playing(
        qtbot, tmp_path, monkeypatch):
    _view, radio, slideshow = _a_gallery_with_its_slideshow_in_front(qtbot, tmp_path, monkeypatch)

    gestures.press_key(slideshow.shown, Qt.Key.Key_Escape, Qt.KeyboardModifier.ShiftModifier)

    qtbot.waitUntil(lambda: not slideshow.shown.isVisible())
    assert not omnipause.frozen()
    assert not radio.frozen


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
    view._buttons.radio.setChecked(True)

    _press_escape_at_the_gallery(view)
    assert omnipause.frozen()
    assert radio.frozen
    assert view._auto.is_active(key)
    assert view._buttons.radio.isChecked()

    _press_escape_at_the_gallery(view)
    assert not omnipause.frozen()
    assert not radio.frozen


def test_esc_in_the_gallery_lights_the_sound_switch_yellow_and_a_second_blue_again(
        qtbot, tmp_path, monkeypatch):
    view, _bed, _key = _startable_view(qtbot, tmp_path, monkeypatch)
    del view._other_window_owns_keys
    view._buttons.radio.setChecked(True)

    _press_escape_at_the_gallery(view)
    assert lit_in(view._buttons.radio) == "yellow"

    _press_escape_at_the_gallery(view)
    assert lit_in(view._buttons.radio) == "blue"


def _startable_view(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(gallery, "resolve_preview",
                        lambda row, places: ("g0.png", "image"))
    radio = _FakeRadio()
    view = GalleryView(_seeded_db(tmp_path), client=_reroll_client(), shared=Shared(radio=radio))
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


def test_shift_esc_in_the_gallery_opens_the_slideshow_a_double_click_would_and_leaves_the_room_playing(
        qtbot, tmp_path, monkeypatch):
    view, _radio, _key = _startable_view(qtbot, tmp_path, monkeypatch)
    _viewport_of(view).show_frame(_png_bytes())
    view.show()
    view.activateWindow()
    QTest.qWaitForWindowActive(view)

    gestures.press_key(view, Qt.Key.Key_Escape, Qt.KeyboardModifier.ShiftModifier)

    slideshow = view._slideshows.showing
    assert slideshow is not None
    qtbot.addWidget(slideshow.shown)
    assert not omnipause.frozen()
    slideshow.close()


def test_esc_leaves_the_mic_listening(qtbot, tmp_path, monkeypatch):
    view, _bed, _key = _startable_view(qtbot, tmp_path, monkeypatch)
    del view._other_window_owns_keys
    view._buttons.mic.setChecked(True)

    _press_escape_at_the_gallery(view)

    assert omnipause.frozen()
    assert view._buttons.mic.isChecked()
    assert view._voice.listener.commands_on


def test_a_reconcile_with_nothing_changed_leaves_the_driver_running(qtbot):
    view, driver, tab = _osr2_view(qtbot)
    tab.osr2_drive_target = lambda: ("A.mp4", "player-A", "actions-A")
    view.osr2_control.set_state(OSR2_DRIVING)

    view.reconcile_osr2()

    assert driver.started == [("player-A", "actions-A")]


def test_the_same_video_on_a_new_player_re_aims_the_driver(qtbot):
    view, driver, tab = _osr2_view(qtbot)
    tab.osr2_drive_target = lambda: ("A.mp4", "player-A", "actions-A")
    view.osr2_control.set_state(OSR2_DRIVING)

    tab.osr2_drive_target = lambda: ("A.mp4", "player-B", "actions-A")
    view.reconcile_osr2()

    assert driver.started[-1] == ("player-B", "actions-A")


def test_a_listener_reconciling_on_the_settled_signal_does_not_land_back_in_the_reconcile(qtbot):
    view, driver, tab = _osr2_view(qtbot)
    tab.osr2_drive_target = lambda: ("A.mp4", "player-A", "actions-A")
    heard = []
    view.osr2_control.settled.connect(lambda: heard.append(view.reconcile_osr2()))

    view.osr2_control.set_state(OSR2_DRIVING)

    assert heard
    assert driver.started == [("player-A", "actions-A")]


def test_quitting_lets_go_of_the_script_the_motion_and_the_radio(qtbot):
    radio = _FakeRadio()
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), shared=Shared(osr2_motion=_SignalMotion(), radio=radio))
    qtbot.addWidget(view)
    view._osr2_driver.start(FakePlayer(), ACTIONS)
    view._osr2_motion.active = True

    QApplication.instance().aboutToQuit.emit()

    assert not view._osr2_driver.active
    assert not view._osr2_motion.active
    assert radio.stops == 1


def test_a_hosted_gallery_says_its_mic_is_off_since_the_session_owns_the_room_s_microphone(qtbot):
    view = GalleryView(FakeDB([]), fun_time=_session())
    qtbot.addWidget(view)

    assert view.mic_enabled() is False
