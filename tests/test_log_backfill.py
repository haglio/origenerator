from __future__ import annotations

from datetime import UTC, datetime

from origenerator.db import Database, NewGeneration
from origenerator.log_backfill import (
    backfill_durations_from_logs,
    parse_log_durations,
)


def _local_epoch(moment):
    return datetime(*moment).astimezone().timestamp()


def _completed_at_as_the_importer_stores_it(moment):
    epoch = _local_epoch(moment)
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat()


def _import_row(db, prompt_id, completed_at):
    db.insert_generation(NewGeneration(prompt_id=prompt_id, workflow_name="sdxl_t2i",
                         workflow_version="imported", params_json="{}",
                         workflow_json="{}", source="imported"))
    db.update_generation(prompt_id, status="completed", completed_at=completed_at)


def test_parse_log_durations_extracts_timestamp_and_duration():
    text = (
        "[2026-06-29 12:20:53.244] Prompt executed in 15.26 seconds\n"
        "[2026-06-29 12:21:00.000] Some unrelated log line\n"
        "[2026-06-29 12:33:57.623] Prompt executed in 0.79 seconds\n"
    )
    result = parse_log_durations(text)
    assert result == [
        (_local_epoch((2026, 6, 29, 12, 20, 53, 244000)), 15.26),
        (_local_epoch((2026, 6, 29, 12, 33, 57, 623000)), 0.79),
    ]


def test_parse_log_durations_ignores_lines_without_the_marker():
    assert parse_log_durations("[2026-06-29 12:00:00.000] Startup complete\n") == []


def test_backfill_matches_rows_to_nearest_log_line(tmp_path):
    db = Database(tmp_path / "test.db")
    _import_row(db, "rowA", _completed_at_as_the_importer_stores_it((2026, 6, 29, 12, 20, 53, 244000)))
    _import_row(db, "rowB", _completed_at_as_the_importer_stores_it((2026, 6, 29, 12, 33, 57)))

    log = tmp_path / "comfyui.log"
    log.write_text(
        "[2026-06-29 09:00:00.000] Prompt executed in 99.00 seconds\n"
        "[2026-06-29 12:20:55.000] Prompt executed in 15.26 seconds\n"
        "[2026-06-29 12:33:57.623] Prompt executed in 0.79 seconds\n"
    )

    matched = backfill_durations_from_logs(db, [log])

    assert matched == 2
    assert db.get_generation("rowA")["duration_seconds"] == 15.26
    assert db.get_generation("rowB")["duration_seconds"] == 0.79


def test_backfill_leaves_unmatched_rows_untouched(tmp_path):
    db = Database(tmp_path / "test.db")
    _import_row(db, "lonely", _completed_at_as_the_importer_stores_it((2026, 6, 29, 12, 0, 0)))

    log = tmp_path / "comfyui.log"
    log.write_text("[2026-06-29 12:30:00.000] Prompt executed in 5.00 seconds\n")

    assert backfill_durations_from_logs(db, [log]) == 0
    assert db.get_generation("lonely")["duration_seconds"] is None


def test_backfill_does_not_reuse_one_line_for_two_rows(tmp_path):
    db = Database(tmp_path / "test.db")
    _import_row(db, "batch1", _completed_at_as_the_importer_stores_it((2026, 6, 29, 12, 20, 53)))
    _import_row(db, "batch2", _completed_at_as_the_importer_stores_it((2026, 6, 29, 12, 20, 53)))

    log = tmp_path / "comfyui.log"
    log.write_text("[2026-06-29 12:20:53.500] Prompt executed in 15.26 seconds\n")

    assert backfill_durations_from_logs(db, [log]) == 1
    durations = sorted(
        db.get_generation(p)["duration_seconds"] is not None
        for p in ("batch1", "batch2")
    )
    assert durations == [False, True], (
        "a batch's two files share one line, and the second stays untimed rather than counted twice")


def test_backfill_gives_the_one_line_to_the_row_it_sits_closest_to(tmp_path):
    db = Database(tmp_path / "test.db")
    _import_row(db, "far", _completed_at_as_the_importer_stores_it((2026, 6, 29, 12, 20, 0)))
    _import_row(db, "near", _completed_at_as_the_importer_stores_it((2026, 6, 29, 12, 20, 50)))

    log = tmp_path / "comfyui.log"
    log.write_text("[2026-06-29 12:20:52.000] Prompt executed in 15.26 seconds\n")

    assert backfill_durations_from_logs(db, [log]) == 1
    assert db.get_generation("near")["duration_seconds"] == 15.26
    assert db.get_generation("far")["duration_seconds"] is None


def test_backfill_takes_a_line_up_to_two_minutes_from_the_file_and_no_further(tmp_path):
    db = Database(tmp_path / "test.db")
    _import_row(db, "inside", _completed_at_as_the_importer_stores_it((2026, 6, 29, 12, 0, 0)))
    _import_row(db, "outside", _completed_at_as_the_importer_stores_it((2026, 6, 29, 13, 0, 0)))

    log = tmp_path / "comfyui.log"
    log.write_text("[2026-06-29 12:01:59.000] Prompt executed in 5.00 seconds\n"
                   "[2026-06-29 13:02:01.000] Prompt executed in 6.00 seconds\n")

    assert backfill_durations_from_logs(db, [log]) == 1
    assert db.get_generation("inside")["duration_seconds"] == 5.0
    assert db.get_generation("outside")["duration_seconds"] is None, (
        "ComfyUI writes the line moments after the file, and a wider window would match another run")


def test_backfill_leaves_a_row_that_already_has_a_duration_as_it_is(tmp_path):
    db = Database(tmp_path / "test.db")
    _import_row(db, "timed", _completed_at_as_the_importer_stores_it((2026, 6, 29, 12, 0, 0)))
    db.update_generation("timed", duration_seconds=3.0)

    log = tmp_path / "comfyui.log"
    log.write_text("[2026-06-29 12:00:01.000] Prompt executed in 9.00 seconds\n")

    assert backfill_durations_from_logs(db, [log]) == 0
    assert db.get_generation("timed")["duration_seconds"] == 3.0
