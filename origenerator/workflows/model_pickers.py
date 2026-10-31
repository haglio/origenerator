from __future__ import annotations

from origenerator.workflows.base import ParamDef, ParamType
from origenerator.workflows.model_files import list_model_files


def model_picker(key: str, label: str, default: str, folder: str, *, accepts,
                 expert: str | None = None) -> ParamDef:
    return ParamDef(key, label, ParamType.COMBO, default, folder=folder,
                    options=list_model_files(folder, [default], accepts=accepts, expert=expert))
