from __future__ import annotations

from typing import NamedTuple


class Version(NamedTuple):
    path: object
    media_type: str
    label: str = ""
    points_of_interest: tuple = ()


class VersionStepper:
    def __init__(self) -> None:
        self._by_path: dict[str, list[Version]] = {}
        self._base: str | None = None
        self._index = 0
        self._stepping = False

    def arm(self, versions_by_path) -> bool:
        before = self._places()
        self._by_path = {}
        self._take(versions_by_path)
        return self._places() != before

    def add(self, versions_by_path) -> bool:
        before = self._places()
        self._take(versions_by_path)
        return self._places() != before

    def _take(self, versions_by_path) -> None:
        self._by_path.update({str(key): [Version(*version) for version in versions]
                              for key, versions in versions_by_path.items()})

    def points_of_interest(self, path) -> tuple:
        versions = self._by_path.get(str(path))
        return versions[0].points_of_interest if versions else ()

    def _places(self) -> dict[str, tuple]:
        return {key: versions[0].points_of_interest
                for key, versions in self._by_path.items()
                if versions and versions[0].points_of_interest}

    def restart(self) -> None:
        self.back_to_the_top()
        self._stepping = False

    def back_to_the_top(self) -> None:
        self._base = None
        self._index = 0

    def step(self, delta: int, *, base: str):
        base = self._base or base
        versions = self._by_path.get(base) or []
        if len(versions) <= 1:
            return None
        self._base = base
        self._stepping = True
        self._index = (self._index + delta) % len(versions)
        return versions[self._index]

    def versions(self, *, base: str) -> list[Version]:
        return self._by_path.get(self._base or base) or []

    @property
    def stepping(self) -> bool:
        return self._stepping

    def pace(self, dwell_s: int) -> int:
        return 0 if self._stepping else dwell_s

    @property
    def index(self) -> int:
        return self._index
