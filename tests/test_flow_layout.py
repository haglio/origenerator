from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from origenerator.gui import flow_layout
from origenerator.gui.flow_layout import FlowLayout


def test_flow_layout_tracks_and_releases_items(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    layout = FlowLayout(host)
    a, b = QWidget(), QWidget()
    layout.addWidget(a)
    layout.addWidget(b)

    assert layout.count() == 2
    assert layout.itemAt(0).widget() is a
    assert layout.itemAt(1).widget() is b

    assert layout.takeAt(0).widget() is a
    assert layout.count() == 1
    assert layout.itemAt(0).widget() is b


def test_flow_layout_fits_more_per_row_when_wider(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    layout = FlowLayout(host, spacing=8)
    for _ in range(8):
        tile = QWidget()
        tile.setFixedSize(180, 200)
        layout.addWidget(tile)

    assert layout.hasHeightForWidth()
    narrow = layout.heightForWidth(200)
    wide = layout.heightForWidth(900)
    assert wide < narrow, (
        "unlike a QGridLayout's fixed column count, this fits as many items in a row as the "
        "width allows and flows them again on a resize")


def test_items_that_exactly_fill_the_width_stay_on_one_row(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    layout = FlowLayout(host, spacing=8)
    for _ in range(2):
        tile = QWidget()
        tile.setFixedSize(96, 96)
        layout.addWidget(tile)

    assert layout.heightForWidth(96 + 8 + 96) == 96


def test_wrapped_rows_can_sit_further_apart_than_the_buttons_in_them(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    flow = FlowLayout(host, spacing=4, row_spacing=20)
    for _ in range(6):
        button = QPushButton("x")
        button.setFixedSize(40, 20)
        flow.addWidget(button)
    host.resize(100, 200)
    flow.setGeometry(host.rect())

    tops = sorted({flow.itemAt(i).geometry().top() for i in range(flow.count())})
    assert len(tops) > 1, "nothing wrapped, so there is no row gap to check"
    assert tops[1] - tops[0] == 20 + 20, (
        "a row of buttons wants its items close and its rows apart: at one gap for both, two "
        "wrapped rows read as a single crowded block")


def test_a_hidden_widget_takes_no_place_and_leaves_no_gap_where_it_was(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    flow = FlowLayout(host, spacing=4)
    buttons = [QPushButton(str(n)) for n in range(3)]
    for button in buttons:
        button.setFixedSize(40, 20)
        flow.addWidget(button)
    buttons[1].hide()
    host.resize(300, 100)
    flow.setGeometry(host.rect())

    assert flow.itemAt(2).geometry().left() == flow.itemAt(0).geometry().right() + 1 + 4


def test_the_row_gap_defaults_to_the_one_between_buttons(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    assert FlowLayout(host, spacing=7)._row_spacing == 7


def test_flow_layout_lays_every_item_out_at_its_own_size(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    layout = FlowLayout(host, spacing=6)
    for _ in range(3):
        tile = QWidget()
        tile.setFixedSize(120, 30)
        layout.addWidget(tile)
    host.resize(150, 200)
    host.show()

    assert [w.width() for w in host.findChildren(QWidget)] == [120, 120, 120], (
        "unlike a QHBoxLayout, every item is laid out at its own size hint, so a row of buttons "
        "wraps onto a second line rather than squeezing every label down to an unreadable stub")


def test_align_right_pushes_each_row_against_the_right_edge(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    layout = FlowLayout(host, spacing=6, align_right=True)
    tiles = []
    for width in (120, 80):
        tile = QWidget()
        tile.setFixedSize(width, 30)
        layout.addWidget(tile)
        tiles.append(tile)
    host.resize(150, 200)
    host.show()

    assert tiles[0].y() < tiles[1].y()
    for tile in tiles:
        assert tile.x() + tile.width() == host.width()


def test_a_trailing_item_sits_against_the_right_edge_of_whichever_row_it_lands_on(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    layout = FlowLayout(host, spacing=6)
    leading, trailing = QWidget(), QWidget()
    leading.setFixedSize(120, 30)
    trailing.setFixedSize(80, 30)
    layout.addWidget(leading)
    layout.add_trailing(trailing)
    host.resize(400, 200)
    host.show()
    assert (leading.x(), trailing.y()) == (0, leading.y())
    assert trailing.x() + trailing.width() == host.width()

    host.resize(150, 200)
    layout.activate()

    assert trailing.y() > leading.y()
    assert trailing.x() + trailing.width() == host.width()


def test_an_item_wider_than_the_whole_row_is_narrowed_to_the_row_rather_than_cut_off(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    layout = FlowLayout(host)
    wide = QLabel("a label far wider than the row it has to sit in")
    wide.setMinimumWidth(40)
    layout.addWidget(wide)
    host.resize(120, 100)
    host.show()

    assert (wide.x(), wide.width()) == (0, 120)


def test_a_full_row_sits_alone_across_the_whole_width_between_the_rows_of_tiles(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    layout = FlowLayout(host, spacing=6)
    above, heading, below = QWidget(), QLabel("scene one"), QWidget()
    above.setFixedSize(40, 30)
    below.setFixedSize(40, 30)
    layout.addWidget(above)
    layout.add_full_row(heading)
    layout.addWidget(below)
    room_for_all_three_side_by_side = 300
    host.resize(room_for_all_three_side_by_side, 200)
    host.show()

    assert (heading.x(), heading.width()) == (0, room_for_all_three_side_by_side)
    assert above.y() < heading.y() < below.y()
    assert below.x() == 0


def test_a_full_row_never_holds_the_layout_wider_than_its_tiles(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    layout = FlowLayout(host)
    tile = QWidget()
    tile.setFixedSize(40, 30)
    layout.addWidget(tile)
    layout.add_full_row(QLabel("a heading a good deal wider than the one tile under it"))

    assert layout.minimumSize().width() == 40


def _squares(count: int) -> list[QWidget]:
    made = []
    for _ in range(count):
        square = QWidget()
        square.setFixedSize(40, 40)
        made.append(square)
    return made


def test_a_group_that_does_not_fit_the_row_moves_to_the_next_row_whole(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    flow = FlowLayout(host, spacing=4, group_spacing=16)
    first, second = _squares(2), _squares(3)
    flow.add_group(first)
    flow.add_group(second)

    flow.setGeometry(QRect(0, 0, 40 + 4 + 40 + 16 + 40 + 4 + 40, 200))

    assert [square.y() for square in first + second] == [0, 0, 44, 44, 44], (
        "a group of buttons wraps as one: room for two of the second group's three is no "
        "reason to leave its third alone on the row below")
    assert [square.x() for square in second] == [0, 44, 88], (
        "a group that starts a row starts at the row's edge, with no gap in front of it")


def test_groups_on_one_row_stand_the_wider_gap_apart(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    flow = FlowLayout(host, spacing=4, group_spacing=16)
    first, second = _squares(2), _squares(1)
    flow.add_group(first)
    flow.add_group(second)

    flow.setGeometry(QRect(0, 0, 400, 200))

    assert [square.x() for square in first + second] == [0, 44, 44 + 40 + 16]


def test_a_group_with_nothing_showing_leaves_no_gap(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    flow = FlowLayout(host, spacing=4, group_spacing=16)
    first, hidden, last = _squares(1), _squares(1), _squares(1)
    for group in (first, hidden, last):
        flow.add_group(group)
    hidden[0].hide()

    flow.setGeometry(QRect(0, 0, 400, 200))

    assert last[0].x() == 40 + 16


def test_a_group_wider_than_the_whole_row_wraps_inside_itself(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    flow = FlowLayout(host, spacing=4, group_spacing=16)
    group = _squares(3)
    flow.add_group(group)

    flow.setGeometry(QRect(0, 0, 90, 200))

    assert [(square.x(), square.y()) for square in group] == [(0, 0), (44, 0), (0, 44)]


def _tiles_in(host, count: int, size=(180, 200)) -> FlowLayout:
    layout = FlowLayout(host, spacing=8)
    for _ in range(count):
        tile = QWidget()
        tile.setFixedSize(*size)
        layout.addWidget(tile)
    return layout


def test_a_height_asked_for_again_at_the_same_width_is_not_worked_out_again(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    layout = _tiles_in(host, 40)
    worked_out = []
    rows = layout._rows
    layout._rows = lambda area, *rest: worked_out.append(area.width()) or rows(area, *rest)

    heights = {layout.heightForWidth(900) for _scroll_step in range(5)}

    assert (len(heights), worked_out) == (1, [900]), (
        "the gallery asks for its height on every scroll step, and working it out walks "
        "every tile drawn")


def _changes(layout):
    caption = QLabel("a caption")
    caption.setWordWrap(True)
    tile = QWidget()
    tile.setFixedSize(180, 200)
    first = layout.itemAt(0).widget()
    return [
        ("a tile added", lambda: layout.addWidget(tile)),
        ("a wrapping caption added", lambda: layout.add_full_row(caption)),
        ("the caption grown to several lines", lambda: caption.setText("words " * 200)),
        ("a tile hidden", first.hide),
        ("the tile shown again", first.show),
        ("a tile grown", lambda: tile.setFixedSize(180, 420)),
        ("the rows set further apart", lambda: layout.set_row_spacing(30)),
        ("an item taken out", lambda: layout.takeAt(1)),
    ]


def test_the_height_kept_for_a_width_is_the_height_worked_out_afresh_after_any_change(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    host.show()
    layout = _tiles_in(host, 9)

    for change, make in _changes(layout):
        layout.heightForWidth(600)
        make()
        fresh = layout._do_layout(QRect(0, 0, 600, 0), place=False)
        assert layout.heightForWidth(600) == fresh, change


def _placed(layout) -> list[QRect]:
    return [layout.itemAt(at).geometry() for at in range(layout.count())]


def _laid_out_afresh(layout, width: int) -> list[QRect]:
    layout.invalidate()
    layout.setGeometry(QRect(0, 0, width, 0))
    return _placed(layout)


def _tiles_sized_to_place_seven_more_after(qtbot, monkeypatch, drawn: int):
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(900, 6000)
    layout = _tiles_in(host, drawn)
    host.show()
    layout.activate()
    sized = []
    size_within = flow_layout._hint_within
    monkeypatch.setattr(flow_layout, "_hint_within",
                        lambda item, width: sized.append(item) or size_within(item, width))
    with layout.appending():
        for _ in range(7):
            tile = QWidget(host)
            tile.setFixedSize(180, 200)
            layout.addWidget(tile)
            tile.show()
    layout.activate()
    monkeypatch.undo()
    assert _placed(layout) == _laid_out_afresh(layout, 900)
    return len(sized)


def test_tiles_added_at_the_end_are_placed_without_placing_the_grid_again(qtbot, monkeypatch):
    after_a_few = _tiles_sized_to_place_seven_more_after(qtbot, monkeypatch, 40)
    after_many = _tiles_sized_to_place_seven_more_after(qtbot, monkeypatch, 400)

    assert after_many == after_a_few, (
        "placing the whole grid again for each few tiles drawn takes longer the further down "
        "the gallery is")


def test_a_change_made_while_nothing_is_being_added_places_the_whole_grid_again(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    host.show()
    layout = _tiles_in(host, 9)

    for change, make in _changes(layout):
        layout.setGeometry(QRect(0, 0, 600, 0))
        make()
        layout.setGeometry(QRect(0, 0, 600, 0))
        placed = _placed(layout)
        assert placed == _laid_out_afresh(layout, 600), change
