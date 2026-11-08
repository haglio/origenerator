from __future__ import annotations

import json

import pytest
from PIL import Image
from PyQt6.QtCore import QPoint, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QGridLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QToolButton,
    QWidget,
)
from shared_ui.colors import BLACK, YELLOW
from shared_ui.preview import Preview
from shared_ui.spacing import GAP_MEDIUM, MARGIN_STANDARD
from shared_ui.tick_control import TickControl

from origenerator.action_labels import Labels
from origenerator.action_setter import Locks, SetterSession
from origenerator.action_vocabulary import Tile, Vocabulary, vocabulary
from origenerator.content import EXAMPLE_CONTENT
from origenerator.gui.action_setter_window import (
    KEEP_GOING,
    KEEP_GOING_QUESTION,
    LAST_LINE,
    PREVIOUSLY_LINE,
    QUIT,
    ROOM_FOR_THE_GRID,
    SAME_BUTTON,
    SKIP_BUTTON,
    STATUS_LINE,
    UNDO_BUTTON,
    ActionSetterWindow,
    action_button,
    ask_to_keep_going,
    checkbox,
    lock,
    on_a_white_square,
    one_scale_for_all,
    one_term_to_a_line,
    wrapped_to_fit,
)
from origenerator.gui.stylesheet import build_stylesheet
from origenerator.media import MediaType

_BUTTONS = {"button one": ("alpha",), "button two": ("alpha", "beta"), "button three": ("gamma",)}
_TILES = (Tile("button one", 0, 0), Tile("button two", 0, 1), Tile("button three", 1, 0))


class _Store:
    def __init__(self):
        self.labels = {}

    def set_labels(self, prompt_id, side, labels):
        self.labels[prompt_id] = labels


class _Stage(QWidget):
    def __init__(self):
        super().__init__()
        self.shown = []

    def show_media(self, path, media_type):
        self.shown.append((str(path), media_type))

    def show_message(self, text):
        self.shown.append(text)

    def clear(self):
        self.shown.append(None)


def _drawn(path, size=(40, 60), color="gray"):
    Image.new("RGB", size, color).save(path)
    return str(path)


def _tile(made, name) -> QToolButton:
    return made.findChild(QToolButton, action_button(name))


def _box(made, name) -> TickControl:
    return made.findChild(TickControl, checkbox(name))


def _lock(made, name) -> QToolButton:
    return made.findChild(QToolButton, lock(name))


def _press(made, name) -> QPushButton:
    return made.findChild(QPushButton, name)


def _said(made, name) -> str:
    return made.findChild(QLabel, name).text()


@pytest.fixture
def window(qtbot, tmp_path):
    def build(*prompt_ids, items=None, drawings=None, tiles=None, checkboxes=(),
              side=MediaType.IMAGE, locks=None, keep_going=None):
        store = _Store()
        listed = items or [{"prompt_id": p, "name": "3FA9C0D2 000", "path": None}
                           for p in prompt_ids]
        stage = _Stage()
        made = ActionSetterWindow(
            SetterSession(listed, store, side),
            Vocabulary(_BUTTONS, tiles or _TILES, tuple(checkboxes), {}, {}, {}, {}),
            drawings or {}, locks or Locks(tmp_path / "locks.json"), stage=stage,
            keep_going=keep_going)
        qtbot.addWidget(made)
        return made, store, stage

    return build


def test_the_window_is_called_the_action_setter_tool_for_its_kind(window, qtbot, tmp_path):
    made, _store, _stage = window("first")
    for_videos = ActionSetterWindow(
        SetterSession([{"prompt_id": "vid", "name": "3FA9C0D2 000", "labels": None}],
                      _Store(), MediaType.VIDEO),
        Vocabulary(_BUTTONS, _TILES, ("third box",), {}, {}, {}, {}), {},
        Locks(tmp_path / "locks.json"), stage=_Stage())
    qtbot.addWidget(for_videos)

    assert (made.windowTitle(), for_videos.windowTitle()) == (
        "Origenerator — image action setter tool", "Origenerator — video action setter tool")


def test_every_checkbox_sits_on_one_line_above_the_buttons(window):
    made, _store, _stage = window("first", checkboxes=("first box", "second box"))
    made.resize(1400, 900)
    made.show()
    made.layout().activate()
    tops = {_box(made, name).mapTo(made, QPoint()).y() for name in ("first box", "second box")}

    assert len(tops) == 1


def test_the_status_line_calls_the_item_by_the_name_the_gallery_gives_it(window):
    made, _store, _stage = window(items=[{"prompt_id": "first", "name": "3FA9C0D2 004"}])

    assert _said(made, STATUS_LINE) == "1 left · 3FA9C0D2 004"


def test_pressing_a_button_saves_the_actions_it_stands_for_on_the_item(window):
    made, store, _stage = window("first", "second")

    _tile(made, "button two").click()

    assert sorted(tile.objectName() for tile in made.findChildren(QToolButton)) == sorted(
        action_button(name) for name in _BUTTONS)
    assert store.labels == {"first": Labels(("alpha", "beta"))}


def test_the_count_says_how_many_are_left_and_falls_as_they_are_set(window):
    made, _store, _stage = window("first", "second")
    before = _said(made, STATUS_LINE)

    _tile(made, "button one").click()

    assert (before[:2], _said(made, STATUS_LINE)[:2]) == ("2 ", "1 ")


def test_the_last_line_names_the_button_last_pressed(window):
    made, _store, _stage = window("first", "second")

    _tile(made, "button one").click()

    assert _said(made, LAST_LINE) == "Last: button one"


def test_the_window_says_when_there_is_nothing_left_to_set(window):
    made, _store, _stage = window("only")

    _tile(made, "button one").click()

    assert _said(made, STATUS_LINE) == ActionSetterWindow.NOTHING_LEFT


class _Asked:
    def __init__(self, answer):
        self.answer, self.times, self.showing = answer, 0, []

    def __call__(self, parent):
        self.times += 1
        self.showing.append(_said(parent, STATUS_LINE))
        return self.answer


def test_opened_on_an_item_it_asks_after_that_one_whether_to_go_on(window):
    asked = _Asked(True)
    made, _store, _stage = window("first", "second", keep_going=asked)
    made.show()

    _tile(made, "button one").click()

    assert (asked.times, made.isVisible(), _said(made, STATUS_LINE)[:2]) == (1, True, "1 ")


def test_quitting_at_the_question_closes_the_tool(window):
    made, store, _stage = window("first", "second", keep_going=_Asked(False))
    made.show()

    _tile(made, "button one").click()

    assert (made.isVisible(), store.labels) == (False, {"first": Labels(("alpha",))})


def test_it_asks_only_after_the_first_one(window):
    asked = _Asked(True)
    made, _store, _stage = window("first", "second", "third", keep_going=asked)

    _tile(made, "button one").click()
    _press(made, SAME_BUTTON).click()

    assert asked.times == 1


def test_with_nothing_else_waiting_it_does_not_ask(window):
    asked = _Asked(True)
    made, _store, _stage = window("only", keep_going=asked)

    _tile(made, "button one").click()

    assert (asked.times, _said(made, STATUS_LINE)) == (0, ActionSetterWindow.NOTHING_LEFT)


def test_it_asks_with_the_first_item_still_showing(window):
    asked = _Asked(True)
    made, _store, _stage = window(items=[{"prompt_id": "first", "name": "3FA9C0D2 001"},
                                         {"prompt_id": "second", "name": "3FA9C0D2 002"}],
                                  keep_going=asked)

    _tile(made, "button one").click()

    assert (asked.showing, _said(made, STATUS_LINE)) == (
        ["2 left · 3FA9C0D2 001"], "1 left · 3FA9C0D2 002")


def test_opened_on_an_item_skip_is_grayed_until_that_item_has_its_actions(window):
    made, _store, _stage = window("first", "second", keep_going=_Asked(True))
    before = _press(made, SKIP_BUTTON).isEnabled()

    _tile(made, "button one").click()

    assert (before, _press(made, SKIP_BUTTON).isEnabled()) == (False, True)


def test_opened_on_its_own_skip_can_be_pressed_on_the_first_item(window):
    made, _store, _stage = window("first", "second")

    assert _press(made, SKIP_BUTTON).isEnabled()


@pytest.mark.parametrize(("pressed", "going_on"), [(KEEP_GOING, True), (QUIT, False)])
def test_the_question_offers_keeping_on_or_quitting(window, pressed, going_on):
    made, _store, _stage = window("first")
    seen = []

    def answer():
        asked = next(shown for shown in QApplication.topLevelWidgets()
                     if isinstance(shown, QMessageBox) and shown.isVisible())
        seen.append((asked.text(), sorted(button.text() for button in asked.buttons())))
        next(button for button in asked.buttons() if button.text() == pressed).click()

    QTimer.singleShot(0, answer)

    assert (ask_to_keep_going(made), seen) == (
        going_on, [(KEEP_GOING_QUESTION, sorted((KEEP_GOING, QUIT)))])


def test_same_as_last_gives_this_item_the_actions_the_last_one_got(window):
    made, store, _stage = window("first", "second")
    _tile(made, "button three").click()

    _press(made, SAME_BUTTON).click()

    assert store.labels == {"first": Labels(("gamma",)), "second": Labels(("gamma",))}


def test_same_as_last_with_nothing_set_yet_says_so_and_sets_nothing(window):
    made, store, _stage = window("first")

    _press(made, SAME_BUTTON).click()

    assert (store.labels, _said(made, LAST_LINE)) == ({}, "Nothing set yet to go by")


def test_skipping_leaves_the_item_as_it_was_and_brings_up_the_next(window):
    made, store, _stage = window("first", "second")

    _press(made, SKIP_BUTTON).click()

    assert (store.labels, _said(made, STATUS_LINE)[:2]) == ({}, "2 ")


def test_undo_takes_the_last_answer_back_and_puts_its_item_up_again(window):
    made, store, _stage = window("first", "second")
    _tile(made, "button one").click()

    _press(made, UNDO_BUTTON).click()

    assert (store.labels, _said(made, STATUS_LINE)[:2]) == ({"first": None}, "2 ")


def test_undo_with_nothing_answered_yet_says_so(window):
    made, _store, _stage = window("first")

    _press(made, UNDO_BUTTON).click()

    assert _said(made, LAST_LINE) == "Nothing to undo"


def test_the_item_on_screen_is_put_up_from_its_file_as_what_it_is(window, tmp_path):
    image = _drawn(tmp_path / "item.png")
    _made, _store, stage = window(items=[{"prompt_id": "first", "name": "3FA9C0D2 001",
                                          "path": image}], side=MediaType.VIDEO)

    assert stage.shown == [(image, MediaType.VIDEO)]


def test_an_item_whose_file_has_gone_says_so_rather_than_showing_nothing(window, tmp_path):
    _made, _store, stage = window(items=[{"prompt_id": "first", "name": "3FA9C0D2 001",
                                          "path": str(tmp_path / "gone.png")}])

    assert stage.shown == [ActionSetterWindow.MISSING]


def test_closing_the_window_lets_go_of_what_it_was_showing(window):
    made, _store, stage = window("first")

    made.close()

    assert stage.shown[-1] is None


def test_each_checkbox_stands_above_the_buttons_with_a_lock_beside_it(window):
    made, _store, _stage = window("first", checkboxes=("first box", "second box"))
    above = made.findChild(QToolButton, action_button("button one")).mapTo(made, made.rect().topLeft())

    for name in ("first box", "second box"):
        box, held = _box(made, name), _lock(made, name)
        assert (box.text(), held.isCheckable(), held.isChecked()) == (name, True, False)
        assert box.mapTo(made, box.rect().topLeft()).y() < above.y()


def test_a_press_saves_the_checked_boxes_with_the_actions(window):
    made, store, _stage = window("first", checkboxes=("first box", "second box"))

    _box(made, "second box").setChecked(True)
    _tile(made, "button one").click()

    assert store.labels == {"first": Labels(("alpha",), ("second box",))}


def _edge(made, name) -> str:
    shot = _tile(made, name).grab().toImage()
    return shot.pixelColor(0, shot.height() // 2).name()


def _previously(made) -> QLabel:
    return made.findChild(QLabel, PREVIOUSLY_LINE)


def _set_before(*items):
    return [{"prompt_id": prompt_id, "name": "3FA9C0D2 000", "path": None, "labels": labels}
            for prompt_id, labels in items]


def _fill(made, name) -> str:
    shot = _tile(made, name).grab().toImage()
    return shot.pixelColor(shot.width() // 2, 3).name()


def _name_color(made, name) -> str:
    face = _tile(made, name).findChild(QToolButton) or _tile(made, name)
    face.ensurePolished()
    return face.palette().color(QPalette.ColorRole.ButtonText).name()


@pytest.mark.parametrize("tiles", [
    _TILES,
    (Tile("button one", 0, 0), Tile("button three", 1, 0), Tile("button two", 0, 1, rows=2)),
], ids=["one row", "down two rows"])
def test_the_button_an_item_was_set_with_before_is_all_yellow_with_its_name_in_black(window, tiles):
    made, _store, _stage = window(items=_set_before(("first", Labels(("beta", "alpha")))), tiles=tiles)
    made.setStyleSheet(build_stylesheet())

    assert [(_edge(made, name), _fill(made, name)) for name in _BUTTONS] == [
        (_edge(made, "button one"), _fill(made, "button one")), (YELLOW.name(), YELLOW.name()),
        (_edge(made, "button one"), _fill(made, "button one"))]
    assert YELLOW.name() not in (_edge(made, "button one"), _fill(made, "button one"))
    assert (_name_color(made, "button two"), _name_color(made, "button one")) == (
        BLACK.name(), _name_color(made, "button three"))


def test_a_yellow_line_beside_the_checkboxes_says_what_the_yellow_box_means(window):
    made, _store, _stage = window(items=_set_before(("first", Labels(("gamma",)))))
    line = _previously(made)
    line.ensurePolished()

    assert (line.isHidden(), line.text(), line.palette().color(QPalette.ColorRole.WindowText).name()) == (
        False, "yellow box was previously selected", YELLOW.name())
    assert line.mapTo(made, QPoint()).y() < _tile(made, "button one").mapTo(made, QPoint()).y()


def test_an_item_never_set_shows_no_yellow_box_and_no_yellow_line(window):
    made, _store, _stage = window(items=_set_before(("first", Labels(("gamma",))), ("second", None)))
    made.setStyleSheet(build_stylesheet())

    _tile(made, "button one").click()

    assert (YELLOW.name() in [_edge(made, name) for name in _BUTTONS], _previously(made).isHidden()) == (
        False, True)


def test_an_item_set_with_actions_no_button_stands_for_shows_no_yellow_line(window):
    made, _store, _stage = window(items=_set_before(("first", Labels(("beta",)))))

    assert _previously(made).isHidden()


def test_each_item_comes_up_with_its_own_checked_boxes(window):
    made, _store, _stage = window(items=[
        {"prompt_id": "first", "labels": Labels((), ("first box",))},
        {"prompt_id": "second", "labels": None},
    ], checkboxes=("first box",))
    on_the_first = _box(made, "first box").isChecked()

    _tile(made, "button one").click()

    assert (on_the_first, _box(made, "first box").isChecked()) == (True, False)


def test_a_locked_box_stays_as_it_is_for_every_item(window):
    made, store, _stage = window("first", "second", checkboxes=("first box",))
    _box(made, "first box").setChecked(True)
    _lock(made, "first box").setChecked(True)

    _tile(made, "button one").click()
    _tile(made, "button one").click()

    assert store.labels == {"first": Labels(("alpha",), ("first box",)),
                            "second": Labels(("alpha",), ("first box",))}


def test_a_lock_is_kept_for_the_next_time_the_window_opens(window, tmp_path):
    locks = Locks(tmp_path / "kept.json")
    made, _store, _stage = window("first", checkboxes=("first box",), locks=locks)
    _box(made, "first box").setChecked(True)
    _lock(made, "first box").setChecked(True)

    again, _store, _stage = window(items=[{"prompt_id": "second", "labels": None}],
                                   checkboxes=("first box",), locks=Locks(tmp_path / "kept.json"))

    assert (_lock(again, "first box").isChecked(), _box(again, "first box").isChecked()) == (
        True, True)


def test_unlocking_a_box_lets_the_next_item_bring_its_own(window):
    made, _store, _stage = window("first", "second", checkboxes=("first box",))
    _box(made, "first box").setChecked(True)
    _lock(made, "first box").setChecked(True)

    _lock(made, "first box").setChecked(False)
    _tile(made, "button one").click()

    assert _box(made, "first box").isChecked() is False


def test_each_button_wears_its_own_drawing(window, tmp_path):
    made, _store, _stage = window("first", drawings={"button two": _drawn(tmp_path / "two.png")})

    assert not _tile(made, "button two").icon().isNull()


def test_a_button_with_no_drawing_installed_stands_on_its_words(window):
    made, _store, _stage = window("first")

    assert _tile(made, "button one").icon().isNull()
    assert _tile(made, "button one").text().replace("\n", " ") == "button one"


def test_a_name_of_several_terms_reads_one_term_to_a_line():
    named = ("alpha, beta gamma", "delta (with epsilon)", "eta + theta")

    assert tuple(one_term_to_a_line(name) for name in named) == (
        "alpha\nbeta gamma", "delta\n(with epsilon)", "eta +\ntheta")


def test_a_drawing_that_will_not_load_is_no_worse_than_none(window, tmp_path):
    torn = tmp_path / "torn.png"
    torn.write_bytes(b"not an image at all")

    made, _store, _stage = window("first", drawings={"button one": str(torn)})

    assert _tile(made, "button one").icon().isNull()


def test_every_button_is_the_same_shape_and_size(window, tmp_path):
    made, _store, _stage = window("first", drawings={
        "button one": _drawn(tmp_path / "one.png"),
        "button three": _drawn(tmp_path / "three.png", size=(140, 60)),
    })

    assert len({_tile(made, name).size() for name in _BUTTONS}) == 1


def _where(made, name):
    tile = _tile(made, name)
    column = tile.parentWidget().layout()
    layout = next(column.itemAt(i).layout() for i in range(column.count())
                  if isinstance(column.itemAt(i).layout(), QGridLayout))
    return layout.getItemPosition(layout.indexOf(tile))


def test_the_buttons_sit_where_the_grid_puts_them(window):
    made, _store, _stage = window("first")

    assert [_where(made, name)[:2] for name in _BUTTONS] == [(0, 0), (0, 1), (1, 0)]


def test_a_drawing_is_centered_on_a_white_square():
    source = QPixmap(40, 20)
    source.fill(Qt.GlobalColor.black)

    square = on_a_white_square(source, 96, 1.0)

    assert square.size() == QSize(96, 96)
    assert square.toImage().pixelColor(0, 0) == QColor(Qt.GlobalColor.white)
    assert square.toImage().pixelColor(48, 48) == QColor(Qt.GlobalColor.black)


def test_one_scale_fits_the_largest_drawing_and_leaves_the_others_smaller():
    big, small = QPixmap(120, 60), QPixmap(60, 30)

    scale = one_scale_for_all((big, small), 96)

    assert (round(big.width() * scale), round(small.width() * scale)) == (96, 48)


def test_a_drawing_that_will_not_load_does_not_set_the_scale():
    assert one_scale_for_all((QPixmap(),), 96) == 1.0


def test_a_tile_the_grid_merges_fills_both_of_its_columns(window):
    made, _store, _stage = window("gen-one", tiles=(Tile("button one", 0, 0, columns=2),
                                                    Tile("button two", 0, 2)))

    assert _where(made, "button one") == (0, 0, 1, 2)
    assert _tile(made, "button one").width() == (
        _tile(made, "button two").width() * 2 + GAP_MEDIUM)


def test_the_tile_down_every_row_is_as_tall_as_all_of_them_and_their_gaps(window):
    made, _store, _stage = window("gen-one", tiles=(Tile("button one", 0, 0),
                                                    Tile("button two", 1, 0),
                                                    Tile("button three", 0, 1, rows=2)))

    assert _where(made, "button three") == (0, 1, 2, 1)
    assert _tile(made, "button three").height() == (
        _tile(made, "button one").height() * 2 + GAP_MEDIUM)


def _drawing_rows(made, name):
    shot = _tile(made, name).grab().toImage()
    return [y for y in range(shot.height())
            if any(shot.pixelColor(x, y).red() > 150
                   and shot.pixelColor(x, y).green() < 100
                   for x in range(shot.width()))]


def test_a_tile_down_several_rows_draws_in_the_middle_of_them(window, tmp_path):
    names = ("button one", "button two", "button three", "button four")
    drawings = {name: _drawn(tmp_path / f"{name}.png", color="red") for name in names}
    made, _store, _stage = window(
        "gen-one", drawings=drawings,
        tiles=(Tile("button one", 0, 0), Tile("button two", 1, 0),
               Tile("button three", 2, 0), Tile("button four", 0, 1, rows=3)))

    def below_the_middle(name):
        rows = _drawing_rows(made, name)
        return (rows[0] + rows[-1]) // 2 - _tile(made, name).height() // 2

    assert abs(below_the_middle("button four") - below_the_middle("button two")) <= 2


def test_a_tile_down_several_rows_draws_no_box_of_one_row_inside_its_own(window, qtbot):
    made, _store, _stage = window("gen-one", tiles=(Tile("button one", 0, 0),
                                                    Tile("button two", 1, 0),
                                                    Tile("button three", 2, 0),
                                                    Tile("button four", 0, 1, rows=3)))
    made.setStyleSheet(build_stylesheet())
    with qtbot.waitExposed(made):
        made.show()
    tall = _tile(made, "button four")
    face = tall.findChild(QToolButton)
    shot = tall.grab().toImage()
    inside = 4

    ground = shot.pixelColor(inside, face.y() - inside).name()
    assert [shot.pixelColor(inside, y).name()
            for y in (face.y(), face.y() + face.height() - 1)] == [ground, ground]


def test_ten_rows_of_buttons_stand_in_the_room_the_window_has(window):
    rows = 10
    made, _store, _stage = window("gen-one", tiles=tuple(Tile(f"button {n}", n, 0)
                                                         for n in range(rows)))

    tall = _tile(made, "button 0").height()
    assert rows * tall + GAP_MEDIUM * (rows - 1) <= ROOM_FOR_THE_GRID


def test_a_term_too_wide_for_a_button_goes_on_to_the_next_line():
    assert wrapped_to_fit("alpha beta\ngamma", 9, len) == "alpha\nbeta\ngamma"


def test_a_term_that_fits_is_left_on_its_line():
    assert wrapped_to_fit("alpha beta", 10, len) == "alpha beta"


def test_no_button_or_checkbox_takes_the_keyboard_so_space_fires_nothing_pressed_before(window):
    made, _store, _stage = window("first", checkboxes=("first box",))
    pressable = (made.findChildren(QToolButton) + made.findChildren(QPushButton)
                 + made.findChildren(TickControl))

    assert pressable
    assert all(widget.focusPolicy() == Qt.FocusPolicy.NoFocus for widget in pressable)


THE_WINDOW_MAXIMIZED_ON_HIS_SCREEN = QSize(2560, 1410 - 31)


def _the_example_overlay() -> dict:
    return json.loads(EXAMPLE_CONTENT.read_text(encoding="utf-8"))


def _as_it_opens(qtbot, tmp_path, side, tiles, *, set_before: bool):
    named = vocabulary(side, _the_example_overlay())
    named = Vocabulary(named.buttons, tiles or named.tiles, named.checkboxes, {}, {}, {}, {})
    labels = Labels(next(iter(named.buttons.values())), named.checkboxes) if set_before else None
    made = ActionSetterWindow(SetterSession(_set_before(("first", labels)), _Store(), side),
                              named, {}, Locks(tmp_path / f"{set_before}.json"), stage=_Stage())
    qtbot.addWidget(made)
    made.setStyleSheet(build_stylesheet())
    made.resize(THE_WINDOW_MAXIMIZED_ON_HIS_SCREEN)
    made.show()
    made.layout().activate()
    return made


def _top(made, widget) -> int:
    return widget.mapTo(made, QPoint()).y()


def _ten_rows_the_grid_has_room_for() -> tuple[Tile, ...]:
    return tuple(Tile(f"button {n}", n, 0) for n in range(10))


@pytest.mark.parametrize(("side", "tiles"), [
    (MediaType.IMAGE, None),
    (MediaType.VIDEO, None),
    (MediaType.IMAGE, _ten_rows_the_grid_has_room_for()),
])
def test_neither_setter_tool_needs_a_vertical_scrollbar_with_the_yellow_line_showing(
        qtbot, tmp_path, side, tiles):
    shown = _as_it_opens(qtbot, tmp_path, side, tiles, set_before=True)
    without = _as_it_opens(qtbot, tmp_path, side, tiles, set_before=False)
    boxes, first_tile = shown._vocabulary.checkboxes, next(iter(shown._tiles))
    line, box, last_lock = _previously(shown), _box(shown, boxes[0]), _lock(shown, boxes[-1])
    column = shown.findChild(QScrollArea)

    assert (line.isHidden(), _previously(without).isHidden()) == (False, True)
    assert (column.verticalScrollBar().maximum(), column.height()) == (
        0, shown.height() - 2 * MARGIN_STANDARD)
    assert _top(shown, box) <= _top(shown, line) + line.height() // 2 <= _top(shown, box) + box.height()
    assert line.mapTo(shown, QPoint()).x() > last_lock.mapTo(shown, QPoint()).x()
    assert (_top(shown, _tile(shown, first_tile)), column.widget().minimumSizeHint().height()) == (
        _top(without, _tile(without, first_tile)),
        without.findChild(QScrollArea).widget().minimumSizeHint().height())


def test_the_action_setter_tool_opened_in_a_preview_names_the_preview(window, monkeypatch):
    monkeypatch.setenv("ORIGENERATOR_BRANCH_SESSION", "1")
    monkeypatch.setattr("origenerator.branch_session.preview_of",
                        lambda checkout: Preview(feature="Example scene pausing"))

    made, _store, _stage = window("first")

    assert made.windowTitle() == "Origenerator — image action setter tool — preview of Example scene pausing"
