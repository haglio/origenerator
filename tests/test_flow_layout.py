from PyQt6.QtWidgets import QWidget

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
    """A row of buttons wants its members close and its rows apart.  At the one
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
