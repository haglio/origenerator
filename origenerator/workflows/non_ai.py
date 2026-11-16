from __future__ import annotations

from origenerator.media import MediaType
from origenerator.workflows.base import ParamDef, ParamType
from origenerator.workflows.outside import MadeElsewhereWorkflow, outside_source

_PREFIX = "non-ai:"
FOLDER_KEY = "folder"


def non_ai_workflow(folder: str) -> str:
    return _PREFIX + folder


def non_ai_folder(workflow_name: str | None) -> str | None:
    if workflow_name and workflow_name.startswith(_PREFIX):
        return workflow_name.removeprefix(_PREFIX)
    return None


FOLDER_KINDS = ("non_ai", "site", "workflow")


def folder_kind(workflow_name: str | None) -> str:
    if non_ai_folder(workflow_name) is not None:
        return "non_ai"
    return "site" if outside_source(workflow_name) is not None else "workflow"


class NonAiWorkflow(MadeElsewhereWorkflow):
    version = "non_ai"
    why_it_cannot_be_made_again = "A Non-AI video wasn't generated, so it can't be made again"
    output_type = MediaType.VIDEO

    def __init__(self, folder: str):
        self.name = non_ai_workflow(folder)
        self.display_name = folder

    def param_definitions(self) -> list[ParamDef]:
        return [ParamDef(FOLDER_KEY, "Folder", ParamType.STR, "")]
