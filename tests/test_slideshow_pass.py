from __future__ import annotations

from dataclasses import dataclass

from origenerator.funscript import synthesize_actions, write_funscript
from origenerator.gui import slideshow_pass
from origenerator.gui.slideshow_pass import playlist_item, rotated_onto
from origenerator.media import MediaType
from origenerator.output_places import OutputPlaces


@dataclass
class _Slide:
    prompt_id: str | None


def test_the_pass_is_turned_so_the_slide_on_screen_leads_and_the_order_is_otherwise_kept():
    a, b, c, d = _Slide("a"), _Slide("b"), _Slide("c"), _Slide("d")

    assert rotated_onto([a, b, c, d], c) == [c, d, a, b]


def test_the_slide_on_screen_is_found_by_its_generation_when_the_set_holds_another_copy_of_it():
    items = [_Slide("a"), _Slide("b"), _Slide("c")]

    assert rotated_onto(items, _Slide("b")) == [items[1], items[2], items[0]]


def test_a_pass_with_nothing_on_screen_or_without_the_slide_on_screen_is_left_alone():
    items = [_Slide("a"), _Slide(None), _Slide("c")]

    assert rotated_onto(items, None) is items
    assert rotated_onto(items, _Slide("z")) is items
    assert rotated_onto(items, _Slide(None)) is items


def test_an_upscale_another_site_made_plays_with_the_script_filed_for_it_in_the_library(
        tmp_path, monkeypatch):
    library = tmp_path / "videos" / "videos"
    upscale = library / "kino" / "2D" / "AI" / "landscape" / "example_site" / "video_one_topaz.mp4"
    script = tmp_path / "videos" / "scripts" / "scripts" / "kino" / "2D" / "AI" / "landscape" / (
        "example_site/video_one_topaz.funscript")
    write_funscript(script, synthesize_actions(2.0, hz=1.0))
    monkeypatch.setattr(slideshow_pass, "OUTPUT_PLACES",
                        OutputPlaces.in_one_folder(tmp_path / "output", library=library))

    assert playlist_item(upscale, MediaType.VIDEO).funscript == script
