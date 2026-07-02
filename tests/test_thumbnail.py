from pathlib import Path
from unittest.mock import MagicMock

from PIL import Image

import origenerator.thumbnail as thumbnail
from origenerator.thumbnail import generate_animated_thumbnail, generate_thumbnail


def test_generate_thumbnail_from_image(tmp_path):
    source = tmp_path / "test.png"
    img = Image.new("RGB", (1280, 720), color=(255, 0, 0))
    img.save(source)
    thumb_dir = tmp_path / "thumbs"
    thumb_dir.mkdir()

    result = generate_thumbnail(source, "image", thumb_dir, name="abc123")

    assert result.exists()
    assert result.suffix == ".jpg"
    assert result.parent == thumb_dir
    thumb = Image.open(result)
    assert thumb.width <= 256
    assert thumb.height <= 256


def test_thumbnail_named_by_caller_not_by_source_stem(tmp_path):
    """The thumbnail filename comes from the caller's unique name, not the source.

    Two distinct outputs that happen to share a filename stem — ComfyUI's default
    ``ComfyUI_00001_.png`` saved beside ``video/ComfyUI_00001_.mp4`` — must land on
    separate thumbnail files. Keying the thumbnail by ``source.stem`` collapsed
    both onto one ``ComfyUI_00001_.jpg``, so the second import overwrote the
    first and a gallery thumbnail showed the wrong item's frame.
    """
    a = tmp_path / "ComfyUI_00001_.png"
    Image.new("RGB", (512, 768), (255, 0, 0)).save(a)
    sub = tmp_path / "video"
    sub.mkdir()
    b = sub / "ComfyUI_00001_.png"  # same stem, different folder
    Image.new("RGB", (1280, 720), (0, 255, 0)).save(b)
    thumb_dir = tmp_path / "thumbs"

    thumb_a = generate_thumbnail(a, "image", thumb_dir, name="row-a")
    thumb_b = generate_thumbnail(b, "image", thumb_dir, name="row-b")

    assert thumb_a != thumb_b
    assert thumb_a.exists() and thumb_b.exists()
    # Each thumbnail keeps its own source's proportions — no overwrite.
    assert Image.open(thumb_a).size[0] < Image.open(thumb_a).size[1]   # portrait
    assert Image.open(thumb_b).size[0] > Image.open(thumb_b).size[1]   # landscape


def test_animated_thumbnail_writes_a_looping_multiframe_webp(tmp_path, monkeypatch):
    frames = [Image.new("RGB", (64, 48), c) for c in ((255, 0, 0), (0, 255, 0), (0, 0, 255))]
    monkeypatch.setattr(thumbnail, "_sample_video_frames", lambda path, count, size: frames)

    result = generate_animated_thumbnail(tmp_path / "v.mp4", tmp_path / "thumbs", name="vid1")

    assert result.exists() and result.suffix == ".webp"
    anim = Image.open(result)
    assert getattr(anim, "n_frames", 1) == 3  # every sampled frame is in the loop


def test_animated_thumbnail_is_cached_and_not_regenerated(tmp_path, monkeypatch):
    thumb_dir = tmp_path / "thumbs"
    thumb_dir.mkdir()
    (thumb_dir / "vid1_anim.webp").write_bytes(b"cached")
    sampler = MagicMock()
    monkeypatch.setattr(thumbnail, "_sample_video_frames", sampler)

    result = generate_animated_thumbnail(tmp_path / "v.mp4", thumb_dir, name="vid1")

    assert result == thumb_dir / "vid1_anim.webp"
    sampler.assert_not_called()  # reused the cache, didn't re-read the video


def test_animated_thumbnail_is_none_when_no_frames_read(tmp_path, monkeypatch):
    monkeypatch.setattr(thumbnail, "_sample_video_frames", lambda path, count, size: [])
    assert generate_animated_thumbnail(tmp_path / "v.mp4", tmp_path / "thumbs", name="v") is None
