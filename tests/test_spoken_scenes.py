"""Her lines, spoken: a scene with a line renders on the speech model, hearing
the line, and the line plays over the foley in the file."""
from __future__ import annotations

import pytest

from origenerator.speech import scene_speech
from origenerator.workflows.wan22_flf2v_loop import Wan22Flf2vLoopWorkflow
from origenerator.workflows.wan22_i2v import Wan22I2vWorkflow


def _spoken_params(**overrides):
    params = dict(Wan22I2vWorkflow().default_params(), frame_count=401, scene_frames=[161, 81, 161],
                  positive_prompt="she waves\n---\nshe turns\n---\nshe speaks",
                  scene_lines=["Come in.", "", "Sit."], audio_seed=5, noise_seed=100)
    params.update(overrides)
    return params


def _nodes(payload, class_type):
    return [node for node in payload.values() if node["class_type"] == class_type]


def _writer_audio(payload):
    (writer,) = _nodes(payload, "CreateVideo")
    return payload[writer["inputs"]["audio"][0]]


def _model_chain(payload, node):
    """The class names from a sampler's model input back to its loader."""
    chain = []
    ref = node["inputs"]["model"]
    while ref is not None:
        node = payload[ref[0]]
        chain.append(node["class_type"])
        ref = node["inputs"].get("model")
    return chain


def test_a_scene_with_a_line_renders_on_the_speech_model_hearing_that_line():
    # Scenes one and three speak, so their segments render on the speech
    # model, each hearing its scene's line for its own frames; scene two says
    # nothing and renders on the two experts as it always has.
    params = _spoken_params()
    payload = Wan22I2vWorkflow().build_api_payload(params)
    spoken = _nodes(payload, "WanSoundImageToVideo")
    assert [seg["inputs"]["length"] for seg in spoken] == [161, 161]
    assert [seg["inputs"]["length"] for seg in _nodes(payload, "WanImageToVideo")] == [81]
    files = [scene.file for scene in scene_speech(params) if scene is not None]
    for seg, file in zip(spoken, files):
        heard = payload[seg["inputs"]["audio_encoder_output"][0]]
        assert heard["class_type"] == "AudioEncoderEncode"
        encoder = payload[heard["inputs"]["audio_encoder"][0]]
        assert encoder["inputs"]["audio_encoder_name"] == params["audio_encoder_name"]
        cut = payload[heard["inputs"]["audio"][0]]
        assert cut["class_type"] == "TrimAudioDuration"
        assert (cut["inputs"]["start_index"], cut["inputs"]["duration"]) == (0.0, pytest.approx(161 / 16))
        line = payload[cut["inputs"]["audio"][0]]
        assert (line["class_type"], line["inputs"]["audio"]) == ("LoadAudio", file)
    # its own scene's text, and the size every segment shares
    assert payload[spoken[1]["inputs"]["positive"][0]]["inputs"]["text"] == "she speaks"
    assert spoken[0]["inputs"]["width"] == _nodes(payload, "WanImageToVideo")[0]["inputs"]["width"]


def test_a_speaking_segment_samples_the_speech_model_under_its_lightning_lora():
    payload = Wan22I2vWorkflow().build_api_payload(_spoken_params())
    samplers = _nodes(payload, "KSampler")
    assert [s["inputs"]["seed"] for s in samplers] == [100, 102]
    for sampler in samplers:
        assert (sampler["inputs"]["steps"], sampler["inputs"]["cfg"]) == (4, 1.0)
        assert (sampler["inputs"]["sampler_name"], sampler["inputs"]["scheduler"]) == ("uni_pc", "simple")
        assert _model_chain(payload, sampler) == ["ModelSamplingSD3", "LoraLoaderModelOnly", "UNETLoader"]
        shifted = payload[sampler["inputs"]["model"][0]]
        lora = payload[shifted["inputs"]["model"][0]]
        loader = payload[lora["inputs"]["model"][0]]
        assert loader["inputs"]["unet_name"] == "wan2.2_s2v_14B_fp8_scaled.safetensors"
        assert "lightx2v" in lora["inputs"]["lora_name"]
    # the experts still sample the silent scene, on their own models
    assert len(_nodes(payload, "KSamplerAdvanced")) == 2


def test_a_speaking_segment_starts_on_the_frame_before_it_and_carries_its_motion():
    # The speech model takes the last frame as its reference and, given the
    # frames before it, continues their motion rather than starting still.
    payload = Wan22I2vWorkflow().build_api_payload(_spoken_params())
    first, third = _nodes(payload, "WanSoundImageToVideo")
    assert first["inputs"]["ref_image"] == ["20", 0] and "ref_motion" not in first["inputs"]
    last = payload[third["inputs"]["ref_image"][0]]
    assert (last["class_type"], last["inputs"]["batch_index"]) == ("ImageFromBatch", 80)
    assert third["inputs"]["ref_motion"] == last["inputs"]["image"]
    assert payload[third["inputs"]["ref_motion"][0]]["class_type"] == "VAEDecode"


def test_a_spoken_scene_longer_than_one_window_hears_its_line_window_by_window():
    params = _spoken_params(frame_count=241, scene_frames=[241], scene_lines=["A long line."])
    payload = Wan22I2vWorkflow().build_api_payload(params)
    spoken = _nodes(payload, "WanSoundImageToVideo")
    assert [seg["inputs"]["length"] for seg in spoken] == [161, 81]
    windows = [payload[payload[seg["inputs"]["audio_encoder_output"][0]]["inputs"]["audio"][0]]["inputs"]
               for seg in spoken]
    assert [(w["start_index"], w["duration"]) for w in windows] == [
        (0.0, pytest.approx(161 / 16)), (pytest.approx(160 / 16), pytest.approx(81 / 16))]
    # both windows read the one file the scene's line is
    assert len({payload[w["audio"][0]]["inputs"]["audio"] for w in windows}) == 1
    # and the second carries the first's motion
    assert spoken[1]["inputs"]["ref_motion"] == payload[spoken[1]["inputs"]["ref_image"][0]]["inputs"]["image"]


def test_the_writer_hears_her_line_where_she_speaks_and_the_foley_where_she_does_not():
    # The foley scores what it sees, and shown a woman talking it scores a
    # garbled voice under hers; so the file's track is her line for a scene
    # that speaks, and the foley's own stretch for one that does not: scene
    # one's line cut to the frames it adds, the foley from 10 s for scene two,
    # scene three's whole line, end to end.
    payload = Wan22I2vWorkflow().build_api_payload(_spoken_params())
    join = _writer_audio(payload)
    assert join["class_type"] == "AudioConcat"
    assert payload[join["inputs"]["audio2"][0]]["class_type"] == "LoadAudio"
    earlier = payload[join["inputs"]["audio1"][0]]
    assert earlier["class_type"] == "AudioConcat"
    ambience = payload[earlier["inputs"]["audio2"][0]]
    assert ambience["class_type"] == "TrimAudioDuration"
    assert (ambience["inputs"]["start_index"], ambience["inputs"]["duration"]) == (
        pytest.approx(160 / 16), pytest.approx(80 / 16))
    assert payload[ambience["inputs"]["audio"][0]]["class_type"] == "HunyuanFoleySampler"
    first = payload[earlier["inputs"]["audio1"][0]]
    assert (first["class_type"], first["inputs"]["duration"]) == ("TrimAudioDuration", pytest.approx(160 / 16))
    assert payload[first["inputs"]["audio"][0]]["class_type"] == "LoadAudio"
    assert "AudioMerge" not in {node["class_type"] for node in payload.values()}


def test_a_story_without_lines_keeps_the_graph_it_always_had():
    wf = Wan22I2vWorkflow()
    payload = wf.build_api_payload(dict(
        wf.default_params(), frame_count=401, scene_frames=[161, 81, 161],
        positive_prompt="a\n---\nb\n---\nc", scene_lines=["", " ", ""]))
    kinds = {node["class_type"] for node in payload.values()}
    assert not kinds & {"WanSoundImageToVideo", "LoadAudio", "AudioMerge", "AudioEncoderLoader", "KSampler"}
    assert _writer_audio(payload)["class_type"] == "HunyuanFoleySampler"


def test_the_speech_slot_offers_only_the_speech_model_and_the_experts_never_do(installed_models):
    installed_models.add("diffusion_models", "speaker.safetensors", arch="wan_s2v")
    installed_models.add("diffusion_models", "expert_high.safetensors", arch="wan")
    installed_models.add("diffusion_models", "expert_low.safetensors", arch="wan")
    by_key = {pd.key: pd for pd in Wan22I2vWorkflow().param_definitions()}
    assert "speaker.safetensors" in by_key["unet_s2v"].options
    assert "expert_high.safetensors" not in by_key["unet_s2v"].options
    assert "speaker.safetensors" not in by_key["unet_high"].options
    assert "speaker.safetensors" not in by_key["unet_low"].options


def test_a_speaking_segment_samples_at_the_steps_and_strength_the_recipe_sets():
    # The speaking pass is sampled on its own terms, not the experts': its
    # steps and prompt strength are the recipe's, so a run can trade the
    # lightning LoRA's four unguided steps for real guidance.
    payload = Wan22I2vWorkflow().build_api_payload(
        _spoken_params(speech_steps=24, speech_cfg=5.5, steps=20, cfg_high=3.5, cfg_low=3.5))
    for sampler in _nodes(payload, "KSampler"):
        assert (sampler["inputs"]["steps"], sampler["inputs"]["cfg"]) == (24, 5.5)
    # the experts' own numbers are untouched by it
    for sampler in _nodes(payload, "KSamplerAdvanced"):
        assert (sampler["inputs"]["steps"], sampler["inputs"]["cfg"]) == (20, 3.5)


def test_the_speech_lora_can_be_bypassed_so_the_model_hears_a_real_prompt_strength():
    # The lightning LoRA is distilled for no guidance, so raising the speech
    # prompt strength means taking it off: "None" adds no loader and the
    # speaking samplers run the speech model bare, exactly as the expert slots
    # bypass theirs. The experts' own LoRAs are untouched.
    from origenerator.workflows.model_files import NO_LORA

    wf = Wan22I2vWorkflow()
    on = wf.build_api_payload(_spoken_params())
    off = wf.build_api_payload(_spoken_params(lora_speech=NO_LORA, speech_cfg=5.0, speech_steps=24))
    assert _model_chain(on, _nodes(on, "KSampler")[0]) == [
        "ModelSamplingSD3", "LoraLoaderModelOnly", "UNETLoader"]
    assert _model_chain(off, _nodes(off, "KSampler")[0]) == ["ModelSamplingSD3", "UNETLoader"]
    assert len(_nodes(off, "LoraLoaderModelOnly")) == len(_nodes(on, "LoraLoaderModelOnly")) - 1
    speech_loader = off[off[_nodes(off, "KSampler")[0]["inputs"]["model"][0]]["inputs"]["model"][0]]
    assert speech_loader["inputs"]["unet_name"] == off["30"]["inputs"]["unet_name"]


def test_the_speech_lora_pulls_at_the_strength_the_recipe_sets():
    payload = Wan22I2vWorkflow().build_api_payload(
        _spoken_params(lora_speech="quieter.safetensors", lora_strength_speech=0.35))
    (lora,) = [n for n in _nodes(payload, "LoraLoaderModelOnly")
               if n["inputs"]["lora_name"] == "quieter.safetensors"]
    assert lora["inputs"]["strength_model"] == 0.35


def test_the_speaking_pass_exposes_its_steps_strength_and_lora_as_fields():
    # All four are editable rows on the form, the LoRA led by "None" like every
    # other LoRA picker, and they start at the lightning settings the pass has
    # always run -- so an untouched recipe builds the graph it always did.
    from origenerator.workflows.model_files import NO_LORA

    wf = Wan22I2vWorkflow()
    by_key = {pd.key: pd for pd in wf.param_definitions()}
    defaults = wf.default_params()
    assert by_key["speech_steps"].type == "int" and defaults["speech_steps"] == 4
    assert by_key["speech_cfg"].type == "float" and defaults["speech_cfg"] == 1.0
    assert by_key["lora_speech"].type == "combo" and by_key["lora_speech"].options[0] == NO_LORA
    assert by_key["lora_speech"].default == defaults["lora_speech"]
    assert "lightx2v" in defaults["lora_speech"]
    assert by_key["lora_strength_speech"].type == "float" and defaults["lora_strength_speech"] == 1.0


def test_the_speech_lora_slot_takes_either_wan_family_and_neither_expert_half(installed_models):
    # The speech model is one model, not half an expert pair, and what runs on
    # it today is a WAN t2v LoRA -- so the slot offers both families and filters
    # on neither high nor low.
    installed_models.add("loras", "lightning_high.safetensors", arch="wan", lora=True)
    installed_models.add("loras", "lightning_low.safetensors", arch="wan", lora=True)
    installed_models.add("loras", "talker.safetensors", arch="wan_s2v", lora=True)
    installed_models.add("loras", "flux_thing.safetensors", arch="flux", lora=True)
    options = {pd.key: pd for pd in Wan22I2vWorkflow().param_definitions()}["lora_speech"].options
    assert {"lightning_high.safetensors", "lightning_low.safetensors",
            "talker.safetensors"} <= set(options)
    assert "flux_thing.safetensors" not in options


def test_the_voice_is_a_preset_or_a_sample_and_only_the_one_shot_workflow_speaks():
    by_key = {pd.key: pd for pd in Wan22I2vWorkflow().param_definitions()}
    assert by_key["voice"].type == "combo" and by_key["voice"].options[0] == by_key["voice"].default
    assert by_key["voice_sample"].type == "audio" and by_key["voice_sample"].browse_dir is not None
    assert by_key["voice"].options[-1] == "Custom voice (a recording)"
    assert by_key["voice_sample_text"].type == "str" and by_key["voice_sample_text"].multiline
    loop = Wan22Flf2vLoopWorkflow()
    assert "scene_lines" not in loop.default_params()
    assert "scene_lines" not in {pd.key for pd in loop.param_definitions()}
