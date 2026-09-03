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


def test_fun_time_gallery_stacks_the_generate_tabs_over_the_browser(qtbot):
    # The RFB rect is an upright column, so the side-by-side panes fold into one
    # vertical stack: generate tabs on top, the tree-and-browser row under them,
    # the queue across the foot.
    view = _fun_time_view(qtbot)
    stack = view._stack
    assert isinstance(stack, QSplitter)
    assert stack.orientation() == Qt.Orientation.Vertical
    assert stack.count() == 3
    # Top floor: the info-pane wrapper (tabs + the find bar).
    assert stack.widget(0).findChild(type(view._info_tabs)) is view._info_tabs
    # Middle floor: the tree beside the browser.
    assert stack.widget(1) is view._panes
    assert view._panes.count() == 2
    assert view._panes.widget(1) is view._folder_panes
    # Bottom floor: the queue, spanning the tree's width too.
    assert stack.widget(2) is view._queue


def test_fun_time_gallery_gives_the_bottom_corner_to_the_queue(qtbot):
    """The tree stops above the queue rather than running the rect's full
    height, so the corner under it is the queue — where standalone has it."""
    view = _fun_time_view(qtbot)
    view.resize(600, 900)
    view.show()
    qtbot.waitExposed(view)
    toc = view._panes.widget(0)
    corner = view._queue.mapTo(view, view._queue.rect().bottomLeft())
    tree_foot = toc.mapTo(view, toc.rect().bottomLeft())
    assert tree_foot.y() < corner.y()  # the tree ends before the rect does
    assert view._queue.mapTo(view, view._queue.rect().topLeft()).x() <= (
        toc.mapTo(view, toc.rect().topLeft()).x()
    )  # and the queue reaches the left edge the tree used to own


def test_fun_time_gallery_has_no_collapse_toggle_on_its_left_pane(qtbot):
    """No chevron for the tree.  It sat beside the back/forward chevrons and
    read as a third one of those, and folding the tree away bought a column
    this narrow very little — the divider still drags shut for anyone who
    wants the room."""
    view = _fun_time_view(qtbot)
    assert not hasattr(view, "_toc_toggle")
    assert view._panes.isCollapsible(0)


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
    """"landscape latest": that shelf's landscape items, on the landscape
    region — a show STARTED by voice, with nothing up beforehand and the
    browser left wherever it was.  Latest plays newest-first, and its HUD says
    so, exactly as the shelf's own slideshow button opens it."""
    from origenerator.voice.commands import ShelfCommand

    view = _fun_time_view(qtbot)
    still = tmp_path / "wide.png"
    Image.new("RGB", (200, 100)).save(still)
    rows = [{"prompt_id": "new-1", "thumbnail_path": str(still)}]
    monkeypatch.setattr(view._browser, "rows_for_shelf",
                        lambda key: rows if key == "__recents__::landscape" else [])
    monkeypatch.setattr(view, "_slideshow_items",
                        lambda r: [(str(still), "image", row["prompt_id"], str(still))
                                   for row in r])

    view._on_voice_command(ShelfCommand("__recents__", "landscape"))

    show = view.region_show("landscape")
    assert show is not None and show.isVisible()
    assert show.hud_order_label == "Latest"   # the HUD says which order it plays
    assert view.region_show("portrait") is None  # the other region is untouched
    qtbot.addWidget(show)


def test_the_shows_row_reads_as_looping_and_the_button_ends_it(qtbot, tmp_path, monkeypatch):
    """A show someone ASKED for is the seed row played round and round, so the
    map's loop button is lit — and pressing the lit one stops that loop, which
    means the region goes back to browsing its library."""
    from origenerator.gui.show_hud import ShowHud, show_hud_model

    view = _fun_time_view(qtbot)
    tall = tmp_path / "tall.png"
    Image.new("RGB", (100, 200)).save(tall)
    base = [(str(tall), "image", f"lib-{n}", str(tall)) for n in range(5)]
    monkeypatch.setattr(view, "_rows_at",
                        lambda key: base if key == "__all__::portrait" else [])
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200, count=3)
    monkeypatch.setattr(view, "_slideshow_items", lambda rows: list(rows))
    show = view.region_show("portrait")
    qtbot.addWidget(show)
    hud, = show.findChildren(ShowHud)

    model = show_hud_model("portrait", show)
    assert model.active_loop == "seed"
    # And the line says what the light says, in the satellite's own words: the
    # two HUDs are one HUD in two places.  It also drops "Unlocked", exactly as
    # a looping satellite's does — a set playing through holds nothing.
    assert model.lock_label.startswith("Looping seeds")
    assert "Unlocked" not in model.lock_label

    hud._deliver("portrait_no_loop")

    assert show.isVisible()                      # the region is not handed back
    assert len(show.hud_items()[0]) == len(base)  # it browses its library again
    dropped = show_hud_model("portrait", show)
    assert dropped.active_loop == ""
    assert "Looping" not in dropped.lock_label


def test_the_base_state_is_not_a_loop_and_says_so(qtbot, tmp_path, monkeypatch):
    """A region browsing its whole library is what a satellite does with no loop
    on, so its HUD must read that way: the loop button dark, the map unboxed,
    and the line naming the order rather than a loop.  It said "Looping seeds"
    over the base state, which is the one place there is no loop at all."""
    from origenerator.gui.show_hud import show_hud_model

    view = _fun_time_view(qtbot)
    tall = tmp_path / "tall.png"
    Image.new("RGB", (100, 200)).save(tall)
    base = [(str(tall), "image", f"lib-{n}", str(tall)) for n in range(4)]
    monkeypatch.setattr(view, "_rows_at",
                        lambda key: base if key == "__all__::portrait" else [])
    monkeypatch.setattr(view, "_slideshow_items", lambda rows: list(rows))

    view.fill_the_regions()

    show = view.region_show("portrait")
    qtbot.addWidget(show)
    model = show_hud_model("portrait", show)
    assert model.active_loop == ""
    assert model.lock_label == "Unlocked · Shuffle"


def test_a_region_the_session_wants_never_stays_empty(qtbot, tmp_path, monkeypatch):
    """The player under a region is blacked for the whole mode, so a region left
    empty is a black rectangle — not a fallback.  Two ways it can be left empty
    and both are answered: the show covering it ends, and the base state was
    asked for before the tree it reads had been built (the session's OPEN_SHOWS
    races this app's boot)."""
    view = _fun_time_view(qtbot)
    tall = tmp_path / "tall.png"
    Image.new("RGB", (100, 200)).save(tall)
    base = [(str(tall), "image", f"lib-{n}", str(tall)) for n in range(4)]
    library = {"rows": []}
    monkeypatch.setattr(view, "_rows_at",
                        lambda key: library["rows"] if key == "__all__::portrait" else [])
    monkeypatch.setattr(view, "_slideshow_items", lambda rows: list(rows))

    view.fill_the_regions()          # asked for too early: nothing to play yet
    assert view.region_show("portrait") is None

    library["rows"] = base
    view.refresh()                   # the tree exists now, and so does the show
    show = view.region_show("portrait")
    assert show is not None
    qtbot.addWidget(show)

    show.close()                     # and it comes back under whatever ends
    later = view.region_show("portrait")
    assert later is not None and later is not show
    qtbot.addWidget(later)

    view.close_the_regions()         # until the session says it is done with them
    assert view.region_show("portrait") is None


def test_a_spoken_favorites_is_the_shows_own_f_mode(qtbot, tmp_path, monkeypatch):
    """On a player "favorites" is F-mode — narrow what is playing to them — so
    on a show it is the same switch, the one its HUD already draws.  Opening
    the shelf as a fresh show would answer a word the HUD has a button for with
    something else entirely."""
    from origenerator.voice.commands import ShelfCommand

    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    monkeypatch.setattr(view, "_starred_prompt_ids", lambda: {"id-tall-1"})
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200, count=3)
    show = view.region_show("portrait")
    qtbot.addWidget(show)

    view._on_voice_command(ShelfCommand("__starred__", "portrait"))
    assert show.hud_f_mode is True
    assert len(show.hud_items()[0]) == 1     # narrowed to the one favorite

    view._on_voice_command(ShelfCommand("__starred__", "portrait"))
    assert show.hud_f_mode is False          # and the word widens it back


def test_a_spoken_fix_names_which_region_it_means(qtbot, tmp_path, monkeypatch):
    """"landscape fix teeth": hosted, two shows run and NEITHER is the active
    window, so the side word is the only thing that says which picture."""
    from origenerator.workflows.detail_parts import DETAIL_PARTS
    from origenerator.voice.commands import SurfaceCommand

    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200)
    _open_slideshow(view, monkeypatch, tmp_path, "wide", 200, 100)
    portrait, landscape = view.region_show("portrait"), view.region_show("landscape")
    for show in (portrait, landscape):
        qtbot.addWidget(show)
    fixed = []
    monkeypatch.setattr(
        view, "_fix_parts",
        lambda prompt_id, parts: (prompt_id,
                                  "fixing " + " ".join(p.name for p in parts)))
    for show in (portrait, landscape):
        monkeypatch.setattr(show, "note_voice_run",
                            lambda pid, msg, s=show: fixed.append((s, pid, msg)))
    teeth = next(p for p in DETAIL_PARTS if p.name == "teeth")

    # A fix names one or more parts, so the command carries them as a set.
    view._on_voice_command(SurfaceCommand([teeth], "landscape"))

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
    opened, navigated = [], []
    monkeypatch.setattr(view._info_tabs, "load_selection",
                        lambda row, images, **kw: opened.append(row["prompt_id"]))
    # Landing on the item is what opens its tab, so the link is spied on rather
    # than swallowed: it has to run for the tab to come of it.
    real_link = view._follow_link

    def follow(prompt_id):
        navigated.append(prompt_id)
        real_link(prompt_id)

    monkeypatch.setattr(view, "_follow_link", follow)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200)
    show = view._region_shows["portrait"]
    qtbot.addWidget(show)

    show._toggle_lock()

    # The item held, not a sibling of it: every seed of one recipe shares a
    # settings folder, so a tab picked by folder came up on the wrong picture.
    assert opened == ["id-tall-0"]
    assert navigated == ["id-tall-0"]  # and the browser went there too

    show._toggle_lock()  # release: no second tab
    assert len(opened) == 1


def test_a_standalone_show_lock_opens_no_tab(qtbot, tmp_path, monkeypatch):
    """The lock-opens-a-tab answer is the hosting session's convention; the
    standalone app's fullscreen slideshow keeps its lock to itself."""
    row = _image("id-tall-0", "a cat", 50, 1)
    view = GalleryView(FakeDB([row]))
    qtbot.addWidget(view)
    opened = []
    monkeypatch.setattr(view._info_tabs, "load_selection",
                        lambda row, images, **kw: opened.append(row["prompt_id"]))
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


def test_the_regions_open_on_the_whole_library_of_their_own_shape(
        qtbot, tmp_path, monkeypatch):
    """The base state of origenerator mode: each region shuffling every item of
    its own orientation, the way each satellite player shuffles the whole
    library of its own.

    It opened on the Latest shelf before this — a recent slice rather than the
    library — and on a black screen before that.
    """
    view = _fun_time_view(qtbot)
    tall, wide = tmp_path / "tall.png", tmp_path / "wide.png"
    Image.new("RGB", (100, 200)).save(tall)
    Image.new("RGB", (200, 100)).save(wide)
    library = {
        "__all__::portrait": [{"prompt_id": "p-1", "thumbnail_path": str(tall)}],
        "__all__::landscape": [{"prompt_id": "l-1", "thumbnail_path": str(wide)}],
    }
    monkeypatch.setattr(view, "_rows_at", lambda key: library.get(key, []))
    monkeypatch.setattr(
        view, "_slideshow_items",
        lambda rows: [(row["thumbnail_path"], "image", row["prompt_id"],
                       row["thumbnail_path"]) for row in rows])

    view.fill_the_regions()

    for side in ("portrait", "landscape"):
        show = view.region_show(side)
        assert show is not None and show.isVisible()
        assert show.hud_order_label == "Shuffle"
        cells, _position, _locked = show.hud_items()
        assert [path for path, _still in cells] == \
            [library[f"__all__::{side}"][0]["thumbnail_path"]]
        qtbot.addWidget(show)
    # And each remembers WHERE it plays from, so what lands in the library
    # reaches a region sitting in its base state.
    assert sorted(where for _show, where in view._live_shows) == [
        "__all__::landscape", "__all__::portrait"]


def test_a_key_can_name_a_place_and_a_shape_at_once(qtbot, tmp_path):
    """``__all__::portrait`` is the whole library narrowed to one shape, and it
    stays re-askable: the base state holds the key rather than the rows, so a
    region asked again after a generation lands sees the new item too."""
    tall, wide = tmp_path / "tall.png", tmp_path / "wide.png"
    Image.new("RGB", (100, 200)).save(tall)
    Image.new("RGB", (200, 100)).save(wide)
    from tests.test_gallery_view import _row
    rows = [
        _row("p-1", "sdxl_t2i", {"positive_prompt": "a", "seed": 1},
             "sdxl_t2i_p1.png", thumbnail_path=str(tall)),
        _row("l-1", "sdxl_t2i", {"positive_prompt": "b", "seed": 2},
             "sdxl_t2i_l1.png", thumbnail_path=str(wide)),
    ]
    view = _fun_time_view(qtbot, rows)
    view.refresh()

    portrait = [row["prompt_id"] for row in view._rows_at("__all__::portrait")]
    landscape = [row["prompt_id"] for row in view._rows_at("__all__::landscape")]
    assert portrait == ["p-1"]
    assert landscape == ["l-1"]
    # And the two halves are the whole of it — there is no un-sided All to ask.
    assert set(portrait) | set(landscape) == {"p-1", "l-1"}


def test_reset_puts_a_region_back_on_the_library_not_on_its_own_folder(
        qtbot, tmp_path, monkeypatch):
    """Reset means on a show what it means on a player: the narrowing comes off
    and the side goes back to browsing its whole library.  A show started on
    one folder therefore leaves that folder — restarting it would be the one
    thing reset is not."""
    from origenerator.gui.show_hud import ShowHud

    view = GalleryView(FakeDB([]), fun_time=_session_with_dashboard(tmp_path))
    qtbot.addWidget(view)
    tall = tmp_path / "tall.png"
    Image.new("RGB", (100, 200)).save(tall)
    base = [(str(tall), "image", f"lib-{n}", str(tall)) for n in range(5)]
    monkeypatch.setattr(view, "_rows_at",
                        lambda key: base if key == "__all__::portrait" else [])
    _open_slideshow(view, monkeypatch, tmp_path, "folder", 100, 200, count=2)
    # _open_slideshow stubs the items for the folder it opened; from here the
    # rows the library hands back are the items.
    monkeypatch.setattr(view, "_slideshow_items", lambda rows: list(rows))
    show = view.region_show("portrait")
    qtbot.addWidget(show)
    hud, = show.findChildren(ShowHud)
    assert len(show.hud_items()[0]) == 2      # the folder it was started on
    view._live_shows = [(show, "folder-a")]

    hud._deliver("portrait_reset")

    assert len(show.hud_items()[0]) == len(base)   # the library of its shape
    assert show.hud_order_label == "Shuffle"
    # And it is fed from the library now, not from the folder it left.
    assert [where for _show, where in view._live_shows] == ["__all__::portrait"]


def test_reset_stays_local_when_a_show_holds_no_region(qtbot, tmp_path, monkeypatch):
    """Standalone there is no base state to go back to, so reset is the show's
    own: F-mode off, the hold released, the top of its set on screen."""
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200, count=3)
    show = view._slideshow
    qtbot.addWidget(show)
    show._playlist.jump_to(1)
    show._toggle_lock()

    show.stroke_reset()

    assert show._playlist.index == 0
    assert show._playlist.locked is False
    assert len(show.hud_items()[0]) == 3


def test_omnipause_leaves_nothing_moving_anywhere_in_the_window(qtbot, tmp_path):
    """Swept rather than listed: after the freeze, no movie under this window is
    running — the grid tiles, the shelves, a tab's history strip, the "Animated
    in" strip, the info pane's own animated still.

    Written this way because the listed version was wrong three times over: the
    tiles were wired to OmniPause and the other three kinds of looping preview
    were not, so a frozen room went on playing and nothing in the suite noticed.
    A sweep cannot miss the fourth one, and it fails the moment someone adds a
    fifth that does not go through looping_movie.
    """
    from PyQt6.QtGui import QMovie
    from PyQt6.QtWidgets import QLabel
    from tests.test_gallery_view import _row

    webp = tmp_path / "loop.webp"
    frames = [Image.new("RGB", (64, 32), shade) for shade in ((10, 10, 10), (220, 220, 220))]
    frames[0].save(webp, save_all=True, append_images=frames[1:], duration=100, loop=0)
    still = tmp_path / "still.png"
    Image.new("RGB", (64, 32)).save(still)
    rows = [_row("v-1", "wan22_i2v",
                 {"positive_prompt": "a clip", "seed": 1,
                  "unet_high": "wan_high.safetensors", "unet_low": "wan_low.safetensors"},
                 "wan22_i2v_v1.mp4", thumbnail_path=str(still))]

    view = _fun_time_view(qtbot, rows)
    view._animated_preview = lambda row: str(webp)
    view.refresh()
    view._tree.setCurrentItem(view._tree_view.leaf_by_id["v-1"])
    running = [label for label in view.findChildren(QLabel)
               if label.movie() is not None
               and label.movie().state() == QMovie.MovieState.Running]
    assert running, "nothing was moving, so the sweep would prove nothing"

    view.set_session_paused(True)

    still_moving = [label for label in view.findChildren(QLabel)
                    if label.movie() is not None
                    and label.movie().state() == QMovie.MovieState.Running]
    assert still_moving == []

    view.set_session_paused(False)
    assert [label for label in view.findChildren(QLabel)
            if label.movie() is not None
            and label.movie().state() == QMovie.MovieState.Running]


def test_omnipause_reaches_a_show_the_region_map_does_not_answer_for(
        qtbot, tmp_path, monkeypatch):
    """The freeze is fanned out over the shows this window has OPEN, not over
    the ones the region map calls visible.

    A show the session has covered or parked is still a show, and one that went
    on advancing through a frozen room is the room not being frozen.  The map
    answers ``None`` for anything it does not consider visible, so reading the
    freeze off it left exactly those shows running.
    """
    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200, count=3)
    show = view._live_shows[0][0]
    qtbot.addWidget(show)
    monkeypatch.setattr(view, "region_show", lambda side: None)

    view.set_session_paused(True)

    assert show._session_paused is True
    assert not show._timer.isActive()


def test_a_frozen_show_does_not_walk_past_an_unplayable_clip(qtbot, tmp_path, monkeypatch):
    """Stepping past a clip that will not play is right while the show is
    running and wrong while the room is held: a show hunting through its set for
    something playable is the room moving during OmniPause."""
    view = _fun_time_view(qtbot)
    _open_slideshow(view, monkeypatch, tmp_path, "tall", 100, 200, count=3)
    show = view.region_show("portrait")
    qtbot.addWidget(show)
    view.set_session_paused(True)
    at = show._playlist.index

    show._preview.video_unplayable.emit()

    assert show._playlist.index == at


def test_a_portrait_picture_stands_beside_the_form_when_hosted(qtbot):
    """In the RFB's upright column a portrait picture stacked over the settings
    pushes every prompt field off the bottom, so the two go side by side —
    settings left, picture right, the order they are read in."""
    from PyQt6.QtGui import QPixmap

    from origenerator.gui.generate_config_panel import GenerateConfigPanel

    panel = GenerateConfigPanel(None, FakeDB([]), fun_time=_session())
    qtbot.addWidget(panel)
    assert panel._media_split.orientation() == Qt.Orientation.Vertical

    panel._preview._pixmap = QPixmap(400, 900)   # taller than it is wide
    panel._reflow_for_the_media()

    assert panel._media_split.orientation() == Qt.Orientation.Horizontal
    assert panel._media_split.indexOf(panel._scroll) == 0    # settings lead
    assert panel._media_split.indexOf(panel._preview) == 1


def test_a_landscape_picture_stays_stacked_when_hosted(qtbot):
    """A wide picture beside a form gets a column too narrow to show it, and the
    form loses the width its prompt boxes need."""
    from PyQt6.QtGui import QPixmap

    from origenerator.gui.generate_config_panel import GenerateConfigPanel

    panel = GenerateConfigPanel(None, FakeDB([]), fun_time=_session())
    qtbot.addWidget(panel)

    panel._preview._pixmap = QPixmap(1200, 700)
    panel._reflow_for_the_media()

    assert panel._media_split.orientation() == Qt.Orientation.Vertical
    assert panel._media_split.indexOf(panel._preview) == 0


def test_standalone_never_stands_them_side_by_side(qtbot):
    """The pane is wide there; stacking is right at any shape."""
    from PyQt6.QtGui import QPixmap

    from origenerator.gui.generate_config_panel import GenerateConfigPanel

    panel = GenerateConfigPanel(None, FakeDB([]))
    qtbot.addWidget(panel)

    panel._preview._pixmap = QPixmap(400, 900)
    panel._reflow_for_the_media()

    assert panel._media_split.orientation() == Qt.Orientation.Vertical


def test_a_tab_coming_to_the_front_lays_out_for_its_own_picture(qtbot):
    """The shape belongs to the tab, so switching to one holding a landscape
    picture stands the panes back up — without waiting for something else to
    nudge the splitter, which is all that used to bring them back."""
    from PyQt6.QtGui import QPixmap

    from origenerator.gui.info_pane_tabs import InfoPaneTabs

    tabs = InfoPaneTabs(None, FakeDB([]), fun_time=_session())
    qtbot.addWidget(tabs)
    portrait_tab = tabs.currentWidget()
    portrait_tab._preview._pixmap = QPixmap(400, 900)
    portrait_tab.refresh_media_layout()
    assert portrait_tab._media_split.orientation() == Qt.Orientation.Horizontal

    # A second tab holding a landscape picture; switching to it stands it up.
    tabs._add_subtab()
    landscape_tab = tabs.currentWidget()
    landscape_tab._preview._pixmap = QPixmap(1200, 700)
    tabs.setCurrentWidget(portrait_tab)
    tabs.setCurrentWidget(landscape_tab)

    assert landscape_tab._media_split.orientation() == Qt.Orientation.Vertical


def test_the_shows_hud_names_the_item_the_way_this_app_does(qtbot):
    """Not the way the disk does.  Off the path it reads "image / ComfyUI_00123_"
    — a media type and a counter that appear nowhere in this UI — where the tree
    calls the folder "615F7744" and the browser captions the tile "seed 7"."""
    row = _image("p1", "a cat", 50, 1)
    view = _fun_time_view(qtbot, rows=[row])

    label = view._show_item_label("p1")

    assert "seed" in label and "/" in label
    assert "image /" not in label       # never the media type as a folder
    assert "ComfyUI" not in label       # never the counter off the disk


def test_an_item_no_row_claims_is_named_nothing_at_all(qtbot):
    view = _fun_time_view(qtbot)
    assert view._show_item_label("nobody") == ""
    assert view._show_item_label("") == ""
