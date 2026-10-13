"""The generation drag payload every drag source builds and each drop target reads."""
from __future__ import annotations

from PyQt6.QtCore import QMimeData

from origenerator.gui import generation_drag


def test_a_dropped_payload_names_the_generation_that_was_dragged():
    assert generation_drag.dropped_generation(generation_drag.generation_mime("abc123")) == "abc123"


def test_a_payload_from_anywhere_else_names_no_generation():
    mime = QMimeData()
    mime.setText("abc123")
    assert generation_drag.dropped_generation(mime) is None
