from __future__ import annotations

import json
from pathlib import Path

import pytest

from origenerator import config, evolver_export, outside_videos
from origenerator.generation_state import GenerationSource

CONTRACT = Path("evolver") / "evolver_contract.json"


def _promise() -> dict:
    for parent in Path(__file__).resolve().parents:
        published = parent / CONTRACT
        if published.is_file():
            return json.loads(published.read_text(encoding="utf-8"))
    pytest.skip(f"no {CONTRACT.as_posix()} beside this checkout")


def test_the_folders_this_app_sends_to_are_the_ones_evolver_watches():
    relative = _promise()["library_relative"]
    sent_to = {"inbox_dir": config.EVOLVER_INBOX_DIR,
               "upscaled_dir": config.EVOLVER_UPSCALED_DIR,
               "trash_dir": config.KINO_TRASH_DIR}

    watched = {name: config.LIBRARY_ROOT / Path(relative[name])
               for name in sent_to if name in relative}

    assert watched == sent_to


def test_a_copy_still_being_written_wears_the_name_evolver_walks_past():
    marker = _promise()["partial_marker"]

    partial = evolver_export.partial_name(Path("some-clip.mp4"))

    assert marker in partial.name


def test_a_star_this_app_journals_is_a_line_evolver_carries_into_fun_times_favorites(tmp_path):
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
