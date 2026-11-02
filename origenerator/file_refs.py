from __future__ import annotations

from pathlib import Path

from origenerator.output_places import OutputPlaces

# ComfyUI's LoadImage annotates a non-input source as "name [output|input|temp]".
TYPE_ANNOTATIONS = frozenset({"[output]", "[input]", "[temp]"})
OUTPUT_TAG = "[output]"
INPUT_TAG = "[input]"
TEMP_TAG = "[temp]"


def split_annotation(image_ref: str | None) -> tuple[str, str]:
    ref = (image_ref or "").strip()
    stem, _, tag = ref.rpartition(" ")
    if stem and tag in TYPE_ANNOTATIONS:
        return stem, tag
    return ref, ""


def unannotated(image_ref: str | None) -> str:
    return split_annotation(image_ref)[0]


def reference_basename(path: str | None) -> str:
    return (path or "").replace("\\", "/").rsplit("/", 1)[-1]


def frame_name(image_ref: str | None) -> str:
    return reference_basename(unannotated(image_ref)).lower()


def reference_path(
    image_ref: str | None, *, places: OutputPlaces, input_dir: Path, temp_dir: Path | None = None,
) -> Path | None:
    path = reference_place(image_ref, places=places, input_dir=input_dir, temp_dir=temp_dir)
    return path if path is not None and path.is_file() else None


def reference_place(
    image_ref: str | None, *, places: OutputPlaces, input_dir: Path, temp_dir: Path | None = None,
) -> Path | None:
    file, tag = split_annotation(image_ref)
    if not file:
        return None
    if tag == OUTPUT_TAG:
        return places.file(file)
    if tag == TEMP_TAG:
        return temp_dir / file if temp_dir is not None else None
    if tag == INPUT_TAG:
        return input_dir / file
    path = Path(file)
    return path if path.is_absolute() else input_dir / file
