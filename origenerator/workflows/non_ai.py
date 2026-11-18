from __future__ import annotations

from origenerator.display_names import in_parentheses, shown_name
from origenerator.media import MediaType
from origenerator.workflows.base import ParamDef, ParamType
from origenerator.workflows.outside import MadeElsewhereWorkflow, outside_source

_PREFIX = "non-ai:"
FOLDER_KEY = "folder"
TITLE_KEY = "title"
FOLDER_PARTS_IN_A_NAME = 2
OTHER = "other"


def non_ai_workflow(folder: str) -> str:
    return _PREFIX + folder


def non_ai_folder(workflow_name: str | None) -> str | None:
    if workflow_name and workflow_name.startswith(_PREFIX):
        return workflow_name.removeprefix(_PREFIX)
    return None


def shown_folder(folder: str) -> str:
    first, _space, rest = folder.partition(" ")
    shown = in_parentheses() if first == OTHER else first[:1].upper() + first[1:]
    return f"{shown} {rest}".rstrip()


FOLDER_KINDS = ("non_ai", "site", "workflow")


def folder_kind(workflow_name: str | None) -> str:
    if non_ai_folder(workflow_name) is not None:
        return "non_ai"
    return "site" if outside_source(workflow_name) is not None else "workflow"


class NonAiWorkflow(MadeElsewhereWorkflow):
    version = "non_ai"
    why_it_cannot_be_made_again = "A Non-AI video wasn't generated, so it can't be made again"
    why_it_has_no_settings = "This video wasn't generated, so it has no generation settings."
    output_type = MediaType.VIDEO

    def __init__(self, folder: str):
        self.name = non_ai_workflow(folder)
        self._folder = folder

    @property
    def display_name(self) -> str:
        return shown_name(self.name, otherwise=shown_folder(self._folder))

    def param_definitions(self) -> list[ParamDef]:
        return [ParamDef(FOLDER_KEY, "Folder", ParamType.STR, "")]
