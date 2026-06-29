from origenerator.media import media_type_from_filename


def test_media_type_from_filename_classifies_by_extension():
    assert media_type_from_filename("sdxl_t2i_00001_.png") == "image"
    assert media_type_from_filename("photo.JPEG") == "image"
    assert media_type_from_filename("wan22_i2v_00001_.mp4") == "video"
    assert media_type_from_filename("clip.WEBM") == "video"
    assert media_type_from_filename("notes.txt") is None
    assert media_type_from_filename("") is None
