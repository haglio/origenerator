from __future__ import annotations

from pathlib import Path

from app_support.comfy_file_refs import INPUT_TAG, OUTPUT_TAG, TEMP_TAG, split_annotation

from origenerator.output_places import OutputPlaces


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
