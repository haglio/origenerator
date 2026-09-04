"""Cut a clip down to the one stroke Genau plays it as.

Genau does not play a clip at its own speed -- it scrubs it against the device's
phase. Phase 0 parks the device at the bottom of its axis
(``genau.tcode.Osr2TcodeSender.take_over``, ``player_core.direct_control``) and
shows the clip's last frame; phase 0.5 has the device at the top and shows the
middle frame (``genau.refresh_logic.display_index_for_phase``). A loop's first
and last frames are one moment of that cycle, so every clip in Genau's folder is
steered as if it ran from one extreme of the stroke, through the other at its
midpoint, and back to the first -- which is exactly the shape Clipper cuts by
hand and calls ``base-tip-base``.

A generated loop does not have that shape. It holds however many strokes its
frame count and its cadence happened to fit, and Genau steers it as one anyway:
the device makes a single slow stroke while the pixels make four. So the Genau
lane sends a *cut* of the clip rather than the clip -- the span between two
consecutive bottoms of the clip's own funscript, one whole stroke, beginning on
the extreme Genau parks on.

The funscript is the only thing here that knows where those extremes are, and it
is the app's own record of the motion rather than a reading of the pixels: for
the track-conditioned workflow it is exact by construction (the pixel track and
the script are built from one set of reversals -- see
:meth:`~origenerator.workflows.wan21_ati_i2v.Wan21AtiI2vWorkflow.authored_actions`),
and for the rest it is the cadence the clip was scored to. A clip with no script,
or none holding a whole stroke, therefore has nothing to be cut to and is not
sent -- rather than being sent whole, which is the very thing this exists to stop.

The cut is a generation row of its own, so the gallery holds both: the whole
video and the one stroke taken out of it. It copies its source's params, which
lands it in the same settings folder, and names that source in ``trimmed_from``,
which is what the Generate tab's "Trimmed from" tile follows back.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app_support.subprocess_utils import hidden_subprocess_kwargs

from origenerator.funscript import (
    funscript_of,
    funscript_path_for,
    read_actions,
    video_duration_seconds,
    write_funscript,
)
from origenerator.thumbnail import generate_thumbnail

logger = logging.getLogger(__name__)

#: What a cut's ``source`` column says. Its own value rather than ``"generated"``
#: because no run made it -- it is a pair of scissors applied to a run's output --
#: and rows are read by source in several places that should not count it twice.
STROKE_TRIM_SOURCE = "stroke_trim"

#: Appended to the source clip's stem to name the cut.
_TRIM_SUFFIX = "_stroke"


class NoSingleStroke(Exception):
    """The clip holds no whole stroke to cut it down to.

    Raised rather than answered with ``None`` so that a caller has one path for
    "this send did not happen and here is the sentence saying why" -- the Genau
    button's dialog and the spoken send's log line both want that sentence, and
    a lane that cannot be given one stroke must not quietly be given all of them.
    """


def _extremes(actions: list[dict]) -> list[int]:
    """The indices in ``actions`` where the stroke turns around, ends included.

    A funscript is the stroke sampled, not only its reversals: an authored script
    carries a shaping point partway through each half-stroke and a measured one
    carries whatever a curve fit kept, so the extremes are the points where the
    direction of travel changes and nothing else. A run of equal positions is not
    a turn but a hold, and the turn is its far end. The first and last actions
    count as extremes of their own, so a script that opens partway up a rise
    still opens at the bottom of what it records.
    """
    positions = [a["pos"] for a in actions]
    if len(positions) < 2:
        return list(range(len(positions)))
    turns = [0]
    heading = 0
    for i in range(1, len(positions)):
        step = positions[i] - positions[i - 1]
        if step == 0:
            continue
        going = 1 if step > 0 else -1
        if heading and going != heading:
            turns.append(i - 1)
        heading = going
    if turns[-1] != len(positions) - 1:
        turns.append(len(positions) - 1)
    return turns


def single_stroke_span(actions: list[dict] | None) -> tuple[int, int] | None:
    """``(start_ms, end_ms)`` of one whole stroke in ``actions``, or ``None``.

    A whole stroke is a low extreme, the high extreme after it, and the low one
    after that: out to the far end of the travel and back to where it started.
    It begins on the LOW extreme because that is where Genau parks -- see the
    module docstring -- so a clip cut here starts on the frame Genau will hold
    the device at the bottom of its axis for.

    Of the strokes a clip holds, the one with the most travel wins. The authored
    stroke deliberately lands short of the extreme now and then (up to 18%, so
    the rhythm reads as a hand rather than a metronome), and a stroke that ends
    somewhere other than it began makes a loop that jumps; the fullest one is
    both the truest single stroke and the cleanest loop. Ties keep the earliest,
    which is the one a viewer would call the clip's first stroke.
    """
    if not actions:
        return None
    turns = _extremes(actions)
    best_travel, best_span = 0, None
    for low, high, back in zip(turns, turns[1:], turns[2:]):
        bottom, top, end = actions[low], actions[high], actions[back]
        if not (bottom["pos"] < top["pos"] > end["pos"]):
            continue
        start_ms, end_ms = int(bottom["at"]), int(end["at"])
        if end_ms <= start_ms:
            continue
        travel = top["pos"] - max(bottom["pos"], end["pos"])
        if travel > best_travel:
            best_travel, best_span = travel, (start_ms, end_ms)
    return best_span


def windowed_actions(actions: list[dict], start_ms: int, end_ms: int) -> list[dict]:
    """``actions`` re-based onto a cut running ``start_ms`` to ``end_ms``.

    The cut needs a script of its own -- it is a video in the gallery like any
    other, and the OSR2 drive reads one off whatever is on screen. Windowing the
    source's is exact and free, where re-deriving one would be a second opinion
    about the same motion. Both ends are kept: the span's own endpoints are
    actions, and a looping script ends where it began at exactly the duration.
    """
    return [{"at": a["at"] - start_ms, "pos": a["pos"]}
            for a in actions if start_ms <= a["at"] <= end_ms]


def _free_name(video_path: Path) -> Path:
    """A name beside ``video_path`` for its cut, not already taken.

    Normally ``<stem>_stroke``, so the pair reads as a pair in a listing. A file
    already there is a cut whose row has been deleted -- the row is restorable
    from the recovery bin and comes back pointing at that very file -- so this
    steps aside rather than writing over it.
    """
    stem, suffix = video_path.stem, video_path.suffix
    candidate = video_path.with_name(f"{stem}{_TRIM_SUFFIX}{suffix}")
    n = 2
    while candidate.exists():
        candidate = video_path.with_name(f"{stem}{_TRIM_SUFFIX} ({n}){suffix}")
        n += 1
    return candidate


def cut_video(src: Path, dest: Path, start_ms: int, end_ms: int) -> None:
    """Re-encode ``src``'s ``[start_ms, end_ms)`` span into ``dest``.

    ``-ss``/``-t`` placed AFTER the input, which makes ffmpeg decode and discard
    up to the mark instead of seeking to the nearest keyframe: the first output
    frame is then the frame the stroke actually turns on, which is the whole
    point of the cut. The span is half-open by the same arithmetic, and that is
    right for a loop -- the frame at ``end_ms`` is the same pose as the one at
    ``start_ms``, so keeping it would stutter every time the clip repeated.

    Re-encoded rather than stream-copied for the same reason: a copy can only
    start on a keyframe. Audio comes along if there is any and is not conjured
    if there is not.
    """
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise FileNotFoundError("ffmpeg is not on PATH, so a clip cannot be cut")
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(src),
         "-ss", f"{start_ms / 1000:.6f}", "-t", f"{(end_ms - start_ms) / 1000:.6f}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", "-c:a", "aac",
         str(dest)],
        check=True, capture_output=True, **hidden_subprocess_kwargs(),
    )


def _record_cut(db, row: dict, dest: Path, output_dir: Path, thumb_dir: Path) -> str:
    """Give ``dest`` a row of its own, cut out of ``row``, and return its id.

    The params, prompts, seed and graph are the source's, copied rather than
    invented: they are as true of the stroke as of the clip it came out of, and
    they are what puts the two in one gallery folder, which is where someone
    looking for "the short one" would look. What separates them is
    ``trimmed_from``, stamped last, and the source column -- no run made this,
    so it does not claim to be a generation.
    """
    prompt_id = str(uuid.uuid4())
    db.insert_generation(
        prompt_id=prompt_id,
        workflow_name=row.get("workflow_name") or "unknown",
        workflow_version=row.get("workflow_version") or "unknown",
        positive_prompt=row.get("positive_prompt"),
        negative_prompt=row.get("negative_prompt"),
        seed=row.get("seed"),
        params_json=row.get("params_json") or "{}",
        workflow_json=row.get("workflow_json") or "{}",
        source=STROKE_TRIM_SOURCE,
    )
    thumb = None
    try:
        thumb = str(generate_thumbnail(dest, "video", thumb_dir, name=prompt_id))
    except Exception as e:
        logger.warning("Thumbnail failed for the cut %s: %s", dest, e)
    subfolder = ""
    try:
        subfolder = dest.parent.relative_to(output_dir).as_posix()
    except ValueError:
        logger.warning("The cut %s landed outside %s", dest, output_dir)
    db.update_generation(
        prompt_id,
        status="completed",
        output_files=json.dumps(
            [{"filename": dest.name, "subfolder": subfolder, "type": "output"}]),
        thumbnail_path=thumb,
        completed_at=datetime.now(UTC).isoformat(),
    )
    db.set_trimmed_from(prompt_id, row["prompt_id"])
    return prompt_id


def clips_sent_whole(rows: list[dict]) -> list[dict]:
    """The clips handed to Genau before the lane learned to cut, oldest send first.

    Everything sent down that lane until now went whole, so Genau has been
    steering four strokes as one for every clip in its folder. These are the rows
    a backfill has work to do on: sent, not themselves a cut, and with no cut of
    them yet -- so a re-run, or a clip the button has since cut, has nothing left
    to do here.

    Oldest send first, because a backfill interrupted halfway should have got
    through the clips that have been wrong the longest. The stamp is only to the
    second and two clips can go down the lane inside one, so the row's own order
    breaks the tie -- otherwise a ``--limit`` run picks whichever of them the
    listing happened to hand over first, and picks a different one next time.
    """
    already_cut = {r["trimmed_from"] for r in rows if r.get("trimmed_from")}
    return sorted(
        (r for r in rows
         if r.get("genau_exported_at")
         and not r.get("trimmed_from")
         and r.get("prompt_id") not in already_cut),
        key=lambda r: (r["genau_exported_at"], r.get("id") or 0),
    )


def single_stroke_clip(row: dict, video_path, db, *, output_dir, thumb_dir) -> Path:
    """The one-stroke cut of ``row``'s clip, made now if it does not exist yet.

    Raises :class:`NoSingleStroke` when the clip has no script or no whole stroke
    in it, and lets an ffmpeg failure out as itself: there is then nothing to
    hand on, and handing on the uncut clip is the defect this exists to fix.

    A row that IS a cut answers with its own file -- it is already one stroke,
    and cutting it again would only copy it. A clip that has been cut before
    answers with that cut, so pressing the button twice, or pressing it after a
    spoken send already went, does not leave a second file and a second row.
    """
    video_path = Path(video_path)
    output_dir, thumb_dir = Path(output_dir), Path(thumb_dir)
    if row.get("trimmed_from"):
        return video_path
    made = db.trim_of(row["prompt_id"])
    if made is not None:
        for f in json.loads(made.get("output_files") or "[]"):
            existing = output_dir / (f.get("subfolder") or "") / (f.get("filename") or "")
            if existing.is_file():
                return existing
    actions = read_actions(funscript_of(video_path, output_dir=output_dir))
    if not actions:
        raise NoSingleStroke(
            "This clip has no stroke track, so there is no single stroke to cut "
            "it down to.")
    span = single_stroke_span(actions)
    if span is None:
        raise NoSingleStroke(
            "This clip's stroke track holds no whole stroke — one extreme, the "
            "other, and back — to cut it down to.")
    start_ms, end_ms = span
    dest = _free_name(video_path)
    cut_video(video_path, dest, start_ms, end_ms)
    if not video_duration_seconds(dest):
        dest.unlink(missing_ok=True)
        raise NoSingleStroke(
            f"The cut of this clip ({start_ms}–{end_ms} ms) came out empty.")
    write_funscript(funscript_path_for(dest, output_dir=output_dir),
                    windowed_actions(actions, start_ms, end_ms))
    prompt_id = _record_cut(db, row, dest, output_dir, thumb_dir)
    logger.info("Cut %s to one stroke (%d–%d ms) as %s (%s)",
                video_path.name, start_ms, end_ms, dest.name, prompt_id)
    return dest
