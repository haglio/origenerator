from origenerator.paths import ensure_shared_ui_on_path

# Make shared_ui importable for tests regardless of checkout depth.
ensure_shared_ui_on_path()
