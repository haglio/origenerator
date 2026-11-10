from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QPushButton, QWidget

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
    assert wide < narrow


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

    assert [w.width() for w in host.findChildren(QWidget)] == [120, 120, 120]


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
