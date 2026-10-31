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
    xml = windows_toast.toast_xml("Video ready", "Example Workflow · 4:12",
                                  link="origenerator:go-to?generation=alpha-1",
                                  mark=Path(r"C:\marks\ready.png"))

    toast, lines, image = _read(xml)
    assert toast.get("activationType") == "protocol"
    assert toast.get("launch") == "origenerator:go-to?generation=alpha-1"
    assert lines == ["Video ready", "Example Workflow · 4:12"]
    assert image.get("placement") == "appLogoOverride"
    assert image.get("src") == "file:///C:/marks/ready.png"


def test_a_toast_about_no_item_has_no_link_for_a_click_to_follow():
    xml = windows_toast.toast_xml("LoRA ready", "Hands fix · 49:12", link=None)

    toast, lines, _image = _read(xml)
    assert (toast.get("activationType"), toast.get("launch")) == (None, None)
    assert lines == ["LoRA ready", "Hands fix · 49:12"]
    assert windows_toast.document_of(xml)


def test_a_workflow_name_with_markup_in_it_is_said_rather_than_read():
    # Whatever a workflow is called is somebody's words, and
    # Windows reads a toast as a document.
    xml = windows_toast.toast_xml("Image & <b>more</b>", 'a "quoted" workflow',
                                  link='origenerator:go-to?generation="x"',
                                  mark=Path(r"C:\marks\ready.png"))

    toast, lines, _image = _read(xml)
    assert lines == ["Image & <b>more</b>", 'a "quoted" workflow']
    assert toast.get("launch") == 'origenerator:go-to?generation="x"'


def test_windows_reads_what_a_toast_document_says():
    # The document is Windows' own parser's, not this app's: a toast it cannot
    # read is a notification that never appears, and there is nothing to see.
    document = windows_toast.document_of(
        windows_toast.toast_xml("Video ready", "Example Workflow · 4:12",
                                link="origenerator:go-to?generation=alpha-1",
                                mark=Path(r"C:\marks\ready.png")))

    assert document


def test_a_document_windows_cannot_read_is_refused_rather_than_raised():
    with pytest.raises(OSError, match=r"call \d+ failed: 0x"):
        windows_toast.document_of("<toast>unclosed")


_A_TOAST = windows_toast.toast_xml("Video ready", "Example Workflow · 4:12",
                                   link="origenerator:go-to?generation=alpha-1")


def test_a_toast_is_filed_under_a_tag_and_a_group_of_up_to_64_characters_each():
    with windows_toast.filed(_A_TOAST, tag="t" * 64, group="g" * 64) as toast:
        assert toast


@pytest.mark.parametrize("filing", [dict(tag="t" * 65, group="g"), dict(tag="t", group="g" * 65)])
def test_a_name_longer_than_windows_files_under_is_refused_before_anything_is_raised(filing):
    with pytest.raises(OSError, match=r"call \d+ failed: 0x"), windows_toast.filed(_A_TOAST, **filing):
        pass


def test_taking_back_a_notification_nobody_raised_is_no_error():
    # Under an app id nothing uses, so it reaches no notification of the user's.
    windows_toast.take_back("Example.NothingUsesThisId", tag="never-raised", group="runs")
