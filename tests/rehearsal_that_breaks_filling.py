from __future__ import annotations

import sys

from origenerator import hosted_rehearsal

if __name__ == "__main__":
    hosted_rehearsal.away_from_his_library()
    from origenerator.gui.gallery_view import GalleryView

    def an_invented_fault(_view, shape: str) -> None:
        raise TypeError(f"an invented fault filling the {shape} Satellite")

    GalleryView.fill_the_region = an_invented_fault
    raise SystemExit(hosted_rehearsal.main(sys.argv[1:]))
