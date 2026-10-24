from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

PICTURES = "image"
SCRIPTS = "funscript"
AUDIO = "audio"
WORKING_FOLDER = "origenerator"


@dataclass(frozen=True)
class OutputPlaces:
    comfyui: Path
    pictures: Path
    videos: Path
    scripts: Path
    audio: Path

    @classmethod
    def in_one_folder(cls, folder: Path) -> OutputPlaces:
        folder = Path(folder)
        return cls(comfyui=folder, pictures=folder / PICTURES, videos=folder,
                   scripts=folder / SCRIPTS, audio=folder / AUDIO)

    @classmethod
    def from_settings(cls, settings: dict, *, comfyui_dir: Path) -> OutputPlaces:
        comfyui = Path(settings.get("comfyui_output_dir") or Path(comfyui_dir) / "output")
        pictures, videos = (settings.get("origenerator_pictures_dir"),
                            settings.get("origenerator_videos_dir"))
        if not (pictures and videos):
            return cls.in_one_folder(comfyui)
        videos = Path(videos)
        return cls(comfyui=comfyui, pictures=Path(pictures), videos=videos,
                   scripts=Path(settings.get("origenerator_scripts_dir") or videos / SCRIPTS),
                   audio=Path(settings.get("origenerator_audio_dir") or videos / AUDIO))

    def folder(self, subfolder: str) -> Path:
        parts = PurePosixPath(subfolder.replace("\\", "/")).parts
        if not parts:
            return self.comfyui
        kind, rest = parts[0], parts[1:]
        named = self._named()
        home = named[kind] if kind in named else self.videos / kind
        return home.joinpath(*rest)

    def file(self, named: str) -> Path:
        *folders, name = PurePosixPath(named.replace("\\", "/")).parts
        return self.folder("/".join(folders)) / name

    def subfolder_of(self, folder: Path) -> str | None:
        for kind, home in self._named().items():
            inside = _parts_within(folder, home)
            if inside is not None:
                return "/".join((kind, *inside))
        inside = _parts_within(folder, self.videos)
        if inside:
            return "/".join(inside)
        return "" if _parts_within(folder, self.comfyui) == () else None

    def video_folders(self) -> list[Path]:
        named = self._named().values()
        return [child for child in folders_in(self.videos)
                if child not in named and child != self.working]

    def files(self) -> Iterator[tuple[Path, str]]:
        for home in [*self._named().values(), *self.video_folders()]:
            for folder, names in files_under(home):
                subfolder = self.subfolder_of(folder)
                yield from ((folder / name, subfolder) for name in names)
        yield from ((path, "") for path in _files_in(self.comfyui))

    @property
    def working(self) -> Path:
        return self.comfyui / WORKING_FOLDER

    def run(self, prompt_id: str) -> Path:
        return self.working / prompt_id

    def keeps_outputs_in_comfyuis_folder(self) -> bool:
        return any(_parts_within(home, self.comfyui) is not None
                   for home in (self.videos, *self._named().values()))

    def _named(self) -> dict[str, Path]:
        return {PICTURES: self.pictures, SCRIPTS: self.scripts, AUDIO: self.audio}


def _parts_within(folder: Path, home: Path) -> tuple[str, ...] | None:
    try:
        return Path(folder).relative_to(home).parts
    except ValueError:
        return None


def folders_in(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(child for child in folder.iterdir()
                  if child.is_dir() and not os.path.isjunction(child))


def _files_in(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(child for child in folder.iterdir() if child.is_file())


def files_under(top: Path) -> Iterator[tuple[Path, list[str]]]:
    for dirpath, dirnames, filenames in os.walk(top):
        dirnames[:] = sorted(name for name in dirnames
                             if not os.path.isjunction(os.path.join(dirpath, name)))
        yield Path(dirpath), sorted(filenames)
