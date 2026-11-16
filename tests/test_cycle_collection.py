from __future__ import annotations

import gc

from shared_ui.gui_thread_collection import GuiThreadCollection


def test_the_suite_collects_cycles_on_the_gui_thread_as_the_app_does(qapp):
    assert not gc.isenabled()
    assert qapp.findChild(GuiThreadCollection) is not None
