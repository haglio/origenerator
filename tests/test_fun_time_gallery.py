"""The gallery inside a Fun Time session: no OSR2 anywhere, vertical layout.

Fun Time's main player owns the OSR2 for the whole session, so a hosted
Origenerator must offer no way to reach the device — no toggle, no stroke, no
console — and its layout folds to fit the Random Favs Browser's upright rect.
"""

from PIL import Image
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QSplitter

from origenerator.fun_time_mode import FunTimeSession, Rect
from origenerator.gui.gallery_view import GalleryView

from tests.test_gallery_view import FakeDB, _image  # the in-memory Database stand-in, and a row for it


def _session(tmp_path=None):
    return FunTimeSession(
        main_rect=Rect(0, 206, 853, 1234),
        portrait_rect=Rect(2560, 0, 1440, 1870),
        landscape_rect=Rect(853, 0, 1707, 1440),
        command_file=None, paused_file=None, status_file=None,
        dashboard_cmd_file=None,
    )


def _fun_time_view(qtbot, rows=()):
    view = GalleryView(FakeDB(list(rows)), fun_time=_session())
    qtbot.addWidget(view)
    return view


def test_fun_time_gallery_builds_no_shared_appliance_switches(qtbot):
    """The room's audio and its microphone are the session's, not this app's:
    the main player owns the sound and Fun Time owns the mic (it hears this
    app's spoken commands too and posts them on the channel), so a second
    switch for either would be a switch over something this window does not
    hold."""
    view = _fun_time_view(qtbot)
    assert view._audio_btn is None
    assert view._mic_btn is None
    view.set_audio_enabled(True)   # a stale standalone session key must not crash
    assert view.audio_enabled() is False


def test_fun_time_gallery_builds_no_osr2_surface(qtbot):
    view = _fun_time_view(qtbot)
    assert view._osr2_stroke is None
    assert view._osr2_driver is None
    assert view._osr2_btn is None
    assert view._stroke_panel is None


def test_fun_time_gallery_ignores_the_stroke_keys(qtbot):
    # Space and friends belong to Fun Time's own hotkeys while hosted; nothing
    # here may swallow them, let alone drive the device.
    view = _fun_time_view(qtbot)
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtCore import QEvent
    view.show()
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_J,
                      Qt.KeyboardModifier.NoModifier)
    assert view.eventFilter(view, event) is False


def test_fun_time_gallery_restores_osr2_state_as_a_no_op(qtbot):
    view = _fun_time_view(qtbot)
    view.set_osr2_enabled(True)  # a stale standalone session key must not crash
    assert view.osr2_enabled() is False


def test_fun_time_gallery_stacks_generate_tabs_under_the_browser(qtbot):
    # The RFB rect is an upright column, so the side-by-side panes fold: folder
    # tree on the left, and the generate tabs UNDER the browser pane.
    view = _fun_time_view(qtbot)
    assert view._panes.count() == 2
    stack = view._panes.widget(1)
    assert isinstance(stack, QSplitter)
    assert stack.orientation() == Qt.Orientation.Vertical
    assert stack.count() == 2
    # The stack's upper pane is the folder column (browser over the queue
    # strip), its lower one the info-pane wrapper (tabs + the find bar).
    assert stack.widget(0) is view._left_column
    assert stack.widget(1).findChild(type(view._info_tabs)) is view._info_tabs


def test_fun_time_gallery_left_pane_collapses_on_its_toggle(qtbot):
    view = _fun_time_view(qtbot)
    view.show()
    toc = view._panes.widget(0)
    view._toc_toggle.click()
    assert not toc.isVisible()
    view._toc_toggle.click()
    assert toc.isVisible()


def test_standalone_gallery_keeps_its_panes_side_by_side(qtbot):
    """Standalone the folder column and the info pane sit beside each other,
    with the tree inside that column rather than out on the window's edge."""
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    assert view._panes.count() == 2
    assert view._panes.widget(0) is view._left_column
    # The second pane is the info-pane wrapper (tabs + the find bar).
    assert view._panes.widget(1).findChild(type(view._info_tabs)) is view._info_tabs
    assert view._folder_panes.count() == 2  # the tree, then the browser
    assert view._toc_toggle is None  # the collapse toggle is Fun Time mode's


def _open_slideshow(view, monkeypatch, tmp_path, name, width, height, count=1):
    still = tmp_path / f"{name}.png"
    Image.new("RGB", (width, height)).save(still)
    items = [(str(still), "image", f"id-{name}-{n}", str(still))
             for n in range(count)]
    monkeypatch.setattr(view, "_slideshow_rows", lambda: [object()])
    monkeypatch.setattr(view, "_slideshow_items", lambda rows: list(items))
    monkeypatch.setattr(view, "_slideshow_subject", lambda: name)
    view._start_slideshow()


def test_slideshow_lands_in_the_region_matching_its_orientation(qtbot, tmp_path, monkeypatch):
    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200)
    show = view._region_shows["portrait"]
    assert show is not None and show.isVisible()
    assert show.windowTitle() == "Origenerator Portrait"
    assert show.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert show.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    geo = show.geometry()
    assert (geo.width(), geo.height()) == (1440, 1870)
    qtbot.addWidget(show)


def test_both_regions_can_hold_a_show_at_once(qtbot, tmp_path, monkeypatch):
    # The whole point of sending shows to the satellite regions: the main
    # window stays usable while up to two slideshows run.
    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200)
    _open_slideshow(view, monkeypatch, tmp_path, "wide", 200, 100)
    portrait = view._region_shows["portrait"]
    landscape = view._region_shows["landscape"]
    assert portrait is not None and portrait.isVisible()
    assert landscape is not None and landscape.isVisible()
    assert portrait is not landscape
    for show in (portrait, landscape):
        qtbot.addWidget(show)


def test_a_new_show_replaces_the_regions_current_occupant(qtbot, tmp_path, monkeypatch):
    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, "first", 100, 200)
    first = view._region_shows["portrait"]
    _open_slideshow(view, monkeypatch, tmp_path, "second", 90, 200)
    second = view._region_shows["portrait"]
    assert second is not first
    assert not first.isVisible()
    assert second.isVisible()
    for show in (first, second):
        qtbot.addWidget(show)


def test_a_preview_double_click_lands_its_show_on_the_matching_region(qtbot, tmp_path):
    """A double-click on a tab's preview opens the folder as a show — hosted,
    that show lands on the region its media belongs to rather than taking over
    whichever monitor the click happened on."""
    view = _fun_time_view(qtbot)
    wide = tmp_path / "wide.png"
    Image.new("RGB", (200, 100)).save(wide)

    show = view._open_slideshow_on_preview((str(wide), "image"), None)

    qtbot.addWidget(show)
    assert view.region_show("landscape") is show
    assert show.windowTitle() == "Origenerator Landscape"


def test_a_region_show_is_muted_like_every_satellite(qtbot, tmp_path):
    # Standalone, the show is the deliberate foreground and plays sound; on a
    # satellite region the session's main player owns the room's audio, and the
    # satellites are silent by design — so the hosted show is too.
    view = _fun_time_view(qtbot)
    wide = tmp_path / "wide.png"
    Image.new("RGB", (200, 100)).save(wide)

    show = view._open_slideshow_on_preview((str(wide), "image"), None)

    qtbot.addWidget(show)
    assert show.audio_muted()


def test_a_presented_show_takes_the_keyboard(qtbot):
    # The show must answer its own keys the moment it opens — left unfocused,
    # its arrows land in the main window and the view reads as dead.  The
    # offscreen platform cannot express real activation, so the contract is
    # pinned at the seam: presenting raises and activates the window.
    from PyQt6.QtWidgets import QWidget

    view = _fun_time_view(qtbot)
    stub = QWidget()
    qtbot.addWidget(stub)
    calls: list[str] = []
    stub.raise_ = lambda: calls.append("raise")
    stub.activateWindow = lambda: calls.append("activate")
    view._present_surface(stub, "portrait")
    assert calls == ["raise", "activate"]


def test_a_preview_double_click_opens_the_show_on_a_region(qtbot, tmp_path):
    # End to end from the gesture: the info-pane preview's double-click, hosted,
    # lands the show it opens on the region matching the media.
    view = _fun_time_view(qtbot)
    view.show()
    panel = view._info_tabs.current_config_panel()
    wide = tmp_path / "wide.png"
    Image.new("RGB", (200, 100)).save(wide)
    panel._preview.show_media(str(wide), "image")

    from PyQt6.QtCore import QPoint
    qtbot.mouseDClick(panel._preview, Qt.MouseButton.LeftButton,
                      pos=QPoint(panel._preview.width() // 2,
                                 panel._preview.height() // 2))

    show = view.region_show("landscape")
    assert show is not None and show.isVisible()
    geo = show.geometry()
    assert (geo.width(), geo.height()) == (1707, 1440)
    qtbot.addWidget(show)


def test_a_presented_show_wears_the_players_own_hud(qtbot, tmp_path, monkeypatch):
    """The show covers the satellite player's HUD, so it wears the players'
    own — the same panel from the same shared code: mode pair, transport, and
    the nav map speaking the set as a seed family.  The view's own furnishings
    come off; the map says all of it."""
    from origenerator.gui.show_hud import ShowHud

    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200)
    show = view._region_shows["portrait"]
    qtbot.addWidget(show)

    hud, = show.findChildren(ShowHud)
    assert hud._targets is not None
    # The mode pair is on it — the way back to player mode from atop a show.
    assert [command for _rect, command in hud._targets.modes] == [
        "players_activate", "origenerator_activate"]
    # The transport controls are the players' own set.
    control_names = {name for _rect, name in hud._targets.control}
    assert {"prev", "next", "lock", "trash"} <= control_names
    # The furnishings the map replaces are off.
    assert show._counter.isHidden()

    # A transport press posts on the session's channel, exactly as a player's
    # HUD posts it; a player-only concept (minimize) is swallowed.
    hud._deliver("portrait_next")
    hud._deliver("portrait_minimize")
    posted = (tmp_path / "dashboard_cmd.txt").read_text(encoding="utf-8").split()
    assert posted == ["portrait_next"]


def _session_with_dashboard(tmp_path):
    return FunTimeSession(
        main_rect=Rect(0, 206, 853, 1234),
        portrait_rect=Rect(2560, 0, 1440, 1870),
        landscape_rect=Rect(853, 0, 1707, 1440),
        command_file=None, paused_file=None, status_file=None,
        dashboard_cmd_file=tmp_path / "dashboard_cmd.txt",
    )


def test_the_huds_map_names_the_set_in_the_players_vocabulary(qtbot, tmp_path, monkeypatch):
    """Seeds: N in the counts corner, Seed ordinals over the columns, the item
    on screen the lit cell — the slideshow's set drawn exactly as a player
    draws a seed family."""
    from origenerator.gui.show_hud import show_hud_model

    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200, count=3)
    show = view._region_shows["portrait"]
    qtbot.addWidget(show)

    model = show_hud_model("portrait", show)
    assert model.seed_count == 3          # "Seeds: 3" in the counts corner
    assert model.corner is not None and len(model.seeds) == 2
    position = show._playlist.order[show._playlist.index] + 1
    expected = ("corner", 0) if position == 1 else ("seed", position - 2)
    assert model.playing == expected      # the item on screen is the lit cell
    assert model.satellites_mode == "origenerator"
    assert model.locked is False

    show.stroke_toggle_hold()
    assert show_hud_model("portrait", show).locked is True


def test_a_hud_map_click_jumps_the_show_to_that_item(qtbot, tmp_path, monkeypatch):
    """A thumbnail click switches a player to that clip; on a show it jumps the
    set to that item — and the double-click's lock holds it there."""
    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    still_b = tmp_path / "b.png"
    Image.new("RGB", (100, 200)).save(still_b)
    items = [(str(tmp_path / "tall.png"), "image", "id-a", str(tmp_path / "tall.png")),
             (str(still_b), "image", "id-b", str(still_b))]
    Image.new("RGB", (100, 200)).save(tmp_path / "tall.png")
    monkeypatch.setattr(view, "_slideshow_rows", lambda: [object()])
    monkeypatch.setattr(view, "_slideshow_items", lambda rows: list(items))
    monkeypatch.setattr(view, "_slideshow_subject", lambda: "a folder")
    view._start_slideshow()
    show = view._region_shows["portrait"]
    qtbot.addWidget(show)

    show.show_item(str(still_b), hold=True)

    assert show._playlist.current()[0] == str(still_b)
    assert show.locked


def test_a_recents_slideshow_plays_latest_not_shuffled(qtbot, tmp_path, monkeypatch):
    """Recents is the players' Latest: the shelf lists newest first and its
    slideshow plays that order, where every other set shuffles — and the
    show's HUD status line says which."""
    from origenerator.gui.gallery_tree import RECENTS_KEY

    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    monkeypatch.setattr(view, "_current_shelf_key", lambda: RECENTS_KEY)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200, count=3)
    show = view._region_shows["portrait"]
    qtbot.addWidget(show)

    assert show._playlist.order == [0, 1, 2]  # the listing's own order, unshuffled
    assert show.hud_order_label == "Latest"


def test_f_mode_on_a_show_narrows_the_set_to_the_favorites(qtbot, tmp_path, monkeypatch):
    """The players' F-mode, meaning on a show what it means on a player:
    narrow to the favorites — the starred items, the same collection the
    Favorites shelf lists — and widen back on the second press."""
    from origenerator.gui.show_hud import ShowHud, show_hud_model

    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    monkeypatch.setattr(view, "_starred_prompt_ids", lambda: {"id-tall-1"})
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200, count=3)
    show = view._region_shows["portrait"]
    qtbot.addWidget(show)
    hud, = show.findChildren(ShowHud)

    hud._deliver("portrait_fmode")

    assert show.hud_f_mode is True
    cells, _position, _locked = show.hud_items()
    assert len(cells) == 1  # narrowed to the one favorite
    model = show_hud_model("portrait", show)
    assert model.f_mode is True and "F-Mode" in model.lock_label

    hud._deliver("portrait_fmode")
    cells, _position, _locked = show.hud_items()
    assert len(cells) == 3  # widened back
    # The star readout lights exactly on the favorite item.  (Every fixture
    # item shares one file, so land on it by position, not by path.)
    show._playlist.jump_to(1)
    assert show.hud_is_favorite is True
    show._playlist.jump_to(0)
    assert show.hud_is_favorite is False


def test_a_hosted_show_keeps_up_with_its_own_folder(qtbot, tmp_path, monkeypatch):
    """A show plays on a satellite region while the main window goes on being
    used, so by the time an auto-generated item lands the browser is usually
    elsewhere — and both regions may be playing different folders.  Each show
    is fed from the location IT opened at, not from the view on screen."""
    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200)
    portrait = view.region_show("portrait")
    qtbot.addWidget(portrait)
    # The show opened from a folder; the browser has since moved off it.
    view._live_shows = [(portrait, "folder-a")]
    landed = {"prompt_id": "new-1"}
    monkeypatch.setattr(view, "_rows_at",
                        lambda key: [landed] if key == "folder-a" else [])
    still = tmp_path / "new.png"
    Image.new("RGB", (100, 200)).save(still)
    monkeypatch.setattr(view, "_slideshow_items",
                        lambda rows: [(str(still), "image", "new-1", str(still))])
    before = len(portrait.hud_items()[0])

    view._feed_slideshow_finished(landed)

    assert len(portrait.hud_items()[0]) == before + 1


def test_a_landing_reaches_only_the_show_playing_its_folder(qtbot, tmp_path, monkeypatch):
    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200)
    _open_slideshow(view, monkeypatch, tmp_path, "wide", 200, 100)
    portrait, landscape = view.region_show("portrait"), view.region_show("landscape")
    for show in (portrait, landscape):
        qtbot.addWidget(show)
    view._live_shows = [(portrait, "folder-a"), (landscape, "folder-b")]
    landed = {"prompt_id": "new-1"}
    monkeypatch.setattr(view, "_rows_at",
                        lambda key: [landed] if key == "folder-b" else [])
    still = tmp_path / "new.png"
    Image.new("RGB", (200, 100)).save(still)
    monkeypatch.setattr(view, "_slideshow_items",
                        lambda rows: [(str(still), "image", "new-1", str(still))])
    counts = [len(portrait.hud_items()[0]), len(landscape.hud_items()[0])]

    view._feed_slideshow_finished(landed)

    assert len(portrait.hud_items()[0]) == counts[0]        # not its folder
    assert len(landscape.hud_items()[0]) == counts[1] + 1   # its folder


def test_a_spoken_side_and_shelf_plays_it_on_that_region(qtbot, tmp_path, monkeypatch):
    """"landscape favorites": the Favorites shelf's landscape items, on the
    landscape region — a show STARTED by voice, with nothing up beforehand and
    the browser left wherever it was."""
    from origenerator.voice.commands import ShelfCommand

    view = _fun_time_view(qtbot)
    still = tmp_path / "wide.png"
    Image.new("RGB", (200, 100)).save(still)
    rows = [{"prompt_id": "fav-1", "thumbnail_path": str(still)}]
    monkeypatch.setattr(view._browser, "rows_for_shelf",
                        lambda key: rows if key == "__starred__::landscape" else [])
    monkeypatch.setattr(view, "_slideshow_items",
                        lambda r: [(str(still), "image", row["prompt_id"], str(still))
                                   for row in r])

    view._on_voice_command(ShelfCommand("__starred__", "landscape"))

    show = view.region_show("landscape")
    assert show is not None and show.isVisible()
    assert view.region_show("portrait") is None  # the other region is untouched
    qtbot.addWidget(show)


def test_a_spoken_fix_names_which_region_it_means(qtbot, tmp_path, monkeypatch):
    """"landscape fix teeth": hosted, two shows run and NEITHER is the active
    window, so the side word is the only thing that says which picture."""
    from origenerator.gallery.detail_parts import DETAIL_PARTS
    from origenerator.voice.commands import SurfaceCommand

    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200)
    _open_slideshow(view, monkeypatch, tmp_path, "wide", 200, 100)
    portrait, landscape = view.region_show("portrait"), view.region_show("landscape")
    for show in (portrait, landscape):
        qtbot.addWidget(show)
    fixed = []
    monkeypatch.setattr(view, "_fix_part",
                        lambda prompt_id, part: (prompt_id, f"fixing {part.name}"))
    for show in (portrait, landscape):
        monkeypatch.setattr(show, "note_voice_fix",
                            lambda pid, msg, s=show: fixed.append((s, pid, msg)))
    teeth = next(p for p in DETAIL_PARTS if p.name == "teeth")

    view._on_voice_command(SurfaceCommand(teeth, "landscape"))

    assert [entry[0] for entry in fixed] == [landscape]
    assert fixed[0][2] == "fixing teeth"


def test_a_lock_on_a_hosted_show_opens_its_generate_tab(qtbot, tmp_path, monkeypatch):
    """Locking an item on a show answers in the core window too — the way the
    RFB opens a tab for a locked video, the item arrives as a generate tab
    ready to work on.  Releasing the hold (the second toggle) asks nothing."""
    # _open_slideshow names its items id-<name>-<n>, so the row behind the one
    # on screen is id-tall-0.
    row = _image("id-tall-0", "a cat", 50, 1)
    view = GalleryView(FakeDB([row]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    opened = []
    monkeypatch.setattr(view._info_tabs, "reveal_config", opened.append)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200)
    show = view._region_shows["portrait"]
    qtbot.addWidget(show)

    show._toggle_lock()

    assert opened == ["id-tall-0"]

    show._toggle_lock()  # release: no second tab
    assert len(opened) == 1


def test_a_standalone_show_lock_opens_no_tab(qtbot, tmp_path, monkeypatch):
    """The lock-opens-a-tab answer is the hosting session's convention; the
    standalone app's fullscreen slideshow keeps its lock to itself."""
    row = _image("id-tall-0", "a cat", 50, 1)
    view = GalleryView(FakeDB([row]))
    qtbot.addWidget(view)
    opened = []
    monkeypatch.setattr(view._info_tabs, "reveal_config", opened.append)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200)

    view._slideshow._toggle_lock()

    assert opened == []


def test_reset_on_a_show_puts_the_side_back_how_it_started(qtbot, tmp_path, monkeypatch):
    """The players' reset, on a show: F-mode drops, a held lock releases, and
    the first item comes back on screen — the side's defaults, not a dead
    button drawn for sameness."""
    from origenerator.gui.show_hud import ShowHud

    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    monkeypatch.setattr(view, "_starred_prompt_ids", lambda: {"id-tall-1"})
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200, count=3)
    show = view._region_shows["portrait"]
    qtbot.addWidget(show)
    hud, = show.findChildren(ShowHud)

    hud._deliver("portrait_fmode")
    show._playlist.jump_to(1)
    show._toggle_lock()
    assert show.hud_f_mode is True

    hud._deliver("portrait_reset")

    assert show.hud_f_mode is False
    cells, _position, locked = show.hud_items()
    assert len(cells) == 3                 # widened back to the whole set
    assert show._playlist.index == 0       # back at the top of the pass
    assert locked is False                 # the hold released with everything else
