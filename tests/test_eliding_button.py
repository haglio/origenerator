from PyQt6.QtWidgets import QPushButton

from origenerator.gui.eliding_button import ElidingButton

_LONG = "Show in Explorer"


def test_it_does_not_hold_a_pane_open_at_its_label(qtbot):
    # The failure this exists for: a button's own minimum is its whole label, so
    # one sitting in a file row set a floor under the info pane and the settings
    # scroll grew a horizontal bar rather than let the row shrink.
    stock = QPushButton(_LONG)
    qtbot.addWidget(stock)
    button = ElidingButton(_LONG)
    qtbot.addWidget(button)

    assert button.minimumSizeHint().width() < stock.minimumSizeHint().width() / 2
    assert button.minimumSizeHint().width() < button.fontMetrics().horizontalAdvance(_LONG)


def test_it_asks_for_its_whole_label_when_there_is_room(qtbot):
    # Only the floor moves: given the space, it still wants to read in full.
    stock = QPushButton(_LONG)
    qtbot.addWidget(stock)
    button = ElidingButton(_LONG)
    qtbot.addWidget(button)

    assert button.sizeHint() == stock.sizeHint()


def test_a_squeezed_label_elides_rather_than_clips(qtbot):
    button = ElidingButton(_LONG)
    qtbot.addWidget(button)
    whole = button.fontMetrics().horizontalAdvance(_LONG)

    assert button.display_text(whole) == _LONG
    squeezed = button.display_text(whole // 3)
    assert squeezed != _LONG
    assert squeezed.endswith("…")


def test_an_ampersand_survives_as_a_character_not_a_mnemonic(qtbot):
    # Qt eats a lone "&" as an accelerator marker, so the button's text carries it
    # doubled — and the eliding happens on the raw label, which is what stops a
    # cut landing between the pair.
    button = ElidingButton("Model & LoRA")
    qtbot.addWidget(button)

    assert button.text() == "Model && LoRA"
    assert button.display_text(10_000) == "Model & LoRA"
