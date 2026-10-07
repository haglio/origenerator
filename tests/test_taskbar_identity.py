from __future__ import annotations

from pathlib import Path

import pytest
from app_support.win32 import TaskbarApp
from PyQt6.QtWidgets import QWidget

from origenerator.gui.taskbar_identity import TaskbarIdentity

_OWN = TaskbarApp(name="Origenerator - preview of a feature",
                  icon=Path("C:/example/preview_icon.ico"),
                  relaunch='wscript.exe "C:/example/preview.vbs"')
_THE_SESSIONS = TaskbarApp(name="Fun Time - preview of a feature",
                           icon=Path("C:/example/preview_session_icon.ico"),
                           relaunch='wscript.exe "C:/example/session.vbs"')


@pytest.fixture
def worn(qapp):
    dressed: list[tuple[str, TaskbarApp | None]] = []
    identity = TaskbarIdentity(qapp, "Origenerator.Preview", _OWN,
                               dress=lambda hwnd, app_id, app: dressed.append((app_id, app)),
                               described={"FunTime.App.Preview": _THE_SESSIONS}.get)
    yield identity, dressed
    qapp.removeEventFilter(identity)


def test_a_window_wears_the_apps_own_identity_from_the_moment_it_is_shown(worn):
    _, worn = worn
    window = QWidget()

    window.show()

    assert worn == [("Origenerator.Preview", _OWN)]
    window.close()


def test_what_a_window_holds_is_left_to_the_window(worn):
    _, worn = worn
    window = QWidget()
    QWidget(window)

    window.show()

    assert len(worn) == 1
    window.close()


def test_once_a_session_takes_the_app_its_windows_join_the_sessions_button(worn):
    identity, worn = worn
    identity.join("FunTime.App.Preview")
    window = QWidget()

    window.show()

    assert worn == [("FunTime.App.Preview", _THE_SESSIONS)]
    window.close()


def test_handed_back_its_windows_wear_its_own_identity_again(worn):
    identity, worn = worn
    identity.join("FunTime.App.Preview")
    identity.leave()
    window = QWidget()

    window.show()

    assert worn == [("Origenerator.Preview", _OWN)]
    window.close()


def test_a_window_windows_will_not_dress_still_opens(qapp):
    def refuse(hwnd, app_id, app):
        raise OSError("SHGetPropertyStoreForWindow failed")

    identity = TaskbarIdentity(qapp, "Origenerator.Preview", _OWN, dress=refuse,
                               described=lambda app_id: None)
    window = QWidget()
    try:
        window.show()

        assert window.isVisible()
    finally:
        window.close()
        qapp.removeEventFilter(identity)
