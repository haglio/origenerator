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
