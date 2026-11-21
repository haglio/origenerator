from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock

from PIL import Image

from origenerator import thumbnail
from origenerator.thumbnail import (
    FRAME_MS,
    LONG_VIDEO_S,
    frame_ms_of,
    frame_thumbnail,
    frames_showing_something,
    generate_animated_thumbnail,
    generate_thumbnail,
    is_black,
    shows_black_among_other_frames,
)
from tests.media_files import write_mp4, write_mp4_of_shades


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
    a = tmp_path / "ComfyUI_00001_.png"
    Image.new("RGB", (512, 768), (255, 0, 0)).save(a)
    sub = tmp_path / "video"
    sub.mkdir()
    b = sub / "ComfyUI_00001_.png"
    Image.new("RGB", (1280, 720), (0, 255, 0)).save(b)
    thumb_dir = tmp_path / "thumbs"

    thumb_a = generate_thumbnail(a, "image", thumb_dir, name="row-a")
    thumb_b = generate_thumbnail(b, "image", thumb_dir, name="row-b")

    assert thumb_a != thumb_b
    assert thumb_a.exists()
    assert thumb_b.exists()
    assert Image.open(thumb_a).size[0] < Image.open(thumb_a).size[1]
    assert Image.open(thumb_b).size[0] > Image.open(thumb_b).size[1]


def test_animated_thumbnail_writes_a_looping_multiframe_webp(tmp_path, monkeypatch):
    frames = [Image.new("RGB", (64, 48), c) for c in ((255, 0, 0), (0, 255, 0), (0, 0, 255))]
    monkeypatch.setattr(thumbnail, "_sample_video_frames", lambda path, count, size: frames)

    result = generate_animated_thumbnail(tmp_path / "v.mp4", tmp_path / "thumbs", name="vid1")

    assert result.exists()
    assert result.suffix == ".webp"
    anim = Image.open(result)
    assert getattr(anim, "n_frames", 1) == 3


def _held_for(tmp_path, monkeypatch, *, seconds: float) -> int:
    frames = [Image.new("RGB", (64, 48), color) for color in ((255, 0, 0), (0, 255, 0))]
    monkeypatch.setattr(thumbnail, "_sample_video_frames", lambda path, count, size: frames)
    monkeypatch.setattr(thumbnail, "video_duration_seconds", lambda path: seconds)
    made = generate_animated_thumbnail(tmp_path / "v.mp4", tmp_path / f"thumbs {seconds}", name="v")
    return frame_ms_of(made)


def test_a_long_videos_thumbnail_holds_each_frame_five_times_as_long(tmp_path, monkeypatch):
    assert (_held_for(tmp_path, monkeypatch, seconds=LONG_VIDEO_S - 1),
            _held_for(tmp_path, monkeypatch, seconds=LONG_VIDEO_S + 1)) == (FRAME_MS, 5 * FRAME_MS)


def test_animated_thumbnail_is_cached_and_not_regenerated(tmp_path, monkeypatch):
    thumb_dir = tmp_path / "thumbs"
    thumb_dir.mkdir()
    (thumb_dir / "vid1_anim.webp").write_bytes(b"cached")
    sampler = MagicMock()
    monkeypatch.setattr(thumbnail, "_sample_video_frames", sampler)

    result = generate_animated_thumbnail(tmp_path / "v.mp4", thumb_dir, name="vid1")

    assert result == thumb_dir / "vid1_anim.webp"
    sampler.assert_not_called()


def test_animated_thumbnail_is_none_when_no_frames_read(tmp_path, monkeypatch):
    monkeypatch.setattr(thumbnail, "_sample_video_frames", lambda path, count, size: [])
    assert generate_animated_thumbnail(tmp_path / "v.mp4", tmp_path / "thumbs", name="v") is None


def test_a_streamed_frame_is_kept_as_a_thumbnail(tmp_path):
    frame = BytesIO()
    Image.new("RGB", (600, 300), "red").save(frame, "PNG")

    kept = frame_thumbnail(frame.getvalue(), tmp_path, name="run1_canceled")

    with Image.open(kept) as saved:
        assert max(saved.size) <= 256
        assert saved.size[0] > saved.size[1]


def test_a_frame_that_will_not_decode_keeps_no_thumbnail(tmp_path):
    assert frame_thumbnail(b"not an image", tmp_path, name="run1_canceled") is None
    assert list(tmp_path.iterdir()) == []


def test_an_animated_thumbnail_that_cannot_be_written_leaves_the_still_to_show(tmp_path):
    video = write_mp4(tmp_path / "scene_one.mp4")
    a_file_in_the_way = tmp_path / "thumbs"
    a_file_in_the_way.write_bytes(b"not a folder")

    assert generate_animated_thumbnail(video, a_file_in_the_way, name="v1") is None


def _shade(shade: int) -> Image.Image:
    return Image.new("RGB", (4, 4), (shade, shade, shade))


def _shades_chosen(shades: list[int], count: int) -> list[int]:
    chosen = frames_showing_something(lambda at: _shade(shades[at]), len(shades), count)
    return [frame.getpixel((0, 0))[0] for frame in chosen]


def test_a_black_frame_gives_way_to_the_next_one_of_its_stretch_that_shows_something():
    fades_in_and_out = [0, 0, 0, 103, 104, 105, 106, 107, 108, 109, 110, 111, 0, 0, 0, 0]

    assert _shades_chosen(fades_in_and_out, 4) == [103, 104, 108]


def test_a_video_that_is_black_throughout_keeps_its_black_frames():
    assert _shades_chosen([0] * 16, 4) == [0, 0, 0, 0]


def test_a_frame_that_shows_something_is_taken_where_it_always_was():
    assert _shades_chosen(list(range(100, 116)), 4) == [100, 104, 108, 112]


def test_a_video_that_fades_in_gets_thumbnails_with_no_black_frame(tmp_path):
    video = write_mp4_of_shades(tmp_path / "fades in.mp4", [0] * 8 + [200] * 24)

    animated = generate_animated_thumbnail(video, tmp_path / "thumbs", name="v")
    still = generate_thumbnail(video, "video", tmp_path / "thumbs", name="v")

    assert not shows_black_among_other_frames(animated)
    assert not is_black(Image.open(animated))
    assert not is_black(Image.open(still))


def test_a_thumbnail_showing_black_beside_other_frames_is_told_from_one_black_throughout(tmp_path):
    def saved(name: str, shades: list[int]):
        frames = [_shade(shade) for shade in shades]
        frames[0].save(tmp_path / name, format="WEBP", save_all=True, append_images=frames[1:],
                       duration=FRAME_MS, loop=0, lossless=True)
        return tmp_path / name

    assert [shows_black_among_other_frames(saved(f"{at}.webp", shades))
            for at, shades in enumerate(([0, 200], [0, 0], [200, 180]))] == [True, False, False]


class _SeekCounting:
    def __init__(self, capture, seeks: list):
        self._capture, self._seeks = capture, seeks

    def set(self, prop, value):
        self._seeks.append(value)
        return self._capture.set(prop, value)

    def __getattr__(self, name):
        return getattr(self._capture, name)


def _seeks_sampling(tmp_path, monkeypatch, shades: list[int], count: int) -> tuple[list, int]:
    import cv2  # noqa: PLC0415 (heavy; only the tests that open a real video need it)
    video = write_mp4_of_shades(tmp_path / "video one.mp4", shades)
    seeks, opened = [], cv2.VideoCapture
    monkeypatch.setattr(cv2, "VideoCapture", lambda path: _SeekCounting(opened(path), seeks))
    return seeks, len(thumbnail._sample_video_frames(video, count, 8))


def test_a_short_videos_frames_are_read_in_one_pass_without_seeking(tmp_path, monkeypatch):
    assert _seeks_sampling(tmp_path, monkeypatch, list(range(100, 132)), 8) == ([], 8)


def test_frames_far_apart_are_reached_by_seeking_rather_than_reading_every_frame_between(
        tmp_path, monkeypatch):
    assert _seeks_sampling(tmp_path, monkeypatch, [150] * 600, 2) == ([300], 2)
