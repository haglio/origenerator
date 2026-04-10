from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParamDef:
    key: str
    label: str
    type: str  # "str", "int", "float", "seed", "combo", "image"
    default: Any
    options: list | None = None
    min_val: float | None = None
    max_val: float | None = None
    step: float | None = None
    multiline: bool = False


class WorkflowTemplate(ABC):
    name: str
    version: str
    display_name: str
    output_type: str  # "image" or "video"

    @abstractmethod
    def default_params(self) -> dict:
        """Return dict of param_name -> default_value."""

    @abstractmethod
    def param_definitions(self) -> list[ParamDef]:
        """Return ordered list of ParamDef for the UI form builder."""

    @abstractmethod
    def build_api_payload(self, params: dict) -> dict:
        """Build the ComfyUI API-format prompt dict from user params."""

    @abstractmethod
    def extract_output_info(self, history_data: dict) -> list[dict]:
        """Parse ComfyUI /history response to find output files."""
