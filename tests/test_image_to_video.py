from PIL import Image

from origenerator.workflows.image_to_video import (
    ImageToVideoWorkflow,
    fit_dimensions,
)


class _StubI2V(ImageToVideoWorkflow):
    """A minimal concrete image-to-video workflow for testing the base."""

    native_size = (832, 480)

    def default_params(self) -> dict:
        return {"input_image": ""}

    def param_definitions(self) -> list:
        return []

    def build_api_payload(self, params: dict) -> dict:
        return {}


def _write_image(path, size):
    Image.new("RGB", size, (0, 0, 0)).save(path)


def test_finalize_params_sizes_output_to_input_image(tmp_path):
    _write_image(tmp_path / "in.png", (1920, 1080))
    params = {"input_image": "in.png", "positive_prompt": "hi"}
    out = _StubI2V().finalize_params(params, tmp_path)

    assert (out["width"], out["height"]) == fit_dimensions(1920, 1080, 832 * 480)
    assert out["positive_prompt"] == "hi"       # other params carry through
    assert "width" not in params                # the original dict is untouched


def test_finalize_params_falls_back_to_native_size_when_image_unreadable(tmp_path):
    out = _StubI2V().finalize_params({"input_image": "missing.png"}, tmp_path)
    assert (out["width"], out["height"]) == (832, 480)


def test_fit_dimensions_preserves_aspect_and_budget_for_landscape():
    # A 16:9 image fit to a 1024x576 pixel budget lands exactly on 1024x576.
    assert fit_dimensions(1920, 1080, 1024 * 576) == (1024, 576)


def test_fit_dimensions_square_image_gives_square_output():
    assert fit_dimensions(500, 500, 512 * 512) == (512, 512)


def test_fit_dimensions_always_snaps_to_multiples_of_16():
    # An odd, non-clean aspect still yields two /16 sides near the budget.
    w, h = fit_dimensions(1000, 663, 832 * 480)
    assert w % 16 == 0 and h % 16 == 0


def test_fit_dimensions_keeps_portrait_orientation_and_budget():
    w, h = fit_dimensions(1080, 1920, 832 * 480)
    assert h > w  # a tall image stays tall
    assert w % 16 == 0 and h % 16 == 0
    assert abs(w * h - 832 * 480) / (832 * 480) < 0.1  # within 10% of the budget


def test_fit_dimensions_clamps_extreme_aspect_to_bounds():
    # A 100:1 sliver can't hold its ratio inside the bounds, so it pins to them.
    assert fit_dimensions(10000, 100, 832 * 480) == (2048, 64)
