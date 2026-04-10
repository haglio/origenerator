from pathlib import Path

from PIL import Image

from origenerator.thumbnail import generate_thumbnail


def test_generate_thumbnail_from_image(tmp_path):
    source = tmp_path / "test.png"
    img = Image.new("RGB", (1280, 720), color=(255, 0, 0))
    img.save(source)
    thumb_dir = tmp_path / "thumbs"
    thumb_dir.mkdir()

    result = generate_thumbnail(source, "image", thumb_dir)

    assert result.exists()
    assert result.suffix == ".jpg"
    assert result.parent == thumb_dir
    thumb = Image.open(result)
    assert thumb.width <= 256
    assert thumb.height <= 256
