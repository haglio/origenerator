"""A show handed to one of a session's players rather than drawn in a window.

What this covers is the channel between the two: the list the player is handed,
the verbs a press sends it, the panel this app publishes for it, and the slide
on screen — which is the player's answer, read back, not this app's own.
"""
from __future__ import annotations

from pathlib import Path

from origenerator.fun_time_mode import PlayerChannel
from origenerator.gui.player_show import PlayerShow
from origenerator.gui.show_wiring import HudFacts, ShowActions
from origenerator.paths import ensure_player_core_on_path
from origenerator.slideshow import ShowState, in_order

ensure_player_core_on_path()

from player_core.file_channel import consume_command_file  # noqa: E402
from player_core.playlist import read_playlist  # noqa: E402
from player_core.satellite_hud import parse_hud  # noqa: E402
from player_core.status import PlayerStatus, status_fields  # noqa: E402

_ITEMS = [("one.png", "image", "id-1"), ("two.png", "image", "id-2"),
          ("three.png", "image", "id-3")]


def _channel(tmp_path: Path) -> PlayerChannel:
    return PlayerChannel(
        playlist=tmp_path / "portrait.tsv",
        command_file=tmp_path / "portrait_cmd.txt",
        status_file=tmp_path / "portrait_status.txt",
        hud_file=tmp_path / "origenerator_portrait_hud.json",
    )


def _show(qtbot, tmp_path, items=_ITEMS, **fields) -> PlayerShow:
    """A show driving a player whose files are this test's own.

    Its poll timer is stopped and :meth:`PlayerShow.tick` called by hand, so a
    test says when the player is next read rather than racing it.
    """
    show = PlayerShow(items, side="portrait", channel=_channel(tmp_path),
                      shuffle=in_order, **fields)
    show._timer.stop()
    return show


def _sent(show: PlayerShow) -> list[str]:
    """The verbs waiting on the player's command file, drained as it drains
    them — its own reader, so a spelling this app got wrong cannot pass."""
    return consume_command_file(show.channel.command_file, uppercase=False)


def _says(show: PlayerShow, **fields) -> None:
    """The player publishing what it is showing, as its status writer does."""
    _player_says(show.channel, **fields)


def _player_says(channel: PlayerChannel, **fields) -> None:
    lines = status_fields(PlayerStatus(**fields))
    channel.status_file.write_text(
        "".join(f"{key}={value}\n" for key, value in lines.items()), encoding="utf-8")


def _show_with_the_player_on(qtbot, tmp_path, **status) -> PlayerShow:
    show = _show(qtbot, tmp_path)
    _says(show, **status)
    show.tick()
    _sent(show)
    return show


def test_a_show_hands_the_player_the_pass_it_is_to_play(qtbot, tmp_path):
    """The set, in the order this show plays it, is the player's playlist —
    read back through the very reader the player reads it with."""
    show = _show(qtbot, tmp_path)

    played = [str(item.path) for item in read_playlist(show.channel.playlist)]
    assert played == ["one.png", "two.png", "three.png"]


def test_the_player_is_told_to_read_the_list_and_how_long_a_picture_holds(qtbot, tmp_path):
    """Two verbs make the hand-over: read this list, and hold each picture for
    the pace this app's console sets — the player owning the advance from
    there, as it does for its own clips."""
    show = _show(qtbot, tmp_path, image_dwell_ms=6000)

    assert _sent(show) == ["RELOAD_PLAYLIST", "SET_PACE 6"]


def test_the_show_follows_the_player_onto_whatever_it_moved_to(qtbot, tmp_path):
    """The player walks the list by itself — a picture's pace runs out, a clip
    ends — so which item the map lights, the star answers about and a spoken
    "this one" means is the player's answer, read back."""
    show = _show(qtbot, tmp_path)

    _says(show, video="two.png")
    show.tick()

    assert show.hud_prompt_id == "id-2"
    assert show.current_media_path() == "two.png"
    _cells, position, _locked = show.hud_items()
    assert position == 2


def test_the_shows_hold_is_the_players_own(qtbot, tmp_path):
    """A padlock on this panel is the player's repeat-one: it is told, and what
    it says back is what the panel draws."""
    show = _show(qtbot, tmp_path)
    _sent(show)

    show.show_toggle_hold()
    assert _sent(show) == ["LOCK_ON"]
    assert show.locked is True

    _says(show, video="one.png", locked=False)   # the player says otherwise
    show.tick()
    assert show.locked is False


def test_stepping_lets_go_of_a_held_slide_first(qtbot, tmp_path):
    """Moving off a held slide releases the hold, the way the players' own
    prev/next cancel a lock — else the player would repeat the next one too."""
    show = _show(qtbot, tmp_path)
    show.show_toggle_hold()
    _sent(show)

    show.show_step(1)

    assert _sent(show) == ["LOCK_OFF", "NEXT"]


def test_a_hold_stars_the_item_and_asks_for_a_better_version(qtbot, tmp_path):
    """Holding is the whole gesture it is in a window: the player repeats it,
    and the show stars it, asks for the better version, and hands it to the
    gallery to open."""
    asked = []
    actions = ShowActions(star=lambda pid: asked.append(("star", pid)),
                          enhance=lambda pid: asked.append(("enhance", pid)) or True,
                          lock=lambda pid: asked.append(("lock", pid)))
    show = _show(qtbot, tmp_path, actions=actions)

    show.show_toggle_hold()

    assert asked == [("star", "id-1"), ("enhance", "id-1"), ("lock", "id-1")]


def test_culling_tells_the_player_to_drop_it_before_deleting_it(qtbot, tmp_path):
    """The player is playing that very file, and Windows will not move a file a
    process still has open — so the player is told to drop it before the
    generation is condemned."""
    queued_at_delete, deleted = [], []

    def delete(prompt_id):
        queued_at_delete.extend(_sent(show))
        deleted.append(prompt_id)

    show = _show(qtbot, tmp_path, actions=ShowActions(delete=delete))
    _sent(show)

    show.show_cull()

    assert deleted == ["id-1"]
    assert queued_at_delete[:2] == ["LOCK_OFF", "TRASH"]
    played = [str(item.path) for item in read_playlist(show.channel.playlist)]
    assert played == ["two.png", "three.png"]  # and it is off the list


def test_the_delete_a_cull_starts_does_not_skip_a_second_item(qtbot, tmp_path):
    """The recovery bin asks every surface to let go of the files it moves; the
    player is already letting go of this one, so asking again would move it on
    past the item after it as well."""
    released = []

    def delete(_prompt_id):
        show.release_media(["one.png"])
        released.extend(_sent(show))

    show = _show(qtbot, tmp_path, actions=ShowActions(delete=delete))
    _says(show, video="one.png")
    show.tick()

    show.show_cull()

    assert "NEXT" not in released


def test_a_file_the_player_will_not_let_go_of_is_said_rather_than_raised(qtbot, tmp_path):
    """A player with nothing else to move on to keeps its file open for good —
    a delete refused, said where the speaker can see it, not an error that
    takes the app down."""
    said = []

    def delete(_prompt_id):
        raise PermissionError("the file is in use")

    show = _show(qtbot, tmp_path, actions=ShowActions(delete=delete), say=said.append,
                 items=_ITEMS[:1])

    show.show_cull()

    assert said and "couldn't delete" in said[-1]


def test_narrowing_hands_the_player_what_is_left(qtbot, tmp_path):
    """A switch is a narrowing of what the player may reach, so the list it is
    playing is written again with what survives."""
    show = _show(qtbot, tmp_path, hud=HudFacts(starred_ids={"id-3"}))
    _sent(show)

    assert show.toggle_favorites_filter() is True

    played = [str(item.path) for item in read_playlist(show.channel.playlist)]
    assert played == ["three.png"]
    assert "RELOAD_PLAYLIST" in _sent(show)


def test_the_panel_this_app_publishes_is_the_shows_own_band(qtbot, tmp_path):
    """The session draws the panel on the player, so this app publishes the
    model for it: the show's map, its status line and the buttons it answers —
    and not the mode pair, which is the session's own to add."""
    show = _show(qtbot, tmp_path)

    model = parse_hud(show.channel.hud_file.read_text(encoding="utf-8"))

    assert model.player == "portrait"
    assert model.seed_count == 3
    assert [button.command for row in model.rows for button in row] == [
        "portrait_prev", "portrait_next", "portrait_lock", "portrait_trash",
        "portrait_fmode", "portrait_enhanced", "portrait_reset"]


def test_a_map_click_plays_that_item_and_a_double_click_holds_it(qtbot, tmp_path):
    """The same jump a click makes on a player's own map, and the same lock its
    double-click takes."""
    show = _show(qtbot, tmp_path)
    _sent(show)

    show.show_item("three.png", hold=True)

    assert _sent(show) == ["PLAY_FILE three.png", "LOCK_ON"]


def test_a_new_pace_reaches_the_player(qtbot, tmp_path):
    """The pace is the player's to keep — it holds a picture that long and then
    ends the file, which is how a slide moves on at all."""
    show = _show(qtbot, tmp_path)
    _sent(show)

    show.set_dwell_s(9)

    assert _sent(show) == ["SET_PACE 9"]


def test_a_show_that_is_over_gives_the_side_back(qtbot, tmp_path):
    """The panel goes with it, so the session draws its own again on that
    player rather than leaving this app's last one up."""
    show = _show(qtbot, tmp_path)

    show.close()

    assert show.is_showing() is False
    assert show.channel.hud_file.read_text(encoding="utf-8") == ""


def test_a_new_set_lands_the_player_on_its_slide_over_another_item_of_it(qtbot, tmp_path):
    show = _show_with_the_player_on(qtbot, tmp_path, video="one.png")

    show.play(_ITEMS, start=2, shuffle=in_order, image_dwell_ms=0)

    assert _sent(show) == ["PLAY_FILE three.png", "RELOAD_PLAYLIST", "SET_PACE 0"]


def test_a_new_set_does_not_reload_a_player_already_on_its_slide(qtbot, tmp_path):
    show = _show_with_the_player_on(qtbot, tmp_path, video="three.png")

    show.play(_ITEMS, start=2, shuffle=in_order, image_dwell_ms=0)

    assert _sent(show) == ["RELOAD_PLAYLIST", "SET_PACE 0"]


def test_a_new_set_lets_go_of_the_hold_the_last_one_had(qtbot, tmp_path):
    show = _show_with_the_player_on(qtbot, tmp_path, video="one.png", locked=True)

    show.play(_ITEMS, start=1, shuffle=in_order)

    assert _sent(show)[0] == "LOCK_OFF"
    assert show.locked is False


def test_a_side_reset_lands_the_player_on_the_top_of_its_base_set(qtbot, tmp_path):
    show = _show_with_the_player_on(qtbot, tmp_path, video="two.png")

    show.retune(_ITEMS)

    assert _sent(show)[:2] == ["PLAY_FILE one.png", "RELOAD_PLAYLIST"]
    assert show.hud_prompt_id == "id-1"


def test_a_reset_with_no_base_set_lands_the_player_on_the_top_of_its_own(qtbot, tmp_path):
    show = _show_with_the_player_on(qtbot, tmp_path, video="two.png")

    show.reset_in_place()

    assert "PLAY_FILE one.png" in _sent(show)
    assert show.hud_prompt_id == "id-1"


def test_a_show_picked_back_up_lands_the_player_where_the_last_one_left_off(
        qtbot, tmp_path):
    show = _show_with_the_player_on(qtbot, tmp_path, video="one.png")

    assert show.resume(ShowState(order=("id-1", "id-2", "id-3"), current="id-3"))

    assert _sent(show)[0] == "PLAY_FILE three.png"


def test_a_show_opened_on_a_slide_lands_the_player_on_it(qtbot, tmp_path):
    _player_says(_channel(tmp_path), video="one.png")

    show = _show(qtbot, tmp_path, start=2)

    assert _sent(show)[0] == "PLAY_FILE three.png"
    assert show.hud_prompt_id == "id-3"


def test_a_file_about_to_be_deleted_is_let_go_of(qtbot, tmp_path):
    """The player holds the file open, so the way to let go is to move on —
    what the gallery asks of every surface before it moves files."""
    show = _show_with_the_player_on(qtbot, tmp_path, video="one.png")

    show.release_media(["one.png"])

    assert _sent(show) == ["NEXT"]
