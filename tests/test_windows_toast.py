"""The notification Windows itself raises, and what it is told to draw.

Nothing here shows one: a toast raised by a test is a toast on the user's
screen and a line in their notification center, so what is exercised is
everything up to the raising -- the document Windows reads, and the refusal of
one it cannot.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

import pytest

from origenerator import windows_toast


def _read(xml: str):
    toast = ElementTree.fromstring(xml)
    binding = toast.find("./visual/binding")
    return toast, [text.text for text in binding.findall("text")], binding.find("image")


def test_a_toast_says_the_two_lines_and_carries_the_link_a_click_follows():
    xml = windows_toast.toast_xml("Video ready", "Example Recipe · 4:12",
                                  link="origenerator:go-to?generation=alpha-1",
                                  mark=Path(r"C:\marks\ready.png"))

    toast, lines, image = _read(xml)
    assert toast.get("activationType") == "protocol"
    assert toast.get("launch") == "origenerator:go-to?generation=alpha-1"
    assert lines == ["Video ready", "Example Recipe · 4:12"]
    assert image.get("placement") == "appLogoOverride"
    assert image.get("src") == "file:///C:/marks/ready.png"


def test_a_recipe_name_with_markup_in_it_is_said_rather_than_read():
    # Whatever a recipe or a workflow is called is somebody's words, and
    # Windows reads a toast as a document.
    xml = windows_toast.toast_xml("Image & <b>more</b>", 'a "quoted" recipe',
                                  link='origenerator:go-to?generation="x"',
                                  mark=Path(r"C:\marks\ready.png"))

    toast, lines, _image = _read(xml)
    assert lines == ["Image & <b>more</b>", 'a "quoted" recipe']
    assert toast.get("launch") == 'origenerator:go-to?generation="x"'


def test_windows_reads_what_a_toast_document_says():
    # The document is Windows' own parser's, not this app's: a toast it cannot
    # read is a notification that never appears, and there is nothing to see.
    document = windows_toast.document_of(
        windows_toast.toast_xml("Video ready", "Example Recipe · 4:12",
                                link="origenerator:go-to?generation=alpha-1",
                                mark=Path(r"C:\marks\ready.png")))

    assert document


def test_a_document_windows_cannot_read_is_refused_rather_than_raised():
    with pytest.raises(OSError):
        windows_toast.document_of("<toast>unclosed")
