from __future__ import annotations

from origenerator.workflows import WORKFLOW_REGISTRY


def _classes(payload: dict) -> set[str]:
    return {node["class_type"] for node in payload.values()}


def _enhance_payload(**settings) -> dict:
    workflow = WORKFLOW_REGISTRY["image_enhance"]
    return workflow.build_api_payload(
        dict(workflow.default_params(), input_image="pick.png", **settings))


def test_no_redraw_saves_exactly_what_the_upscaler_gave_without_a_model():
    payload = _enhance_payload(enhance_denoise=0.0)

    assert _classes(payload) == {"LoadImage", "UpscaleModelLoader", "ImageUpscaleWithModel",
                                 "ImageScaleBy", "SaveImage"}


def test_the_upscaler_alone_is_saved_from_a_forms_own_enhance_at_no_redraw_too():
    workflow = WORKFLOW_REGISTRY["krea2_t2i"]
    payload = workflow.build_api_payload(dict(workflow.default_params(), enhance=True,
                                              enhance_denoise=0.0))

    assert payload[payload[workflow.output_node_id]["inputs"]["images"][0]]["class_type"] == "ImageScaleBy"
