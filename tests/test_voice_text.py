"""Reducing a transcription to words, and hearing a word through a mis-render."""
from __future__ import annotations

from origenerator.voice.text import sounds_like, words


def test_case_and_punctuation_are_whispers_not_the_speakers():
    assert words("Fix Teeth.") == ["fix", "teeth"]
    assert words(None) == []


def test_apostrophes_are_kept_only_where_the_matcher_asks():
    assert words("don't") == ["don", "t"]
    assert words("don't", keep_apostrophes=True) == ["don't"]


def test_digits_are_kept_only_where_the_matcher_asks():
    assert words("window 3") == ["window"]
    assert words("window 3", keep_digits=True) == ["window", "3"]


def test_a_word_is_heard_through_a_single_wrong_letter():
    # Off a quiet mic the base model lands the shape of a short word and misses
    # a letter of it, so an exact test drops requests the speaker clearly made.
    assert sounds_like("fix", ("fix", "fixed"))
    assert sounds_like("six", ("fix", "fixed"))
    assert sounds_like("fixes", ("fix", "fixed"))


def test_a_word_of_another_length_is_a_different_word():
    # Length still has to match, which keeps the tolerance from swallowing
    # ordinary speech.
    assert not sounds_like("fi", ("fix", "fixed"))
    assert not sounds_like("fixer", ("fix",))
