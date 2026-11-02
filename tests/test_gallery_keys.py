from __future__ import annotations

from origenerator.gallery.keys import (
    folder_id,
    lora_key,
    model_key,
    settings_key,
    source_image_key,
)

_HEX = set("0123456789abcdef")


def _segment(key: str) -> str:
    return key.rsplit("/", 1)[1]


def test_a_settings_folders_segment_is_pure_hex():
    assert set(_segment(settings_key("image", "sdxl_t2i", "steps=30"))) <= _HEX


def test_no_other_levels_key_can_collide_with_a_settings_key():
    for key in (model_key, lora_key, source_image_key):
        assert not set(_segment(key("image", "sdxl_t2i", "steps=30"))) <= _HEX


def test_the_levels_of_one_signature_have_keys_of_their_own():
    keys = {settings_key("image", "w", "s"), model_key("image", "w", "s"),
            lora_key("image", "w", "s"), source_image_key("image", "w", "s")}

    assert len(keys) == 4


def test_a_folders_generic_name_is_one_short_upper_case_code():
    name = folder_id(settings_key("image", "sdxl_t2i", "steps=30"))

    assert len(name) == 8
    assert name == name.upper()
    assert name == folder_id(settings_key("image", "sdxl_t2i", "steps=30"))
