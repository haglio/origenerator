from __future__ import annotations

from origenerator.workflows.base import ParamDef, ParamType
from origenerator.workflows.model_files import list_model_files


def model_dropdown(key: str, label: str, default: str, folder: str, **offered) -> ParamDef:
    return ParamDef(key, label, ParamType.DROPDOWN, default, folder=folder,
                    options=list_model_files(folder, [default], **offered))
