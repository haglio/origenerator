"""The shapes the tree remembers, and what it forgets.

``row_orientation`` opens a file to find out which region its media belongs on,
and keeps the answer against the path that gave it — a rebuild re-reads every row
and the poll rebuilds every 1.5 s, so measuring afresh each time would mean a
thumbnail opened per row per second.  Kept for ever, though, that is a dict with
an entry for every file the app has looked at since it launched and no way for
one to leave: a generation deleted an hour ago still holds its slot.
"""

from types import SimpleNamespace

import pytest

from origenerator.gui import orientation


class _FakeImage:
    """A stand-in for a decoded file: the size is all the shape is read from."""

    def __init__(self, size):
        self.size = size

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def _a_cache_of_this_files_own(monkeypatch):
    """These tests fill the cache; nothing after them should inherit it."""
    monkeypatch.setattr(orientation, "_measured", type(orientation._measured)())


@pytest.fixture(autouse=True)
def _every_path_reads_as_a_tall_picture(monkeypatch):
    """Measure without a file: what is on disk is not what these tests are about,
    and a thousand real PNGs would only be a slower way to ask the same thing."""
    monkeypatch.setattr(
        orientation, "Image", SimpleNamespace(open=lambda path: _FakeImage((90, 160))))


def _measure(name: str) -> str:
    return orientation.row_orientation({"thumbnail_path": f"/library/{name}.png"})


def test_the_remembered_shapes_stop_piling_up():
    for n in range(orientation._MEASURED_LIMIT + 100):
        assert _measure(f"m{n}") == orientation.PORTRAIT

    assert len(orientation._measured) <= orientation._MEASURED_LIMIT


def test_the_one_it_drops_is_the_one_nothing_has_asked_for():
    """A library past the cap still has one folder open in front of it, and the
    rows the poll redraws must outlast the ones scrolled past once."""
    for n in range(orientation._MEASURED_LIMIT):
        _measure(f"m{n}")
    _measure("m0")  # asked for again, so no longer the oldest thing here

    _measure("late")  # one over: something has to go

    assert "/library/m0.png" in orientation._measured
    assert "/library/m1.png" not in orientation._measured
