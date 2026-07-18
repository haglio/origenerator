"""Background experimentation: propose, run, and learn from unattended
generation experiments while the GPU is otherwise idle.

* :mod:`.policy` — Qt-free brain: derive the next experiment from the gallery's
  own history, weighted by the user's review verdicts.
* :mod:`.runner` — the ambient scheduler: launch one experiment at a time, only
  when nothing else wants the GPU.
* :mod:`.gpu` — the idle probe that keeps experiments off a busy GPU (another
  app's work — e.g. Evolver's upscaler — or anything else).
"""
