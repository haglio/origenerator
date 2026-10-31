"""What this repo hands Evolver, held to what Evolver promises.

A send copies the video into a folder of Evolver's and the gallery later reads
Evolver's upscale back out of another -- both spelled here, from reading that
repo's source, with nothing comparing them.  A folder renamed over there left
this app dropping videos where nothing ingests them, and every suite stayed
green.

Evolver publishes ``evolver_contract.json`` at its checkout root now.  These
hold this repo's paths and its half-written name to it.  Neither gate clones
the other, so on a machine with no Evolver beside this one there is nothing to
compare and the check says so.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from origenerator import config, evolver_export, outside_videos
from origenerator.generation_state import GenerationSource

CONTRACT = Path("evolver") / "evolver_contract.json"


def _promise() -> dict:
    """Evolver's published document, found beside this checkout.

    Walked up from here rather than resolved through the content overlay: the
    overlay is git-ignored, so a worktree -- which is where every suite runs --
    has only the placeholder one, pointing at a library that is not there.  The
    walk lands on the checkout beside the primary from a worktree and from a
    clone alike.
    """
    for parent in Path(__file__).resolve().parents:
        published = parent / CONTRACT
        if published.is_file():
            return json.loads(published.read_text(encoding="utf-8"))
    pytest.skip(f"no {CONTRACT.as_posix()} beside this checkout")


def test_the_folders_this_app_sends_to_are_the_ones_evolver_watches():
    """Library-relative in the document, because the library root is private
    and each app resolves it from its own overlay."""
    relative = _promise()["library_relative"]

    under_library = {name: config.LIBRARY_ROOT / Path(value)
                     for name, value in relative.items()}

    assert under_library == {"inbox_dir": config.EVOLVER_INBOX_DIR,
                             "upscaled_dir": config.EVOLVER_UPSCALED_DIR}


def test_a_copy_still_being_written_wears_the_name_evolver_walks_past():
    """The marker is the whole of why a run of Evolver's pipeline never ingests
    half a video, and it has to be IN the name, not merely near it."""
    marker = _promise()["partial_marker"]

    partial = evolver_export.partial_name(Path("some-clip.mp4"))

    assert marker in partial.name


def test_a_star_this_app_journals_is_a_line_evolver_carries_into_fun_times_favorites(tmp_path):
    """Evolver's favorites stage reads every journal in the folder it publishes,
    in the fields it publishes, so a star set on another source's video here
    reaches Fun Time's list the way the phone's favorites do."""
    promise = _promise()
    journals = promise["journals"]
    video, row = _another_sources_video(promise)
    places = _journaling_into(tmp_path, beside=video)

    outside_videos.journal_favorites(places, [row], True)
    outside_videos.journal_favorites(places, [row], False)

    lines = _journaled(places)
    assert all(set(line) == set(journals["fields"]) for line in lines)
    assert [line["event"] for line in lines] == journals["favorite_events"]
    assert {config.LIBRARY_ROOT / Path(line["path"]) for line in lines} == {video}


def test_an_act_picked_here_is_a_line_evolver_writes_into_the_videos_record(tmp_path):
    promise = _promise()
    journals = promise["journals"]
    video, row = _another_sources_video(promise)
    places = _journaling_into(tmp_path, beside=video)

    outside_videos.pick_act(MagicMock(), places, row, "Wave")

    [line] = _journaled(places)
    assert set(journals["fields"]) <= set(line)
    assert (line["event"], line[journals["act_field"]]) == (journals["act_event"], "Wave")
    assert config.LIBRARY_ROOT / Path(line["path"]) == video


def _another_sources_video(promise: dict) -> tuple[Path, dict]:
    video = (config.LIBRARY_ROOT / Path(promise["library_relative"]["upscaled_dir"])
             / "portrait" / "a-site" / "c1_topaz.mp4")
    row = {"prompt_id": "c1", "source": GenerationSource.OUTSIDE,
           "output_files": json.dumps([{"filename": video.name, "library_path": str(video)}])}
    return video, row


def _journaling_into(folder: Path, *, beside: Path) -> outside_videos.Places:
    return outside_videos.Places(
        upscaled_dir=beside.parents[2], records_folder=folder, frames_dir=folder,
        thumb_dir=folder, skip_sources=frozenset(), library_root=config.LIBRARY_ROOT,
        journal=folder / outside_videos.JOURNAL_NAME)


def _journaled(places: outside_videos.Places) -> list[dict]:
    return [json.loads(line) for line in places.journal.read_text(encoding="utf-8").splitlines()]
