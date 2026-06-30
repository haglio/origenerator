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
