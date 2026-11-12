from __future__ import annotations

from PySide6.QtGui import QKeySequence

from origenerator.gui.motion_hud import apply_motion_key
from origenerator.reference import reference_sections
from origenerator.voice.app_commands import _PHRASES, BarSetting
from origenerator.voice.slideshow_commands import SlideshowCommand, said_to_the_slideshow


def _rows():
    return [row for section in reference_sections() for row in section.rows]


def _said() -> set[str]:
    return {phrase for row in _rows() for phrase in row.voice}


def _written(phrase: str) -> str:
    return phrase.replace("o s r two", "OSR2").replace("osr two", "OSR2")


def _section(title: str):
    return next(section for section in reference_sections() if section.title == title)


def test_the_sections_are_core_the_image_on_screen_the_osr2_and_the_slideshow():
    assert [section.title for section in reference_sections()] == [
        "Core", "The image on screen", "OSR2", "Slideshow"]


def test_every_word_origenerator_answers_is_on_some_row():
    words = {_written(phrase) for phrase, meant in _PHRASES.items()
             if not isinstance(meant, BarSetting)}

    assert words - _said() == set()


def test_every_spoken_slideshow_order_is_on_some_row():
    assert set(said_to_the_slideshow(*SlideshowCommand)) <= _said()


def test_the_osr2_s_keys_are_the_ones_the_motion_answers():
    class Motion:
        def __getattr__(self, _name):
            return lambda *_args: None

    for row in _section("OSR2").rows:
        for column in row.key_columns:
            for key in column:
                assert apply_motion_key(Motion(), QKeySequence(key)[0].key()), key


def test_an_action_opens_lowercase_unless_it_opens_with_a_name():
    names = ("Latest", "Favorites", "Experiments", "Populate", "Origenerator", "Request",
             "HUD")
    for row in _rows():
        assert row.description[0].islower() or row.description.startswith(names), row.description


def test_the_osr2_is_written_as_the_app_shows_it_and_each_phrase_once():
    control = _section("OSR2").rows[0]

    assert "OSR2 control on" in control.voice
    assert not any("two" in phrase for phrase in control.voice)
    assert len(control.voice) == len(set(control.voice))
