"""The shared "already generated" dialog.

Re-running a workflow whose seed isn't randomized re-creates a byte-identical
output, so both places that can launch such a run — the Generate tab and the
gallery's image+video combine — warn first and offer a fresh seed. One dialog,
one wording, so the two paths stay in step.
"""

from PyQt6.QtWidgets import QMessageBox


def offer_reroll(parent, workflow) -> bool:
    """Warn that this exact config was already generated; ask whether to re-roll.

    Re-running it would just re-create an identical output, so the only useful
    choices are a fresh random seed or backing out to change a setting. Returns
    ``True`` to re-roll with a new random seed, ``False`` to cancel (also the
    dialog's close box).
    """
    media = workflow.output_type if workflow.output_type in ("image", "video") else "output"
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Already generated")
    box.setText(
        f"You've already generated this exact {media} — same settings and "
        f"the same seed.\nRunning it again will just re-create an identical "
        f"{media}."
    )
    box.setInformativeText("Generate a new random seed instead, or cancel to change a setting?")
    reroll = box.addButton("New Random Seed", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(reroll)
    box.exec()
    return box.clickedButton() is reroll
