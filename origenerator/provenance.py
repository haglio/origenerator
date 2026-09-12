"""What made each generation, kept on its row so a later change can find
everything made before it and remake it.

The block is the family's stamp (:mod:`app_support.provenance`) with the
workflow as its recipe, plus one key of this app's own saying how the recipe
version came to be known.
"""
from __future__ import annotations

from app_support import provenance as family

APP = "origenerator"
BASIS = "recipe_version_basis"
RECORDED = "recorded"


def at_launch(workflow) -> dict:
    return {**family.stamp(APP, anchor=__file__, recipe=workflow.name,
                           recipe_version=workflow.version),
            BASIS: RECORDED}
