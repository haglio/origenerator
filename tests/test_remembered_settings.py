"""Every control a person can set comes back after a restart, or is named here as
no setting, and a control that is neither fails -- the way a Fun Time setting
nobody has said either of does."""
from __future__ import annotations

import json

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
from origenerator.gui.console import OSR2_CONTROL_BY_COMMAND
from origenerator.gui.panes import PaneSplitter
from tests.test_main_window import _seed_combine_db, _window

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
    return view._info_tabs.config_panels()


REMEMBERED = {
    "generate_tabs": lambda view: [
        widget for panel in _tabs(view) for widget in _within(panel)
        if widget is not panel._how_many and not panel._picture_state.isAncestorOf(widget)
    ] + [view._info_tabs.tabBar()],
    "how_many": lambda view: [panel._how_many for panel in _tabs(view)],
    "toc_sides": lambda view: [view._tree.separate_button, view._tree.together_button],
    "open_folders": lambda view: view._tree.findChildren(QTreeView),
    "pane_sizes": lambda view: [splitter for splitter in view.findChildren(PaneSplitter)
                                if splitter.remembered_as],
    "experiments_enabled": lambda view: [view._experiments_cb],
    "enhance_settings": lambda view: _within(view._enhance.panel),
    "search_sort": lambda view: [view._search._sort_combo],
    "gallery_combine": lambda view: _within(view._combine.panel),
    "audio_enabled": lambda view: [view._bank.audio],
    "mic_enabled": lambda view: [view._bank.mic],
}

NO_SETTING = {
    "what is being looked for, which is not a place to come back to": lambda view: [
        view._search.field, *_within(view._find_bar), *_within(view._folder_path)],
    "what one picture shows, which the library keeps with the picture": lambda view: [
        widget for panel in _tabs(view) for widget in _within(panel._picture_state)],
    ("Auto-generate, which a restart leaves off, since a loop that came back on by itself"
     " could run unnoticed"): lambda view: [view._bank.auto],
}

CONSOLE_PRESSES_REMEMBERED_AS = {
    "motion": {"robot_hand_speed_up", "robot_hand_speed_down", "robot_hand_amplitude_up",
               "robot_hand_amplitude_down", "robot_hand_center_up", "robot_hand_center_down",
               "robot_hand_cycle_shape", "robot_hand_toggle_learned", "speed", "amp", "center"},
    "osr2_enabled": set(OSR2_CONTROL_BY_COMMAND),
    "max_intensity": {"max_intensity"},
}
CONSOLE_PRESSES_THAT_ARE_NO_SETTING = {
    "a read-out, which nothing presses": "",
}


def _a_window_with_every_control_built(qtbot, tmp_path):
    _seed_combine_db(tmp_path)
    win = _window(qtbot, tmp_path, AppState(tmp_path / "ui.json"))
    view = win._gallery_view
    view.refresh()
    view._info_tabs.currentWidget().prefill("sdxl_t2i", {})
    view._info_tabs.open_config("wan22_i2v", {})
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


def test_every_control_on_the_console_comes_back_after_a_restart_or_is_no_setting(
        qtbot, tmp_path):
    console = _window(qtbot, tmp_path)._gallery_view._motion_panel
    console.render_console()
    offered = ({button.command for _rect, button in console._painter.buttons}
               | {track.axis for track in console._painter.tracks})

    named = set().union(*CONSOLE_PRESSES_REMEMBERED_AS.values(),
                        CONSOLE_PRESSES_THAT_ARE_NO_SETTING.values())

    assert offered <= named, f"say how a restart brings back {sorted(offered - named)}"


def test_what_the_census_counts_as_remembered_is_what_the_window_saves(qtbot, tmp_path):
    path = tmp_path / "ui.json"
    _window(qtbot, tmp_path, AppState(path)).close()

    saved = set(json.loads(path.read_text(encoding="utf-8")))

    assert set(REMEMBERED) | set(CONSOLE_PRESSES_REMEMBERED_AS) <= saved
