from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QWidget

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
    narrow = layout.heightForWidth(200)   # one tile per row -> eight rows tall
    wide = layout.heightForWidth(900)     # several per row -> only a couple rows
    assert wide < narrow


def test_wrapped_rows_can_sit_further_apart_than_the_buttons_in_them(qtbot):
    """A row of buttons wants its items close and its rows apart.  At the one
    gap this layout used for both, the gallery's button bank wrapped into two
    rows that all but touched."""
    from PyQt6.QtWidgets import QPushButton, QWidget

    host = QWidget()
    qtbot.addWidget(host)
    flow = FlowLayout(host, spacing=4, row_spacing=20)
    for _ in range(6):
        button = QPushButton("x")
        button.setFixedSize(40, 20)
        flow.addWidget(button)
    host.resize(100, 200)          # two per row
    flow.setGeometry(host.rect())

    tops = sorted({flow.itemAt(i).geometry().top() for i in range(flow.count())})
    assert len(tops) > 1, "nothing wrapped, so there is no row gap to check"
    assert tops[1] - tops[0] == 20 + 20   # a row's height plus the row gap


def test_the_row_gap_defaults_to_the_one_between_buttons(qtbot):
    from PyQt6.QtWidgets import QWidget

    host = QWidget()
    qtbot.addWidget(host)
    assert FlowLayout(host, spacing=7)._row_spacing == 7


def test_flow_layout_lays_every_item_out_at_its_own_size(qtbot):
    # What a QHBoxLayout does instead: squeeze past the minimum and clip, which is
    # how a bank of buttons came out reading "o fo", "to E", "ner".
    host = QWidget()
    qtbot.addWidget(host)
    layout = FlowLayout(host, spacing=6)
    for _ in range(3):
        tile = QWidget()
        tile.setFixedSize(120, 30)
        layout.addWidget(tile)
    host.resize(150, 200)          # room for one across, not three
    host.show()

    assert [w.width() for w in host.findChildren(QWidget)] == [120, 120, 120]


def test_align_right_pushes_each_row_against_the_right_edge(qtbot):
    # A button bank sits in the lower-right corner, and has to stay there as it
    # wraps rather than walk off to the left.
    host = QWidget()
    qtbot.addWidget(host)
    layout = FlowLayout(host, spacing=6, align_right=True)
    tiles = []
    for width in (120, 80):
        tile = QWidget()
        tile.setFixedSize(width, 30)
        layout.addWidget(tile)
        tiles.append(tile)
    host.resize(150, 200)          # only one fits across: two rows
    host.show()

    assert tiles[0].y() < tiles[1].y()                       # it wrapped
    for tile in tiles:
        assert tile.x() + tile.width() == host.width()       # ...against the edge


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
    host.resize(300, 200)          # room for all three side by side, were it a tile
    host.show()

    assert (heading.x(), heading.width()) == (0, 300)
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
