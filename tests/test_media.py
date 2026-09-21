from __future__ import annotations

from origenerator.gallery.keys import settings_key
from origenerator.media import MediaType, media_type_from_filename, sibling_of_type


def test_media_type_from_filename_classifies_by_extension():
    assert media_type_from_filename("sdxl_t2i_00001_.png") is MediaType.IMAGE
    assert media_type_from_filename("photo.JPEG") is MediaType.IMAGE
    assert media_type_from_filename("wan22_i2v_00001_.mp4") is MediaType.VIDEO
    assert media_type_from_filename("clip.WEBM") is MediaType.VIDEO
    assert media_type_from_filename("notes.txt") is None
    assert media_type_from_filename("") is None


def test_the_media_types_are_the_two_strings_rows_have_always_been_filed_under():
    assert {kind.value for kind in MediaType} == {"image", "video"}


def test_a_folder_key_spells_its_media_type_the_way_stored_keys_already_do():
    assert settings_key(MediaType.VIDEO, "wan22_i2v", "{}") == \
        settings_key("video", "wan22_i2v", "{}")


def test_sibling_of_type_finds_same_stem_file_of_other_media(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"v")
    png = tmp_path / "clip.png"
    png.write_bytes(b"p")

    assert sibling_of_type(video, MediaType.IMAGE) == png
    assert sibling_of_type(png, MediaType.VIDEO) == video


def test_a_media_kind_that_was_never_made_has_no_sibling(tmp_path):
    lone = tmp_path / "clip.mp4"
    lone.write_bytes(b"v")
    assert sibling_of_type(lone, MediaType.IMAGE) is None
