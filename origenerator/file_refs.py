"""How a generation names the files it made, and how this app keys one file.

Every place a file changes hands here is a *reference*, not a path: ComfyUI
records an output as ``{"filename", "subfolder", "type"}``, a ``LoadImage``
input names one as ``"subfolder/name.png [output]"``, and a row's stored
params carry that same annotated string. Three shapes for one file — and until
they were parsed in one place, each surface parsed them its own way and drifted:
one stripped the annotation and another didn't, one lowercased and another
compared as spelled.

So this module is the one reading of a reference the rest of the app shares:

* :func:`split_annotation` — a ``LoadImage`` value into the file it names and
  the ``[output]``-style tag ComfyUI hangs on it (``""`` when unannotated).
* :func:`reference_basename` — the bare file name a reference or path ends in,
  whichever separator wrote it.
* :func:`frame_name` — the *comparison key* for a file: its basename, lowercased,
  annotation gone. A stored output filename, a start-frame reference and a
  re-roll's annotated output all agree under it. Only a key, never a location.
* :func:`reference_path` — where on disk a ``LoadImage`` value points, the way
  ComfyUI's own LoadImage routes it: ``[output]`` under the output dir,
  ``[input]`` (or no tag) under the input dir, an absolute path as itself.

Kept free of every other module of this app, so the gallery's row logic and the
workflow templates can both read from it without one importing the other.
"""

from pathlib import Path

# ComfyUI's LoadImage annotates a non-input source as "name [output|input|temp]".
TYPE_ANNOTATIONS = frozenset({"[output]", "[input]", "[temp]"})
OUTPUT_TAG = "[output]"
INPUT_TAG = "[input]"
TEMP_TAG = "[temp]"


def split_annotation(image_ref: str | None) -> tuple[str, str]:
    """``(file, tag)`` for a ``LoadImage`` value — the tag ``""`` when there is
    none, so ``"frame.png"`` and ``"frame.png [input]"`` both name ``frame.png``."""
    ref = (image_ref or "").strip()
    stem, _, tag = ref.rpartition(" ")
    if stem and tag in TYPE_ANNOTATIONS:
        return stem, tag
    return ref, ""


def unannotated(image_ref: str | None) -> str:
    """A ``LoadImage`` value with any trailing type tag taken off."""
    return split_annotation(image_ref)[0]


def reference_basename(path: str | None) -> str:
    """The final segment of a path or reference, tolerant of either separator."""
    return (path or "").replace("\\", "/").rsplit("/", 1)[-1]


def frame_name(image_ref: str | None) -> str:
    """The comparison key for a file: its basename, lowercased, annotation
    stripped — so a stored output filename, an annotated re-roll output and a
    ``LoadImage`` reference all match by the plain file they name.

    A key and nothing more. Two files in different subfolders can share one
    (ComfyUI's counters are per prefix, and a prefix names a subfolder), which
    is why a *run* is tied to the row it is of by that row's id wherever the
    app gets to choose (see :func:`origenerator.gallery.enhance.enhance_target_id`)
    and only falls back to this name for a reference that carries nothing else.
    """
    return reference_basename(unannotated(image_ref)).lower()


def reference_path(
    image_ref: str | None, *, output_dir: Path, input_dir: Path, temp_dir: Path | None = None,
) -> Path | None:
    """The on-disk file a ``LoadImage`` value names, or ``None`` when it's empty,
    absent, or not there.

    ``"name [output]"`` lives under ``output_dir``, ``"[temp]"`` under
    ``temp_dir`` (nowhere, for a caller with none), and ``"[input]"`` (or an
    unannotated name) under ``input_dir`` — matching how ComfyUI's LoadImage
    routes the reference. An absolute path is taken as-is.
    """
    file, tag = split_annotation(image_ref)
    if not file:
        return None
    if tag == OUTPUT_TAG:
        path = output_dir / file
    elif tag == TEMP_TAG:
        if temp_dir is None:
            return None
        path = temp_dir / file
    elif tag == INPUT_TAG:
        path = input_dir / file
    else:
        path = Path(file)
        if not path.is_absolute():
            path = input_dir / file
    return path if path.is_file() else None
