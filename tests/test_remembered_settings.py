"""Every control a person can set comes back after a restart, or is named here as
no setting, and a control that is neither fails -- the way a Fun Time setting
nobody has said either of does."""
from __future__ import annotations

import json

from funestra.console import BROKER_PRESS
from PyQt6 import sip
from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractSlider,
    QAbstractSpinBox,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QScrollBar,
    QSplitter,
    QTabBar,
    QTextEdit,
    QTreeView,
    QWidget,
)

from origenerator.app_state import AppState
from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.osr2_controls_state import OSR2_CONTROL_BY_COMMAND
from origenerator.gui.panes import PaneSplitter
from tests.test_core import _seed_combine_db, _window

_SETTABLE = (QComboBox, QAbstractSpinBox, QAbstractSlider, QSplitter, CollapsibleSection,
             QLineEdit, QPlainTextEdit, QTextEdit, QTabBar, QTreeView)


def _settable(widget: QWidget) -> bool:
    if isinstance(widget, QScrollBar) or _the_text_box_of_a_spinner_or_dropdown(widget):
        return False
    if isinstance(widget, QAbstractButton):
        return widget.isCheckable()
    return isinstance(widget, _SETTABLE)


def _the_text_box_of_a_spinner_or_dropdown(widget: QWidget) -> bool:
    return isinstance(widget.parentWidget(), (QAbstractSpinBox, QComboBox))


def _within(*containers: QWidget) -> list[QWidget]:
    return [widget for container in containers
            for widget in (container, *container.findChildren(QWidget)) if _settable(widget)]


def _tabs(view) -> list:
    return view._generate_pane.generate_tabs()


REMEMBERED = {
    "generate_tabs": lambda view: [
        widget for tab in _tabs(view) for widget in _within(tab)
        if widget is not tab._how_many and not tab._action.isAncestorOf(widget)
    ] + [view._generate_pane.tabBar()],
    "how_many": lambda view: [tab._how_many for tab in _tabs(view)],
    "toc_sides": lambda view: [view._tree.separate_button, view._tree.together_button],
    "open_folders": lambda view: view._tree.findChildren(QTreeView),
    "pane_sizes": lambda view: [splitter for splitter in view.findChildren(PaneSplitter)
                                if splitter.remembered_as],
    "experiments_enabled": lambda view: [view._experiments_cb],
    "enhance_settings": lambda view: _within(view._enhance.pane),
    "search_sort": lambda view: [view._search._sort_dropdown],
    "gallery_combine": lambda view: _within(view._combine.widget),
    "audio_enabled": lambda view: [view._buttons.radio],
    "mic_enabled": lambda view: [view._buttons.mic],
}

NO_SETTING = {
    "what is being looked for, which is not a place to come back to": lambda view: [
        view._search.field, *_within(view._find_bar), *_within(view._folder_path)],
    "what one item shows, which the library keeps with the item": lambda view: [
        widget for tab in _tabs(view) for widget in _within(tab._action)],
    ("Auto-Generate, which a restart leaves off, since one that came back on by itself"
     " could run unnoticed"): lambda view: [view._buttons.auto],
}

OSR2_CONTROLS_PRESSES_REMEMBERED_AS = {
    "motion": {"robot_hand_speed_up", "robot_hand_speed_down", "robot_hand_amplitude_up",
               "robot_hand_amplitude_down", "robot_hand_center_up", "robot_hand_center_down",
               "robot_hand_cycle_shape", "robot_hand_toggle_learned", "speed", "amp", "center"},
    "osr2_enabled": set(OSR2_CONTROL_BY_COMMAND),
    "max_intensity": {"max_intensity"},
}
OSR2_CONTROLS_PRESSES_THAT_ARE_NO_SETTING = {
    "a read-out, which nothing presses": "",
    "starting or stopping the Broker, which runs whether or not this app is open": BROKER_PRESS,
}


def _a_window_with_every_control_built(qtbot, tmp_path):
    _seed_combine_db(tmp_path)
    win = _window(qtbot, tmp_path, AppState(tmp_path / "ui.json"))
    view = win._gallery_view
    view.refresh()
    view._generate_pane.currentWidget().prefill("sdxl_t2i", {})
    view._generate_pane.open_config("wan22_i2v", {})
    return win


def _address(widget: QWidget) -> int:
    return sip.unwrapinstance(widget)


def _described(widget: QWidget) -> str:
    chain, holder = [], widget
    while holder is not None and len(chain) < 6:
        chain.append(holder.objectName() or type(holder).__name__)
        holder = holder.parentWidget()
    return f"{' < '.join(chain)} ({widget.toolTip()[:50]!r})"


def test_every_control_in_the_window_comes_back_after_a_restart_or_is_no_setting(
        qtbot, tmp_path):
    win = _a_window_with_every_control_built(qtbot, tmp_path)
    claims = (*REMEMBERED.values(), *NO_SETTING.values())
    claimed = {_address(widget) for claim in claims for widget in claim(win._gallery_view)}

    unnamed = [widget for widget in win.findChildren(QWidget)
               if _settable(widget) and _address(widget) not in claimed]

    assert not unnamed, "say how a restart brings back: " + "; ".join(map(_described, unnamed))


def test_every_control_on_the_osr2_controls_comes_back_after_a_restart_or_is_no_setting(
        qtbot, tmp_path):
    controls = _window(qtbot, tmp_path)._gallery_view._osr2_controls
    controls.drawing()
    offered = ({button.command for _rect, button in controls._painter.buttons}
               | {track.axis for track in controls._painter.tracks})

    named = set().union(*OSR2_CONTROLS_PRESSES_REMEMBERED_AS.values(),
                        OSR2_CONTROLS_PRESSES_THAT_ARE_NO_SETTING.values())

    assert offered <= named, f"say how a restart brings back {sorted(offered - named)}"


def test_what_the_census_counts_as_remembered_is_what_the_window_saves(qtbot, tmp_path):
    path = tmp_path / "ui.json"
    _window(qtbot, tmp_path, AppState(path)).close()

    saved = set(json.loads(path.read_text(encoding="utf-8")))

    assert set(REMEMBERED) | set(OSR2_CONTROLS_PRESSES_REMEMBERED_AS) <= saved
