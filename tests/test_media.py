from origenerator.media import media_type_from_filename, sibling_of_type


def test_media_type_from_filename_classifies_by_extension():
    assert media_type_from_filename("sdxl_t2i_00001_.png") == "image"
    assert media_type_from_filename("photo.JPEG") == "image"
    assert media_type_from_filename("wan22_i2v_00001_.mp4") == "video"
    assert media_type_from_filename("clip.WEBM") == "video"
    assert media_type_from_filename("notes.txt") is None
    assert media_type_from_filename("") is None


def test_sibling_of_type_finds_same_stem_file_of_other_media(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"v")
    png = tmp_path / "clip.png"
    png.write_bytes(b"p")

    assert sibling_of_type(video, "image") == png
    assert sibling_of_type(png, "video") == video


def test_sibling_of_type_returns_none_when_absent(tmp_path):
    lone = tmp_path / "clip.mp4"
    lone.write_bytes(b"v")
    assert sibling_of_type(lone, "image") is None
