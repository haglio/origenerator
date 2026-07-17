"""The generation drag payload every drag source builds and each drop slot reads."""

from origenerator.gui import generation_drag


def test_generation_mime_carries_the_prompt_id():
    # The drag payload a slot reads to know which generation was dropped.
    mime = generation_drag.generation_mime("abc123")
    assert mime.hasFormat(generation_drag.GENERATION_MIME)
    assert bytes(mime.data(generation_drag.GENERATION_MIME)) == b"abc123"
