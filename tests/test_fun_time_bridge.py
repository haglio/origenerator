"""The hosted app's file channels: Fun Time's verbs in, occupancy out.

Fun Time speaks to its satellite players through a command file, a paused
flag and a status file; a hosted Origenerator answers the same idioms so the
session's hotkeys reach the region shows and its choreography can see them.
"""

from PIL import Image

from origenerator.fun_time_mode import FunTimeSession, Rect
from origenerator.gui.fun_time_bridge import FunTimeBridge
from origenerator.gui.gallery_view import GalleryView

from tests.test_gallery_view import FakeDB


def _session(tmp_path):
    return FunTimeSession(
        main_rect=Rect(0, 206, 853, 1234),
        portrait_rect=Rect(2560, 0, 1440, 1870),
        landscape_rect=Rect(853, 0, 1707, 1440),
        command_file=tmp_path / "origenerator_cmd.txt",
        paused_file=tmp_path / "origenerator_paused.txt",
        status_file=tmp_path / "origenerator_status.txt",
        dashboard_cmd_file=tmp_path / "dashboard_cmd.txt",
    )


def _view_with_bridge(qtbot, tmp_path):
    view = GalleryView(FakeDB([]), fun_time=_session(tmp_path))
    qtbot.addWidget(view)
    bridge = FunTimeBridge(view._fun_time, view, parent=view)
    return view, bridge


def _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path, count=3):
    still = tmp_path / "tall.png"
    Image.new("RGB", (100, 200)).save(still)
    items = [(str(still), "image", f"id{n}", str(still)) for n in range(count)]
    monkeypatch.setattr(view, "_slideshow_rows", lambda: [object()])
    monkeypatch.setattr(view, "_slideshow_items", lambda rows: list(items))
    monkeypatch.setattr(view, "_slideshow_subject", lambda: "a folder")
    view._start_slideshow()
    show = view.region_show("portrait")
    qtbot.addWidget(show)
    return show


def test_side_verbs_drive_the_show_holding_that_region(qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    before = show._playlist.index

    (tmp_path / "origenerator_cmd.txt").write_text("PORTRAIT_NEXT\n", encoding="utf-8")
    bridge._tick()

    assert show._playlist.index == (before + 1) % 3


def test_a_verb_for_an_empty_region_is_dropped(qtbot, tmp_path):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    (tmp_path / "origenerator_cmd.txt").write_text("LANDSCAPE_TRASH\n", encoding="utf-8")
    bridge._tick()  # nothing holds the landscape region — nothing to crash


def test_lock_verb_holds_the_slide(qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)

    (tmp_path / "origenerator_cmd.txt").write_text("PORTRAIT_LOCK\n", encoding="utf-8")
    bridge._tick()

    assert show.locked


def test_reset_verb_puts_the_side_back_how_it_started(qtbot, tmp_path, monkeypatch):
    """The reset on the shared control band, spoken to a show: the hold
    releases and the top of the set comes back."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    show._playlist.jump_to(2)
    show._toggle_lock()
    assert show.locked

    (tmp_path / "origenerator_cmd.txt").write_text("PORTRAIT_RESET\n", encoding="utf-8")
    bridge._tick()

    assert not show.locked
    assert show._playlist.index == 0


def test_close_shows_clears_both_regions(qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)

    (tmp_path / "origenerator_cmd.txt").write_text("CLOSE_SHOWS\n", encoding="utf-8")
    bridge._tick()

    assert not show.isVisible()
    assert view.region_show("portrait") is None


def test_the_paused_flag_freezes_and_resumes_an_open_show(qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    assert show._timer.isActive()  # an image slide dwells on its timer

    (tmp_path / "origenerator_paused.txt").write_text("1", encoding="utf-8")
    bridge._tick()
    assert not show._timer.isActive()

    (tmp_path / "origenerator_paused.txt").write_text("0", encoding="utf-8")
    bridge._tick()
    assert show._timer.isActive()


def test_status_reports_which_regions_are_occupied(qtbot, tmp_path, monkeypatch):
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    bridge._tick()
    text = (tmp_path / "origenerator_status.txt").read_text(encoding="utf-8")
    assert "portrait_active=0" in text
    assert "landscape_active=0" in text

    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    bridge._tick()
    text = (tmp_path / "origenerator_status.txt").read_text(encoding="utf-8")
    assert "portrait_active=1" in text
    assert "tall.png" in text  # the current item's path rides along
    assert "landscape_active=0" in text

    show.close()
    bridge._tick()
    text = (tmp_path / "origenerator_status.txt").read_text(encoding="utf-8")
    assert "portrait_active=0" in text


def test_a_show_opened_mid_pause_opens_frozen(qtbot, tmp_path, monkeypatch):
    """The room being OmniPaused must hold a show the user opens DURING the
    pause too — the flag edged onto already-open shows once, so a slideshow
    started mid-pause played while everything else in the session stood."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    (tmp_path / "origenerator_paused.txt").write_text("1", encoding="utf-8")
    bridge._tick()

    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)

    assert not show._timer.isActive()  # no dwell armed: it opened frozen


def test_a_step_while_paused_lands_on_a_slide_that_holds(qtbot, tmp_path, monkeypatch):
    """Stepping a frozen show moves it to a new slide, but the new slide must
    arrive holding — re-arming the dwell was the show quietly unpausing
    itself while the rest of the room stayed frozen."""
    view, bridge = _view_with_bridge(qtbot, tmp_path)
    show = _open_portrait_slideshow(qtbot, view, monkeypatch, tmp_path)
    (tmp_path / "origenerator_paused.txt").write_text("1", encoding="utf-8")
    bridge._tick()
    before = show._playlist.index

    (tmp_path / "origenerator_cmd.txt").write_text("PORTRAIT_NEXT\n", encoding="utf-8")
    bridge._tick()

    assert show._playlist.index == (before + 1) % 3  # the step still lands
    assert not show._timer.isActive()                # but the slide holds
