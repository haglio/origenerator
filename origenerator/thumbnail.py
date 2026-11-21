from __future__ import annotations

import logging
from collections.abc import Callable
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageStat
from shared_ui.palette import BG_BUTTON

from origenerator.media import MediaType, media_type_from_filename, video_header

logger = logging.getLogger(__name__)

_THUMB_MAX = 256


def generate_thumbnail(
    source_path: Path, output_type: MediaType, thumb_dir: Path, *, name: str
) -> Path:
    if output_type == MediaType.VIDEO:
        img = (next(iter(_sample_video_frames(source_path, 1, _THUMB_MAX)), None)
               or first_frame_of(source_path)
               or Image.new("RGB", (_THUMB_MAX, _THUMB_MAX), BG_BUTTON))
    else:
        img = Image.open(source_path)
    return _saved_thumbnail(img, thumb_dir, name)


def frame_thumbnail(frame: bytes, thumb_dir: Path, *, name: str) -> Path | None:
    try:
        img = Image.open(BytesIO(frame))
        img.load()
    except (OSError, ValueError):
        return None
    return _saved_thumbnail(img, thumb_dir, name)


def _saved_thumbnail(img: Image.Image, thumb_dir: Path, name: str) -> Path:
    thumb_dir.mkdir(parents=True, exist_ok=True)
    dest = still_thumbnail_path(thumb_dir, name)
    img.thumbnail((_THUMB_MAX, _THUMB_MAX))
    img.convert("RGB").save(dest, "JPEG", quality=85)
    return dest


def still_thumbnail_path(thumb_dir: Path, name: str) -> Path:
    return thumb_dir / f"{name}.jpg"


def first_frame_of(path: Path) -> Image.Image | None:
    import cv2  # noqa: PLC0415 (heavy; only a video needs it)
    cap = cv2.VideoCapture(str(path))
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return None
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return Image.fromarray(frame_rgb)


FRAME_MS = 140
LONG_VIDEO_S = 60
_TIMES_AS_LONG_ON_A_LONG_VIDEO = 5


def video_duration_seconds(path: Path) -> float | None:
    header = video_header(path)
    return header.seconds if header else None


def frame_ms_for(seconds: float | None) -> int:
    return FRAME_MS * (_TIMES_AS_LONG_ON_A_LONG_VIDEO if seconds and seconds > LONG_VIDEO_S else 1)


def frame_ms_of(animated_thumbnail: Path) -> int | None:
    try:
        with Image.open(animated_thumbnail) as made:
            if getattr(made, "n_frames", 1) < 2:
                return None
            return min(_held_ms(made, frame) for frame in range(made.n_frames))
    except OSError:
        return None


def _held_ms(made: Image.Image, frame: int) -> int:
    made.seek(frame)
    made.load()
    return made.info.get("duration", 0)


def at_its_videos_pace(animated_thumbnail: Path, video: Path) -> bool:
    held = frame_ms_of(animated_thumbnail)
    return held is None or held == frame_ms_for(video_duration_seconds(video))


def generate_animated_thumbnail(
    source_path: Path, thumb_dir: Path, *, name: str, frames: int = 8, again: bool = False
) -> Path | None:
    dest = animated_thumbnail_path(thumb_dir, name)
    if dest.exists() and not again:
        return dest
    being_written = dest.with_name(f"{name}.partial.anim")
    try:
        thumb_dir.mkdir(parents=True, exist_ok=True)
        images = _sample_video_frames(source_path, frames, _THUMB_MAX)
        if not images:
            return None
        images[0].save(
            being_written, format="WEBP", save_all=True, append_images=images[1:],
            duration=frame_ms_for(video_duration_seconds(source_path)), loop=0,
        )
        being_written.replace(dest)
    except Exception as e:
        logger.warning("Animated thumbnail failed for %s: %s", name, e)
        return None
    return dest


def animate_if_video(path: Path, thumb_dir: Path, *, name: str) -> None:
    if media_type_from_filename(path.name) == MediaType.VIDEO:
        generate_animated_thumbnail(path, thumb_dir, name=name)


def animated_thumbnail_path(thumb_dir: Path, name: str) -> Path:
    return thumb_dir / f"{name}_anim.webp"


_LOOKS_IN_A_STRETCH = 4
_FRAMES_READ_RATHER_THAN_SOUGHT = 200
_BLACK_AT_MOST = 10


def is_black(image: Image.Image) -> bool:
    return ImageStat.Stat(image.convert("L")).mean[0] <= _BLACK_AT_MOST


def shows_black_among_other_frames(animated_thumbnail: Path) -> bool:
    return _blackness_of_its_frames(animated_thumbnail) == {True, False}


def is_black_where_its_video_is_not(still: Path, animated_thumbnail: Path) -> bool:
    return (_blackness_of_its_frames(still) == {True}
            and False in _blackness_of_its_frames(animated_thumbnail))


def _blackness_of_its_frames(thumbnail: Path) -> set[bool]:
    try:
        with Image.open(thumbnail) as made:
            return {is_black(_frame(made, at)) for at in range(getattr(made, "n_frames", 1))}
    except OSError:
        return set()


def _frame(made: Image.Image, at: int) -> Image.Image:
    made.seek(at)
    return made.convert("RGB")


def frames_showing_something(frame_at: Callable[[int], Image.Image | None], total: int,
                             count: int) -> list[Image.Image]:
    stretch = max(1, total // count)
    looked_at = [_looks_along(frame_at, min(at * stretch, total - 1), stretch, total)
                 for at in range(count)]
    showing = [next((frame for frame in looks if not is_black(frame)), None) for looks in looked_at]
    if any(frame is not None for frame in showing):
        return [frame for frame in showing if frame is not None]
    return [looks[0] for looks in looked_at if looks]


def _looks_along(frame_at, start: int, stretch: int, total: int) -> list[Image.Image]:
    looks = []
    for at in range(start, min(start + stretch, total), max(1, stretch // _LOOKS_IN_A_STRETCH)):
        frame = frame_at(at)
        if frame is None:
            break
        looks.append(frame)
        if not is_black(frame):
            break
    return looks


def _sample_video_frames(path: Path, count: int, size: int) -> list[Image.Image]:
    import cv2  # noqa: PLC0415 (heavy; only a video needs it)
    cap = cv2.VideoCapture(str(path))
    standing_at = 0

    def frame_at(index: int) -> Image.Image | None:
        nonlocal standing_at
        if index - standing_at > _FRAMES_READ_RATHER_THAN_SOUGHT:
            cap.set(cv2.CAP_PROP_POS_FRAMES, index)
            standing_at = index
        for _ in range(index - standing_at):
            cap.grab()
        read, frame = cap.read()
        standing_at = index + 1
        return _shrunk(cv2, frame, size) if read else None

    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        return frames_showing_something(frame_at, total, count) if total > 0 else []
    finally:
        cap.release()


def _shrunk(cv2, frame, size: int) -> Image.Image:
    height, width = frame.shape[:2]
    scale = size / max(height, width)
    if scale < 1:
        frame = cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))),
                           interpolation=cv2.INTER_AREA)
    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    image.thumbnail((size, size))
    return image.convert("RGB")
