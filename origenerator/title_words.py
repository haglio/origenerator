from __future__ import annotations

import re

_EXPLAINED = (
    (re.compile(r"\bRaw\b"), "Raw: the model as its makers released it, before the training that "
                             "makes a Turbo version fast. It takes about 50 steps an image, "
                             "where Turbo takes 8."),
    (re.compile(r"\bTurbo\b"), "Turbo: trained further to finish an image in about 8 steps, several "
                               "times faster than the model it was trained from."),
    (re.compile(r"\[dev\]"), "[dev]: the version of FLUX.1 that Black Forest Labs gives away for "
                             "personal use. Their paid version is [pro]."),
    (re.compile(r"\bno Lightning\b"), "No Lightning: Lightning is a speed-up that makes a video in 4 "
                                      "steps instead of about 20, and this version leaves it out."),
    (re.compile(r"\bKijai\b"), "Kijai: this copy was made for ComfyUI by Kijai, who keeps ComfyUI's "
                               "add-on for Wan. The version after the name is Kijai's."),
    (re.compile(r"Pony"), "Pony: built on Pony Diffusion, an SDXL model that follows short lists of "
                          "tags in the prompt."),
    (re.compile(r"\bI2V\b"), "I2V: image to video. It animates a starting image."),
    (re.compile(r"\bS2V\b"), "S2V: sound to video. It moves a person's lips to a sound."),
    (re.compile(r"\b14B\b"), "14B: the model is made of 14 billion numbers. Wan 2.2 also comes in a "
                             "smaller 5B."),
    (re.compile(r"\bFine-Tune\b", re.IGNORECASE), "Fine-tune: a model someone trained further, on "
                                                  "images of their choosing."),
)


def explained(title: str) -> list[str]:
    found = [(match.start(), text) for pattern, text in _EXPLAINED
             if (match := pattern.search(title)) is not None]
    return [text for _start, text in sorted(found)]
