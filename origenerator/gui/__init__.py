"""What this app draws, and the logic that belongs beside one thing drawn.

A module here serves something on screen: a widget, a controller that owns
one, or the Qt-free reading a widget is built from -- which is why
``console``, ``show_map`` and ``thumbnail_selection`` sit here with no Qt in
them at all, each answering for the widget next to it.

What does NOT belong here is the app's own machinery, however much a widget
happens to be its only caller: the session's file channels, the two device
drivers, the ambient players, the orientation key scheme and the spin-arrow
PNGs all lived here once, and importing any `gui` module dragged UDP sockets
and filesystem IPC in with it -- so a reader after this app's IPC contract had
to know to look inside the widget package to find it. They are
``origenerator.fun_time_bridge``, ``origenerator.osr2_driver``,
``origenerator.osr2_motion_driver``, ``origenerator.ambient_audio_players``,
``origenerator.orientation`` and ``origenerator.spin_arrows``, beside the rest
of the app, and ``tests/test_module_boundaries.py`` holds them there.

Imports run upward: a module here may reach the package below it, and nothing
below may reach in.
"""
