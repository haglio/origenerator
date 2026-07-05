"""The gallery's Inspect tab: an editable generate panel over the inspect sidebar.

Tab 0 of the info pane. It stacks, top to bottom:

- the selection's title and typical-time estimate,
- the one shared preview (an image/video, a live re-roll frame, or this tab's own
  generation frames — whoever wrote last),
- an editable :class:`GenerateConfigPanel` (workflow + params + Generate), so you
  can tweak the browsed generation's settings and run a new one right here,
- the read-only metadata sidebar, the "Animated in" strip, and Send-to-Evolver.

The embedded generate panel shares this tab's preview and the info pane's
one-at-a-time run queue, but has no per-tab history strip (the gallery browser is
its history). The metadata/animated/evolver widgets and the preview are exposed as
attributes so the gallery's :class:`InfoPaneController` drives them exactly as it
drove the old read-only inspect page — only now the form sits above them.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gui.animated_strip import AnimatedVideoStrip
from origenerator.gui.generate_config_panel import GenerateConfigPanel
from origenerator.gui.metadata_panel import MetadataPanel
from origenerator.gui.preview_widget import PreviewWidget


class InspectPanel(QWidget):
    """The editable Inspect tab: an embedded generate panel plus the inspect sidebar."""

    def __init__(self, client: ComfyUIClient | None, db: Database, *, queue,
                 parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(8, 8, 8, 8)  # matches the gallery's other pane margins

        self.meta_title = QLabel("Select a generation")
        self.meta_title.setWordWrap(True)
        box.addWidget(self.meta_title)

        self.estimate_label = QLabel()
        self.estimate_label.setObjectName("estimateLabel")
        self.estimate_label.setWordWrap(True)
        box.addWidget(self.estimate_label)

        self.preview = PreviewWidget()
        box.addWidget(self.preview, 3)

        # The editable generate controls: workflow + params + Generate. It shares
        # the one preview above and (via the queue) the one-at-a-time run order, and
        # keeps no strip of its own. Its own estimate is hidden — the inspect
        # estimate above stands in — to avoid two "Typical time" lines.
        self.config = GenerateConfigPanel(
            client, db, queue=queue, preview=self.preview, show_strip=False
        )
        self.config._estimate_label.hide()
        box.addWidget(self.config, 2)

        self.meta_panel = MetadataPanel()
        box.addWidget(self.meta_panel, 2)

        self.animated_strip = AnimatedVideoStrip()
        box.addWidget(self.animated_strip)

        self.evolver_btn = QPushButton("Send to Evolver")
        self.evolver_btn.setToolTip(
            "Copy this video into Evolver's inbox for sorting and upscaling."
        )
        self.evolver_btn.hide()  # shown only for a video selection
        box.addWidget(self.evolver_btn)
