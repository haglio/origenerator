from __future__ import annotations

from shared_ui.reference import CommandRef, ReferenceGroup, ReferenceSection

from origenerator.gallery.voice_commands import ENHANCE_COMMAND
from origenerator.voice.app_commands import AppCommand, said_as
from origenerator.voice.dictation import LEAD_WORDS
from origenerator.voice.slideshow_commands import SlideshowCommand, said_to_the_slideshow
from origenerator.workflows.detail_parts import published_fix_phrases

_DETAIL_DASH = " — "


def _row(description: str, keys: tuple[str, ...] = (), *, said: tuple[str, ...] = ()) -> CommandRef:
    action, _, detail = description.partition(_DETAIL_DASH)
    return CommandRef(action, said, key_columns=(keys,), detail=detail)


_AS_WRITTEN = (("o s r two", "OSR2"), ("osr two", "OSR2"))


def _as_written(phrase: str) -> str:
    for heard, written in _AS_WRITTEN:
        phrase = phrase.replace(heard, written)
    return phrase


def _said(*commands: AppCommand) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_as_written(phrase) for command in commands
                               for phrase in said_as(command)))


def _core() -> ReferenceSection:
    return ReferenceSection("Core", (
        ReferenceGroup("", (
            _row("quit", ("Ctrl+Alt+Q",)),
            _row("pause / play everything — stops and starts the sounds and the animations; "
                 "the play/pause button does the same", ("Esc",),
                 said=said_to_the_slideshow(SlideshowCommand.PAUSE)),
            _row("open / close the slideshow — opens it on the image a double click would",
                 ("Shift+Esc",),
                 said=said_to_the_slideshow(SlideshowCommand.START, SlideshowCommand.STOP)),
            _row("find", ("Ctrl+F",)),
            _row("back / forward", said=_said(AppCommand.BACK, AppCommand.FORWARD)),
            _row("undo / redo", ("Ctrl+Z", "Ctrl+Shift+Z"),
                 said=_said(AppCommand.UNDO, AppCommand.REDO)),
            _row("delete", ("Delete",), said=_said(AppCommand.CULL)),
            _row("copy the names of what is picked", ("Ctrl+C",)),
            _row("favorite", said=_said(AppCommand.FAVORITE)),
            _row("group the picked folders into a collection of your own",
                 said=_said(AppCommand.GROUP)),
        )),
        ReferenceGroup("Collections", (
            _row("Latest", said=_said(AppCommand.LATEST)),
            _row("Favorites", said=_said(AppCommand.FAVORITES)),
            _row("Experiments", said=_said(AppCommand.EXPERIMENTS)),
        )),
        ReferenceGroup("Switches", (
            _row("Populate on / off",
                 said=_said(AppCommand.POPULATE, AppCommand.POPULATE_ON, AppCommand.POPULATE_OFF)),
            _row("Origenerator Radio on / off",
                 said=_said(AppCommand.RADIO, AppCommand.RADIO_ON, AppCommand.RADIO_OFF)),
        )),
        ReferenceGroup("Voice control", (
            _row("stop listening", said=_said(AppCommand.MIC_OFF)),
            _row("Request — say what to change about the image on screen, and end with “over”",
                 said=LEAD_WORDS[:1]),
        )),
    ))


def _the_image() -> ReferenceSection:
    return ReferenceSection("The image on screen", (
        ReferenceGroup("", (
            _row("enhance it", said=(ENHANCE_COMMAND, f"{ENHANCE_COMMAND} it")),
            _row("fix a part of it", said=published_fix_phrases()),
            _row("animate it — name the action after “animate as”, as the Action list "
                 "shows it", said=("animate as",)),
        )),
    ))


def _osr2() -> ReferenceSection:
    return ReferenceSection("OSR2", (
        ReferenceGroup("", (
            _row("control on / off", ("Space",),
                 said=_said(AppCommand.DRIVE, AppCommand.DRIVE_ON, AppCommand.DRIVE_OFF)),
        )),
        ReferenceGroup("Robot Hand", (
            _row("speed up / down", ("L", "J"), said=_said(AppCommand.SPEED_UP, AppCommand.SPEED_DOWN)),
            _row("set speed", said=("min speed", "max speed", "speed 0–100")),
            _row("amplitude up / down", ("9", "7"), said=_said(AppCommand.AMP_UP, AppCommand.AMP_DOWN)),
            _row("set amplitude", said=("min amp", "max amp", "amp 0–100")),
            _row("center up / down", ("O", "U"),
                 said=_said(AppCommand.CENTER_UP, AppCommand.CENTER_DOWN)),
            _row("set center", said=("min center", "max center", "center 0–100")),
            _row("previous waveform shape", said=_said(AppCommand.PREVIOUS_SHAPE)),
            _row("next waveform shape", ("I",), said=_said(AppCommand.NEXT_SHAPE)),
            _row("enable / disable human-inspired motion", (";",),
                 said=_said(AppCommand.LEARNED, AppCommand.LEARNED_ON, AppCommand.LEARNED_OFF)),
        )),
    ))


_SLIDESHOW_NOTE = ("Add “portrait” or “landscape” before a phrase to aim it at that slideshow, "
                   "for example “portrait next”.")


def _slideshow() -> ReferenceSection:
    return ReferenceSection("Slideshow", (
        ReferenceGroup("", (
            _row("close the slideshow", ("Enter",)),
        )),
        ReferenceGroup("Navigation", (
            _row("previous", ("Left", "A"), said=_said(AppCommand.BACK)),
            _row("next", ("Right", "D"), said=_said(AppCommand.FORWARD)),
            _row("previous version", ("Shift+Left", "Shift+A")),
            _row("next version", ("Shift+Right", "Shift+D")),
            _row("up the nav map", ("Shift+Up", "Shift+W")),
            _row("down the nav map", ("Shift+Down", "Shift+S")),
            _row("cycle loop mode", ("E", "Home")),
        )),
        ReferenceGroup("What is on screen", (
            _row("delete it and move on", ("Up", "W"), said=_said(AppCommand.CULL)),
            _row("lock / unlock it", ("Down", "S"), said=_said(AppCommand.LOCK, AppCommand.UNLOCK)),
            _row("favorite it", said=_said(AppCommand.FAVORITE)),
        )),
        ReferenceGroup("Filter", (
            _row("show only the enhanced ones", said=_said(AppCommand.FILTER_ENHANCED)),
            _row("drop the filter", said=_said(AppCommand.FILTER_OFF)),
        )),
        ReferenceGroup("HUD", tuple(
            _row(f"HUD {direction}", (f"Ctrl+{arrow}", f"Ctrl+{letter}"))
            for direction, arrow, letter in (("left", "Left", "A"), ("right", "Right", "D"),
                                             ("up", "Up", "W"), ("down", "Down", "S"))
        )),
    ), note=_SLIDESHOW_NOTE)


def reference_sections() -> tuple[ReferenceSection, ...]:
    return (_core(), _the_image(), _osr2(), _slideshow())
