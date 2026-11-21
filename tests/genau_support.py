from __future__ import annotations

from pathlib import Path

LOOPING = "wan22_flf2v_loop"


def looping_row(prompt_id: str, *, workflow: str = LOOPING, shape: str = "portrait",
                favorite: bool = False, source: str = "generated", flipped: bool = False) -> dict:
    return {"prompt_id": prompt_id, "workflow_name": workflow, "shape": shape,
            "starred": favorite, "source": source, "genau_flipped": int(flipped)}


class FlicksLibrary:
    def __init__(self, rows: list[dict], *, folder: Path = Path("C:/made/up"),
                 enhanced: frozenset[str] = frozenset()) -> None:
        self.recent_rows = rows
        self.folder = folder
        self._enhanced = enhanced
        self.slides_asked = 0

    def is_enhanced(self, row: dict) -> bool:
        return row["prompt_id"] in self._enhanced

    def file_of(self, prompt_id: str) -> Path:
        return self.folder / f"{prompt_id}.mp4"

    def slides_of(self, rows) -> list[tuple]:
        self.slides_asked += 1
        return [(self.file_of(row["prompt_id"]), "video", row["prompt_id"], None) for row in rows]


class HeardBeat:
    def __init__(self) -> None:
        self.said: list[str] = []

    def drive(self, on: bool) -> None:
        self.said.append(f"drive {int(on)}")

    def bpm(self, bpm: float) -> None:
        self.said.append(f"bpm {bpm:g}")

    def sync(self) -> None:
        self.said.append("sync")

    def close(self) -> None:
        self.said.append("closed")
