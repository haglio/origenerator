def test_gui_suite_renders_offscreen(qapp):
    """Agents run this suite on every commit; it must render offscreen so no Qt
    windows flash onto the screen. Guards conftest's QT_QPA_PLATFORM setting
    against being removed or set too late (after the QApplication is created)."""
    assert qapp.platformName() == "offscreen"
