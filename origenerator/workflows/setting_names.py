from __future__ import annotations

from functools import cache

from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.base import ParamDef, WorkflowTemplate


@cache
def _definitions_of(workflow: WorkflowTemplate) -> dict[str, ParamDef]:
    return {pd.key: pd for pd in workflow.param_definitions()}


def setting_name(key: str) -> str:
    return next((definitions[key].label
                 for definitions in map(_definitions_of, WORKFLOW_REGISTRY.values())
                 if key in definitions), key)


def setting_definition(key: str, workflow_name: str | None) -> ParamDef | None:
    workflow = WORKFLOW_REGISTRY.get(workflow_name or "")
    return _definitions_of(workflow).get(key) if workflow is not None else None
