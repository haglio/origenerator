"""The window for settling what each animation runs: the image a sample started
from, the sample, and the prompts, which are editable. The walk is
:class:`~origenerator.animation_check_session.AnimationCheckSession`."""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from shared_ui.spacing import GAP_MEDIUM, MARGIN_STANDARD

from origenerator.animate_command import lane_said_as
from origenerator.gui.looping_preview import play_in, stop_what_plays_in
from origenerator.gui.stylesheet import COMMITS

HEADING = "animation.heading"
COUNTED = "animation.counted"
SAID = "animation.said"
POSITIVE = "animation.positive"
NEGATIVE = "animation.negative"
ACCEPT = "animation.accept"
SUBMIT = "animation.submit"
REJECT = "animation.reject"
BACK = "animation.back"
FORWARD = "animation.forward"

IMAGE = "animation.image"
SAMPLE = "animation.sample"
BLANK = "animation.blank"

NO_SAMPLE = ("No video made this way has been favorited "
              "or sent to Genau or Evolver.")
FROM_THE_ACTS_OWN = (
    "No video made this way has been favorited or sent to Genau or Evolver. "
    "The prompts below are this act's own settings, to start from.")
ALL_DONE = "Every animation has been through."


class AnimationCheckWindow(QWidget):
    """One animation at a time, with the video that stands as its sample."""

    def __init__(self, session, look, submit, parent=None):
        """``look`` answers ``(image path, looping sample path)`` for a sample;
        ``submit`` queues a run of the edited prompts on that sample's image."""
        super().__init__(parent)
        self._session = session
        self._look = look
        self._submit = submit
        self._still = QPixmap()
        self.setWindowTitle("Origenerator — how should this be animated?")

        self._heading = QLabel(objectName=HEADING)
        self._heading.setStyleSheet("font-weight: bold;")
        self._counted = QLabel(objectName=COUNTED)
        self._counted.setToolTip(
            "Every animation that can be asked for — each act, in each lane, from each "
            "kind of image — and how many already have settings assigned.")
        self._said = QLabel(objectName=SAID)
        self._said.setWordWrap(True)
        self._image = QLabel(objectName=IMAGE)
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setMinimumSize(280, 280)
        self._clip = QLabel(objectName=SAMPLE)
        self._clip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._clip.setMinimumSize(280, 280)

        pair = QWidget()
        shown = QHBoxLayout(pair)
        shown.setContentsMargins(0, 0, 0, 0)
        shown.setSpacing(GAP_MEDIUM)
        shown.addWidget(self._image, 1)
        shown.addWidget(self._clip, 1)
        # Sharing the row it reads as a caption on the image's half.
        self._blank = QLabel(NO_SAMPLE, objectName=BLANK)
        self._blank.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._blank.setWordWrap(True)
        self._shown = QStackedWidget()
        self._shown.addWidget(pair)
        self._shown.addWidget(self._blank)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_STANDARD, MARGIN_STANDARD,
                                  MARGIN_STANDARD, MARGIN_STANDARD)
        layout.setSpacing(GAP_MEDIUM)
        layout.addWidget(self._heading)
        layout.addLayout(self._build_where_it_is())
        layout.addWidget(self._shown, 1)
        layout.addWidget(QLabel("Prompt"))
        self._positive = QPlainTextEdit(objectName=POSITIVE)
        self._negative = QPlainTextEdit(objectName=NEGATIVE)
        for box in (self._positive, self._negative):
            box.setMaximumHeight(90)
            box.textChanged.connect(self._only_offer_a_new_sample_once_edited)
        layout.addWidget(self._positive)
        layout.addWidget(QLabel("Negative prompt"))
        layout.addWidget(self._negative)
        layout.addWidget(self._said)
        layout.addLayout(self._build_answers())

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.close)
        self._show_current()

    def _build_where_it_is(self) -> QHBoxLayout:
        where = QHBoxLayout()
        where.setSpacing(GAP_MEDIUM)
        where.addWidget(self._step(BACK, "<", "The animation before this one",
                                   self._on_back))
        where.addWidget(self._counted)
        where.addWidget(self._step(FORWARD, ">", "The animation after this one",
                                   self._on_forward))
        where.addStretch(1)
        return where

    def _step(self, name: str, caption: str, tip: str, press) -> QPushButton:
        step = QPushButton(caption, objectName=name)
        step.setToolTip(tip)
        step.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        step.clicked.connect(press)
        return step

    def _build_answers(self) -> QHBoxLayout:
        answers = QHBoxLayout()
        answers.setSpacing(GAP_MEDIUM)
        for name, caption, tip, press in (
            (REJECT, "View next preexisting sample from library",
             "Drop this one and show the next video made this way", self._on_reject),
            (SUBMIT, "Generate new sample with current settings",
             "Queue a video of this image with the prompts as they now read, "
             "and come back to this animation once it is done", self._on_submit),
            (ACCEPT, "Assign these settings",
             "Every animation of this act from this kind of image runs these "
             "settings, with the prompts as they now read", self._on_accept),
        ):
            button = QPushButton(caption, objectName=name)
            button.setToolTip(tip)
            if name == ACCEPT:
                button.setProperty(COMMITS, True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(press)
            answers.addWidget(button)
        return answers


    def _on_accept(self) -> None:
        self._session.accept(positive=self._positive.toPlainText(),
                             negative=self._negative.toPlainText())
        self._show_current("Settings taken.")

    def _on_submit(self) -> None:
        self._said.setText(self._submit(self._session.sample,
                                        self._positive.toPlainText(),
                                        self._negative.toPlainText()))

    def _on_reject(self) -> None:
        self._session.next_sample()
        self._show_current("Sample dropped.")

    def _on_forward(self) -> None:
        self._session.forward()
        self._show_current()

    def _on_back(self) -> None:
        self._session.back()
        self._show_current()


    def _show_current(self, said: str = "") -> None:
        self._said.setText(said)
        path = self._session.path
        if path is None:
            self._heading.setText(ALL_DONE)
            self._counted.setText("")
            self._clear_the_pair()
            self._press(REJECT).setEnabled(False)
            self._press(SUBMIT).setEnabled(False)
            return
        lane, act, state = path
        self._heading.setText(
            f"{lane_said_as(lane)} · {act} · from a “{state}” image")
        at, of = self._session.position
        self._counted.setText(f"{at} of {of} · {self._session.answered} done")
        sample = self._session.sample
        from_here = self._session.starting_point
        self._shown.setCurrentWidget(self._blank if sample is None else
                                     self._shown.widget(0))
        self._blank.setText(NO_SAMPLE if from_here is None else FROM_THE_ACTS_OWN)
        self._press(REJECT).setEnabled(self._session.another_sample)
        self._write_the_prompts(sample, from_here)
        self._only_offer_a_new_sample_once_edited()
        if sample is None:
            self._clear_the_pair(keep_the_prompts=True)
            return
        still, loop = self._look(sample)
        self._still = QPixmap(str(still)) if still else QPixmap()
        self._draw_the_still()
        self._play(loop)

    def _press(self, name: str) -> QPushButton:
        return self.findChild(QPushButton, name)

    def _only_offer_a_new_sample_once_edited(self) -> None:
        """A new sample is worth the GPU only once a prompt differs from it."""
        sample = self._session.sample or {}
        edited = (self._positive.toPlainText() != (sample.get("positive_prompt") or "")
                  or self._negative.toPlainText() != (sample.get("negative_prompt") or ""))
        self._press(SUBMIT).setEnabled(sample != {} and edited)

    def _write_the_prompts(self, sample: dict | None, from_here: dict | None) -> None:
        held = sample or (from_here or {}).get("params") or {}
        self._positive.setPlainText(held.get("positive_prompt") or "")
        self._negative.setPlainText(held.get("negative_prompt") or "")

    def _clear_the_pair(self, *, keep_the_prompts: bool = False) -> None:
        self._still = QPixmap()
        self._image.clear()
        stop_what_plays_in(self._clip)
        self._clip.clear()
        if not keep_the_prompts:
            self._positive.setPlainText("")
            self._negative.setPlainText("")

    def _draw_the_still(self) -> None:
        if self._still.isNull():
            self._image.setText("(this image's file is missing)")
            return
        self._image.setPixmap(self._still.scaled(
            self._image.width(), self._image.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def _play(self, loop) -> None:
        if not loop:
            self._clip.clear()
            self._clip.setText("(this clip's file is missing)")
            return
        play_in(self._clip, str(loop),
                QSize(self._clip.width(), self._clip.height()))

    def resizeEvent(self, event):  # noqa: N802 — Qt override
        super().resizeEvent(event)
        self._draw_the_still()
