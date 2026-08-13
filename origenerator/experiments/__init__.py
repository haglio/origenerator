"""Background experimentation: propose, run, and learn from unattended
generation experiments — the ones that fill the stretch when the app is closed.

* :mod:`.policy` — Qt-free brain: derive the next experiment from the gallery's
  own history, weighted by the user's review verdicts.
* :mod:`.background` — hand ComfyUI a batch of them as the app closes, and clear
  whatever is left of that batch when it opens again.
"""
