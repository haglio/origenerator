from __future__ import annotations

import json
import sys
from typing import TextIO

from origenerator.voice.commands import hosted_phrases
from origenerator.voice.dictation import LEAD_WORDS, request_bias


def main(out: TextIO) -> None:
    json.dump({"phrases": sorted(hosted_phrases()), "openers": list(LEAD_WORDS),
               "speech_hint": request_bias()}, out)


if __name__ == "__main__":
    main(sys.stdout)
