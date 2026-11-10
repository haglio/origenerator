from __future__ import annotations

from pathlib import Path

from origenerator.file_refs import reference_path
from origenerator.output_places import OutputPlaces


def test_reference_path_routes_the_way_comfyuis_loadimage_does(tmp_path):
    out_dir, in_dir = tmp_path / "output", tmp_path / "input"
    (out_dir / "image").mkdir(parents=True)
    in_dir.mkdir()
    (out_dir / "image" / "gen.png").write_bytes(b"x")
    (in_dir / "frame.png").write_bytes(b"x")
    def resolve(ref):
        return reference_path(ref, places=OutputPlaces.in_one_folder(out_dir), input_dir=in_dir)

    assert resolve("image/gen.png [output]") == out_dir / "image" / "gen.png"
    assert resolve("frame.png [input]") == in_dir / "frame.png"
    assert resolve("frame.png") == in_dir / "frame.png"
    assert resolve("image/gen.png") is None
    assert resolve(str(in_dir / "frame.png")) == in_dir / "frame.png"
    assert resolve("missing.png [output]") is None
    assert resolve("") is None
    assert resolve(None) is None
    assert isinstance(resolve("frame.png"), Path)


def test_reference_path_routes_a_temp_reference_under_the_temp_dir(tmp_path):
    out_dir, in_dir, temp_dir = tmp_path / "output", tmp_path / "input", tmp_path / "temp"
    for d in (out_dir, in_dir, temp_dir):
        d.mkdir()
    (temp_dir / "scratch.png").write_bytes(b"x")

    assert reference_path("scratch.png [temp]", places=OutputPlaces.in_one_folder(out_dir), input_dir=in_dir,
                          temp_dir=temp_dir) == temp_dir / "scratch.png"
    assert reference_path("scratch.png [temp]", places=OutputPlaces.in_one_folder(out_dir), input_dir=in_dir) is None
