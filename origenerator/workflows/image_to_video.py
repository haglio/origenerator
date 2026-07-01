import math
from pathlib import Path

from PIL import Image

from origenerator.workflows.base import WorkflowTemplate


def fit_dimensions(
    image_w: int,
    image_h: int,
    target_pixels: int,
    *,
    multiple: int = 16,
    min_dim: int = 64,
    max_dim: int = 2048,
) -> tuple[int, int]:
    """Output dimensions matching an image's aspect ratio at a pixel budget.

    Scales the ``image_w`` × ``image_h`` aspect ratio to cover roughly
    ``target_pixels`` total pixels, then snaps each side to a multiple of
    ``multiple`` (WAN's latent stride) and clamps it to ``[min_dim, max_dim]``.
    """
    aspect = image_w / image_h
    w = math.sqrt(target_pixels * aspect)
    h = math.sqrt(target_pixels / aspect)
    return _snap(w, multiple, min_dim, max_dim), _snap(h, multiple, min_dim, max_dim)


def _snap(value: float, multiple: int, lo: int, hi: int) -> int:
    snapped = round(value / multiple) * multiple
    return int(max(lo, min(hi, snapped)))


class ImageToVideoWorkflow(WorkflowTemplate):
    """A workflow whose output size is derived from its input image.

    The WAN video nodes take an explicit width/height, so rather than hardcode
    one resolution these workflows reshape the output to the input image's
    aspect ratio, kept near ``native_size``'s pixel budget so VRAM and runtime
    stay put. Concrete subclasses set ``native_size`` (the model's native
    width × height) and supply the graph in :meth:`build_api_payload`.
    """

    # (width, height): the model's native size — both the pixel budget the
    # derived size targets and the fallback when the image can't be measured.
    native_size: tuple[int, int]

    def finalize_params(self, params: dict, input_dir: Path) -> dict:
        params = dict(params)
        params["width"], params["height"] = self._output_size(
            input_dir / params.get("input_image", "")
        )
        return params

    def _output_size(self, image_path: Path) -> tuple[int, int]:
        native_w, native_h = self.native_size
        try:
            with Image.open(image_path) as image:
                image_w, image_h = image.size
        except (OSError, ValueError):
            return native_w, native_h
        if image_w <= 0 or image_h <= 0:
            return native_w, native_h
        return fit_dimensions(image_w, image_h, native_w * native_h)
