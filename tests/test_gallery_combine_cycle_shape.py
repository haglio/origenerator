from __future__ import annotations

import pytest

from origenerator.gallery import combine


class _Workflow:
    def __init__(self, defaults):
        self._defaults = defaults

    def default_params(self):
        return self._defaults


@pytest.mark.parametrize("defaults", [{"frame_rate": 16}, {"frame_count": 81}, {}])
def test_a_workflow_with_no_length_or_no_rate_to_set_is_handed_back_unchanged(defaults):
    params = {"positive_prompt": "example", "frame_count": 81}

    assert combine.cycle_shaped(params, _Workflow(defaults)) is params
