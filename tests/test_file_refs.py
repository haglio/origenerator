"""One reading of a file reference for the whole app: the file a ``LoadImage``
value names, the key two spellings of one file agree under, and where on disk
the reference points."""

from pathlib import Path

from origenerator.file_refs import (
    frame_name,
    reference_basename,
    reference_path,
    split_annotation,
    unannotated,
)


def test_split_annotation_takes_the_type_tag_off_and_nothing_else():
    assert split_annotation("image/gen_00001_.png [output]") == ("image/gen_00001_.png", "[output]")
    assert split_annotation("frame.png [input]") == ("frame.png", "[input]")
    assert split_annotation("frame.png") == ("frame.png", "")
    assert split_annotation("a name with spaces.png") == ("a name with spaces.png", "")
    assert split_annotation("") == ("", "")
    assert split_annotation(None) == ("", "")
    assert unannotated("x.png [temp]") == "x.png"


def test_frame_name_is_the_key_a_stored_file_and_a_reference_share():
    # A row records {"filename": "gen_00001_.png", "subfolder": "image"}; an i2v
    # or an enhance built on it records "image/gen_00001_.png [output]"; a
    # re-roll's params may carry either. All three name one file.
    assert frame_name("image/gen_00001_.png [output]") == "gen_00001_.png"
    assert frame_name("gen_00001_.png") == "gen_00001_.png"
    assert frame_name("C:\\comfy\\output\\image\\GEN_00001_.PNG") == "gen_00001_.png"
    assert frame_name("") == ""
    assert frame_name(None) == ""


def test_reference_basename_tolerates_either_separator():
    assert reference_basename("a/b/c.png") == "c.png"
    assert reference_basename("a\\b\\c.png") == "c.png"
    assert reference_basename("c.png") == "c.png"
    assert reference_basename(None) == ""


def test_reference_path_routes_the_way_comfyuis_loadimage_does(tmp_path):
    out_dir, in_dir = tmp_path / "output", tmp_path / "input"
    (out_dir / "image").mkdir(parents=True)
    in_dir.mkdir()
    (out_dir / "image" / "gen.png").write_bytes(b"x")
    (in_dir / "frame.png").write_bytes(b"x")
    resolve = lambda ref: reference_path(ref, output_dir=out_dir, input_dir=in_dir)

    assert resolve("image/gen.png [output]") == out_dir / "image" / "gen.png"
    assert resolve("frame.png [input]") == in_dir / "frame.png"
    assert resolve("frame.png") == in_dir / "frame.png"       # unannotated: the input dir
    assert resolve("image/gen.png") is None                    # not in the input dir
    assert resolve(str(in_dir / "frame.png")) == in_dir / "frame.png"  # absolute, as-is
    assert resolve("missing.png [output]") is None
    assert resolve("") is None and resolve(None) is None
    assert isinstance(resolve("frame.png"), Path)
