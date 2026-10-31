"""A run's toast raised on the desktop, and taken back by the run it is about.

Nothing here raises one: a toast raised by a test is a toast on the
user's screen. What Windows is handed is caught at its door instead.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

from origenerator import toast_raising, windows_toast
from origenerator.run_toast import Toast

_RUN = "7f0c9b2e-1111-4444-8888-aaaabbbbcccc"


def _toast(generation=_RUN):
    return Toast("Video ready", "Example Workflow · 4:12", ok=True, generation=generation)


def _filings(monkeypatch):
    raised, taken_back = [], []
    monkeypatch.setattr(toast_raising, "show",
                        lambda app_id, xml, **filing: raised.append((app_id, filing)))
    monkeypatch.setattr(toast_raising, "take_back",
                        lambda app_id, **filing: taken_back.append((app_id, filing)))
    return raised, taken_back


def test_the_toast_a_run_raised_is_the_one_taken_back_for_that_run(monkeypatch):
    raised, taken_back = _filings(monkeypatch)

    toast_raising.raise_toast("Example.App", _toast())
    toast_raising.take_back_toast("Example.App", _RUN)

    assert taken_back == raised


def test_two_runs_toasts_are_filed_apart(monkeypatch):
    raised, taken_back = _filings(monkeypatch)

    toast_raising.raise_toast("Example.App", _toast())
    toast_raising.take_back_toast("Example.App", "another-run")

    assert taken_back[0][1]["tag"] != raised[0][1]["tag"]


def test_a_run_of_the_longest_id_a_link_carries_files_its_toast_where_windows_takes_it(
        monkeypatch):
    filed = []

    def file_without_raising(_app_id, xml, **filing):
        with windows_toast.filed(xml, **filing):
            filed.append(filing)

    monkeypatch.setattr(toast_raising, "show", file_without_raising)

    toast_raising.raise_toast("Example.App", _toast(generation="a" * 128))

    assert len(filed) == 1


def test_windows_refusing_the_take_back_costs_the_app_nothing(monkeypatch, caplog):
    def refuse(_app_id, **_filing):
        raise OSError("the toast platform is not listening")

    monkeypatch.setattr(toast_raising, "take_back", refuse)

    with caplog.at_level("WARNING", logger="origenerator.toast_raising"):
        toast_raising.take_back_toast("Example.App", _RUN)

    assert "not listening" in caplog.text


def test_a_toast_about_no_item_is_raised_with_no_link(monkeypatch):
    raised = []
    monkeypatch.setattr(toast_raising, "show", lambda app_id, xml, **filing: raised.append(xml))

    toast_raising.raise_toast("Example.App", _toast(generation=""))

    assert "launch" not in raised[0]
