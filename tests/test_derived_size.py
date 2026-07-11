"""The app-side twin of the i2v in-graph size derivation."""

import origenerator.workflows.derived_size as ds
from origenerator.workflows.derived_size import (
    measure_derived_size, resolve_input_image_path, scale_to_total_pixels,
)


def _write_image(path, size):
    from PIL import Image

    Image.new("RGB", size, (128, 128, 128)).save(path)


def test_scale_to_total_pixels_matches_comfyui_rounding():
    # Replicates ComfyUI's ImageScaleToTotalPixels exactly — round(dim *
    # sqrt(0.4MP / area) / 16) * 16 — so the size it picks for an image equals
    # what the in-graph WAN 2.2 workflows produce for it. Values computed straight
    # from the formula (0.4 MP, /16 stride).
    assert scale_to_total_pixels(1920, 1080) == (864, 480)
    assert scale_to_total_pixels(1080, 1920) == (480, 864)
    assert scale_to_total_pixels(864, 1536) == (480, 864)
    assert scale_to_total_pixels(1024, 1024) == (640, 640)
    assert scale_to_total_pixels(768, 1344) == (496, 864)
    # A degenerate aspect never yields a zero dimension (which would crash the
    # track node); the side that would round to 0 floors at the /16 stride.
    assert scale_to_total_pixels(10000, 1) == (64768, 16)


def test_resolve_input_image_routes_by_annotation(tmp_path, monkeypatch):
    # A LoadImage value resolves to a real file: a plain name (or "[input]") under
    # the input dir, a "name [output]" under the output dir — the same routing
    # ComfyUI's LoadImage does. Anything unresolvable is None.
    in_dir, out_dir = tmp_path / "input", tmp_path / "output"
    in_dir.mkdir()
    out_dir.mkdir()
    monkeypatch.setattr(ds, "COMFYUI_INPUT_DIR", in_dir)
    monkeypatch.setattr(ds, "COMFYUI_OUTPUT_DIR", out_dir)
    (in_dir / "frame.png").write_bytes(b"x")
    (out_dir / "gen.png").write_bytes(b"x")

    assert resolve_input_image_path("frame.png") == in_dir / "frame.png"
    assert resolve_input_image_path("frame.png [input]") == in_dir / "frame.png"
    assert resolve_input_image_path("gen.png [output]") == out_dir / "gen.png"
    assert resolve_input_image_path("gen.png") is None       # not in the input dir
    assert resolve_input_image_path("missing.png") is None
    assert resolve_input_image_path("") is None
    assert resolve_input_image_path(None) is None


def test_resolve_input_image_takes_an_absolute_path_as_is(tmp_path, monkeypatch):
    # Browse stores a full path verbatim (ComfyUI's LoadImage takes one outside
    # its input folder unchanged), so the resolver must honor an absolute path
    # rather than re-root it under the input dir.
    monkeypatch.setattr(ds, "COMFYUI_INPUT_DIR", tmp_path / "input")
    img = tmp_path / "elsewhere" / "cat.png"
    img.parent.mkdir()
    img.write_bytes(b"x")
    assert resolve_input_image_path(str(img)) == img
    assert resolve_input_image_path(str(tmp_path / "elsewhere" / "gone.png")) is None


def test_measure_derived_size_scales_the_measured_image(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "COMFYUI_INPUT_DIR", tmp_path)
    _write_image(tmp_path / "square.png", (1024, 1024))
    assert measure_derived_size("square.png") == scale_to_total_pixels(1024, 1024)
    assert measure_derived_size("square.png") == (640, 640)


def test_measure_derived_size_is_none_when_unmeasurable(tmp_path, monkeypatch):
    # A missing, unset, or unreadable image yields None so a caller can fall back
    # rather than crash.
    monkeypatch.setattr(ds, "COMFYUI_INPUT_DIR", tmp_path)
    (tmp_path / "notanimage.png").write_bytes(b"not really a png")
    assert measure_derived_size("") is None
    assert measure_derived_size("missing.png") is None
    assert measure_derived_size("notanimage.png") is None
