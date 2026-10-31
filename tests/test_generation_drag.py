"""The generation drag payload every drag source builds and each drop zone reads."""
from __future__ import annotations

from PyQt6.QtCore import QMimeData

from origenerator.gui import generation_drag


def test_generation_mime_carries_the_prompt_id():
    # The drag payload a drop zone reads to know which generation was dropped.
    mime = generation_drag.generation_mime("abc123")
    assert mime.hasFormat(generation_drag.GENERATION_MIME)
    assert bytes(mime.data(generation_drag.GENERATION_MIME)) == b"abc123"


def test_the_payload_reads_back_as_the_prompt_id_it_names():
    mime = generation_drag.generation_mime("abc123")
    assert generation_drag.dragged_generation(mime) == "abc123"


def test_a_drag_naming_no_generation_reads_back_as_none():
    other = QMimeData()
    other.setText("abc123")  # a plain-text drag from anywhere else
    assert generation_drag.dragged_generation(other) is None
