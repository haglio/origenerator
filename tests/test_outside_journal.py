from __future__ import annotations

from origenerator.outside_journal import said_in


def test_a_journal_line_that_is_not_json_is_skipped_and_the_rest_are_kept(tmp_path):
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        'not json at all\n{"path": "scene one.mp4", "t": 5, "event": "favorite"}\n',
        encoding="utf-8")

    assert said_in(journal) == [{"path": "scene one.mp4", "t": 5, "event": "favorite"}]
