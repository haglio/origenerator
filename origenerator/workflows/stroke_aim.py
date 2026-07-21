"""Auto-aim the ATI stroke at the anatomy in a start frame.

Manually telling the workflow where the anchor sits in every image doesn't
scale, so this module finds it: a detection pass over the start frame yields
the anchor's bounding box, and the box maps to the stroke's aim — the track
column through the box's center, a stroke span over the anchor's gripped
length, and the static anchor at its base. Results are FRACTIONS of the image
(0..1), so the caller converts them into whatever coordinate frame it authors
tracks in; this module knows nothing about reference frames or workflows.

The detector is deepghs's anime_censor_detection YOLO (ONNX, run directly via
onnxruntime — trained on drawn/rendered explicit content, which is what this
gallery generates; NudeNet's photo-trained detector whiffed on it). The model
is fetched once through the Hugging Face cache and runs on CPU in ~100ms.

Detection is best-effort by design: any failure (dependency missing, model
unavailable, nothing detected) returns ``None`` and the caller falls back to
its manual numbers — auto-aim must never be the reason a generation can't
build.
"""

import logging
from pathlib import Path

from origenerator.content import load_content

logger = logging.getLogger(__name__)

_MODEL_REPO = "deepghs/anime_censor_detection"
_MODEL_FILE = "censor_detect_v1.0_s/model.onnx"
# The aim model's class names are library vocabulary; they come from the
# content overlay rather than from source.
_MODEL_LABELS = tuple(load_content()["detector_labels"]["model_labels"])
_INFER_SIZE = 640
_IOU_LIMIT = 0.45

# The label whose box the stroke aims at.
_SHAFT_CLASSES = set(load_content()["detector_labels"]["anchor_classes"])
# The gallery's photoreal renders score low on the anime-trained detector even
# when the box is spot-on (measured ~0.28 on a frame-filling anchor the box
# nailed), so the bar sits low; a wrong aim is bounded by the manual override
# and costs one re-roll, while a missed aim forfeits the feature.
_MIN_SCORE = 0.22

# Where the stroke lands inside the detected box, as fractions of its height:
# the span starts just under the tip and ends above the base (the gripped
# length a hand travels), and the anchor pins the base itself. Calibrated
# against the hand-aimed proof-of-concept frame.
_SPAN_TOP = 0.18
_SPAN_BOTTOM = 0.72
_ANCHOR = 0.93

_detector = None


def aim_fractions_from_box(box, image_w: int, image_h: int) -> dict:
    """Map a detected anchor box ``(x, y, w, h)`` to the stroke's aim, each value
    a fraction of the image: the track column through the box center, the
    stroke span over the gripped length, the anchor at the base."""
    x, y, w, h = box
    cx = (x + w / 2) / image_w
    return {
        "stroke_x": cx,
        "stroke_top": (y + _SPAN_TOP * h) / image_h,
        "stroke_bottom": (y + _SPAN_BOTTOM * h) / image_h,
        "anchor_x": cx,
        "anchor_y": (y + _ANCHOR * h) / image_h,
    }


def detect_grip_aim(image_path: Path | None) -> dict | None:
    """The stroke aim for ``image_path``'s most confident detected anchor, as
    image fractions (see :func:`aim_fractions_from_box`), or ``None`` when
    there's no file, no usable detector, or no confident detection."""
    if image_path is None:
        return None
    try:
        from PIL import Image

        best = _best_anchor(_detect(str(image_path)))
        if best is None:
            logger.info("Auto-aim: no anchor detected in %s", image_path)
            return None
        with Image.open(image_path) as img:
            image_w, image_h = img.size
        return aim_fractions_from_box(best["box"], image_w, image_h)
    except Exception as e:
        logger.warning("Auto-aim detection failed for %s: %s", image_path, e)
        return None


def _best_anchor(detections) -> dict | None:
    return max(
        (d for d in detections
         if d.get("class") in _SHAFT_CLASSES and d.get("score", 0) >= _MIN_SCORE),
        key=lambda d: d["score"],
        default=None,
    )


def _detect(path: str) -> list[dict]:
    """Run the (lazily created, cached) censor detector over an image file,
    returning ``{"class", "score", "box": (x, y, w, h)}`` dicts in image
    pixels. Isolated so tests can monkeypatch detection without the model."""
    import numpy as np
    from PIL import Image

    session = _session()
    with Image.open(path) as img:
        rgb = img.convert("RGB")
        w, h = rgb.size
        scale = min(_INFER_SIZE / w, _INFER_SIZE / h)
        nw, nh = round(w * scale), round(h * scale)
        pad_x, pad_y = (_INFER_SIZE - nw) // 2, (_INFER_SIZE - nh) // 2
        canvas = Image.new("RGB", (_INFER_SIZE, _INFER_SIZE), (114, 114, 114))
        canvas.paste(rgb.resize((nw, nh)), (pad_x, pad_y))
    x = np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
    (out,) = session.run(None, {session.get_inputs()[0].name: x})
    return _decode_yolo(out[0], scale, pad_x, pad_y)


def _decode_yolo(out, scale: float, pad_x: int, pad_y: int) -> list[dict]:
    """YOLOv8 output ``(4 + n_classes, anchors)`` → scored, NMS-pruned boxes
    mapped back through the letterbox into original image pixels."""
    import numpy as np

    boxes_cxcywh = out[:4].T
    scores = out[4:].T
    class_idx = scores.argmax(axis=1)
    confidence = scores[np.arange(len(class_idx)), class_idx]
    keep = confidence >= _MIN_SCORE
    detections = []
    for (cx, cy, bw, bh), ci, score in zip(
        boxes_cxcywh[keep], class_idx[keep], confidence[keep]
    ):
        x = (cx - bw / 2 - pad_x) / scale
        y = (cy - bh / 2 - pad_y) / scale
        detections.append({
            "class": _MODEL_LABELS[ci],
            "score": float(score),
            "box": (x, y, bw / scale, bh / scale),
        })
    detections.sort(key=lambda d: d["score"], reverse=True)
    pruned = []
    for d in detections:
        if all(_iou(d["box"], p["box"]) < _IOU_LIMIT for p in pruned):
            pruned.append(d)
    return pruned


def _iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _session():
    """The lazily created, cached onnxruntime session for the detector, its
    weights fetched once through the Hugging Face cache."""
    global _detector
    if _detector is None:
        import onnxruntime
        from huggingface_hub import hf_hub_download

        model_path = hf_hub_download(_MODEL_REPO, _MODEL_FILE)
        _detector = onnxruntime.InferenceSession(
            model_path, providers=["CPUExecutionProvider"]
        )
    return _detector
