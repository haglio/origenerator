"""The combine panel's "already generated" dialog.

Re-running a workflow whose seed isn't randomized re-creates a byte-identical
output. A config tab needs no dialog for that — its Generate button says up front
that the press will draw a fresh seed (see
:meth:`GenerateConfigPanel._apply_generate_caption`) — but a combine has a real
question to ask: an image-to-video carries two seeds, its start frame's and its
motion's, so when the dropped frame is itself a re-buildable generation the
dialog offers each on its own (new motion of the same frame, or a new frame with
the same motion) as well as both. A recipe with one re-rollable seed — a dropped
frame that was imported rather than generated — keeps the lone "New Random Seed".
"""

from PyQt6.QtWidgets import QMessageBox

# Which seed(s) the user chose to re-roll (``None`` from :func:`offer_reroll`
# means they cancelled). REROLL_VIDEO is also the single-seed workflows' choice —
# their one seed is "the video seed" as far as the caller's re-roll is concerned.
REROLL_VIDEO = "video"  # keep the start frame, re-roll the video seed
REROLL_IMAGE = "image"  # re-roll the start frame, keep the video seed
REROLL_BOTH = "both"    # a fresh frame and a fresh video seed


def _build_reroll_box(parent, workflow, can_reroll_image: bool):
    """The "already generated" dialog and its button -> choice map (no exec yet).

    Split from :func:`offer_reroll` so the button/choice wiring is testable
    without spinning a modal loop. Buttons absent from the map (Cancel, the close
    box) resolve to ``None``.
    """
    media = workflow.output_type if workflow.output_type in ("image", "video") else "output"
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Already generated")
    box.setText(
        f"You've already generated this exact {media} — same settings and "
        f"the same seed.\nRunning it again will just re-create an identical {media}."
    )
    accept = QMessageBox.ButtonRole.AcceptRole
    if not can_reroll_image:
        box.setInformativeText("Generate a new random seed instead, or cancel to change a setting?")
        reroll = box.addButton("New Random Seed", accept)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(reroll)
        return box, {reroll: REROLL_VIDEO}

    box.setInformativeText(
        "This image-to-video has two seeds — its start frame and its motion.\n"
        "Re-roll the video seed for new motion on the same frame, the image seed "
        "for a new frame with the same motion, or both."
    )
    mapping = {
        box.addButton("New Video Seed", accept): REROLL_VIDEO,
        box.addButton("New Image Seed", accept): REROLL_IMAGE,
        box.addButton("New Both Seeds", accept): REROLL_BOTH,
    }
    box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(next(iter(mapping)))  # New Video Seed — keep the frame you liked
    return box, mapping


def offer_reroll(parent, workflow, *, can_reroll_image: bool = False) -> str | None:
    """Warn that this exact config was already generated; ask which seed to re-roll.

    Returns ``REROLL_VIDEO`` / ``REROLL_IMAGE`` / ``REROLL_BOTH`` for the chosen
    re-roll, or ``None`` to cancel (also the dialog's close box). ``can_reroll_image``
    is the caller's word on whether a fresh start frame is possible — only then are
    the per-seed image choices offered.
    """
    box, mapping = _build_reroll_box(parent, workflow, can_reroll_image)
    box.exec()
    return mapping.get(box.clickedButton())
