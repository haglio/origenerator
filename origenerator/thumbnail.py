from pathlib import Path

from PIL import Image

_THUMB_MAX = 256


def generate_thumbnail(
    source_path: Path, output_type: str, thumb_dir: Path, *, name: str
) -> Path:
    """Render a thumbnail for ``source_path`` into ``thumb_dir / f"{name}.jpg"``.

    ``name`` is the caller's unique key for this generation (its ``prompt_id``),
    not the source filename: two outputs that share a stem — ComfyUI's default
    ``ComfyUI_00001_.png`` beside ``video/ComfyUI_00001_.mp4`` — would otherwise
    collapse onto one thumbnail, leaving one row showing the other's frame.
    """
    thumb_dir.mkdir(parents=True, exist_ok=True)
    dest = thumb_dir / f"{name}.jpg"

    if output_type == "video":
        img = _first_frame_from_video(source_path)
    else:
        img = Image.open(source_path)

    img.thumbnail((_THUMB_MAX, _THUMB_MAX))
    img = img.convert("RGB")
    img.save(dest, "JPEG", quality=85)
    return dest


def _first_frame_from_video(path: Path) -> Image.Image:
    import cv2
    cap = cv2.VideoCapture(str(path))
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return Image.new("RGB", (_THUMB_MAX, _THUMB_MAX), (64, 64, 64))
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return Image.fromarray(frame_rgb)


def generate_animated_thumbnail(
    source_path: Path, thumb_dir: Path, *, name: str, frames: int = 8, duration_ms: int = 140
) -> Path | None:
    """Render a short looping WebP preview of a video into
    ``thumb_dir / f"{name}_anim.webp"`` — the moving preview the gallery shows for
    the videos an image was animated into.

    Cached: an existing file is returned untouched. ``None`` when no frames can be
    read (a missing or unreadable video), so the caller falls back to the static
    thumbnail. WebP + ``QMovie`` playback keeps many previews light and avoids a
    video player per tile.
    """
    thumb_dir.mkdir(parents=True, exist_ok=True)
    dest = thumb_dir / f"{name}_anim.webp"
    if dest.exists():
        return dest
    images = _sample_video_frames(source_path, frames, _THUMB_MAX)
    if not images:
        return None
    images[0].save(
        dest, format="WEBP", save_all=True, append_images=images[1:],
        duration=duration_ms, loop=0,
    )
    return dest


def _sample_video_frames(path: Path, count: int, size: int) -> list[Image.Image]:
    """Up to ``count`` frames evenly spaced across the video, each scaled to fit
    ``size`` — RGB PIL images, or empty when the video can't be read."""
    import cv2
    cap = cv2.VideoCapture(str(path))
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total <= 0:
            return []
        step = max(1, total // count)
        images = []
        for i in range(count):
            cap.set(cv2.CAP_PROP_POS_FRAMES, min(i * step, total - 1))
            ret, frame = cap.read()
            if not ret:
                break
            img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            img.thumbnail((size, size))
            images.append(img.convert("RGB"))
        return images
    finally:
        cap.release()
