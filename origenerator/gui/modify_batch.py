from __future__ import annotations

from dataclasses import dataclass

from origenerator.generation_config import ConfigSnapshot, configs_match

CAPTION = "Modify batch (all seeds)"
_TIP = (
    "Run all {count} images in this folder again, each with its own seed and "
    "the prompt as you have rewritten it, landing them in a new folder."
)
_TIP_ONE = (
    "Run this folder's one image again with its own seed and the prompt as "
    "you have rewritten it, landing it in a new folder."
)
_TITLE = "Modify batch {folder}"


@dataclass(frozen=True)
class ModifyBatch:
    folder_key: str
    label: str
    count: int
    opened_on: ConfigSnapshot

    def title(self) -> str:
        return _TITLE.format(folder=self.label)

    def caption(self) -> str:
        return CAPTION

    def tooltip(self) -> str:
        return (_TIP_ONE if self.count == 1
                else _TIP.format(count=self.count))

    def is_unchanged(self, config: ConfigSnapshot) -> bool:
        return configs_match(self.opened_on, config)
