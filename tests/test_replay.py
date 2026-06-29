from origenerator.replay import (
    apply_overrides,
    extract_output_files,
    missing_inputs,
)


def _i2v_graph():
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "old positive"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "old negative"}},
        "4": {"class_type": "KSamplerAdvanced",
              "inputs": {"noise_seed": 1, "add_noise": "enable"}},
        "5": {"class_type": "KSamplerAdvanced",
              "inputs": {"noise_seed": 0, "add_noise": "disable"}},
        "6": {"class_type": "WanImageToVideo",
              "inputs": {"positive": ["2", 0], "negative": ["3", 0],
                         "start_image": ["1", 0]}},
    }


def test_apply_overrides_sets_prompts_structurally():
    g = apply_overrides(_i2v_graph(), positive="new pos", negative="new neg")
    assert g["2"]["inputs"]["text"] == "new pos"
    assert g["3"]["inputs"]["text"] == "new neg"


def test_apply_overrides_sets_image_and_seed():
    g = apply_overrides(_i2v_graph(), seed=999, input_image="new.png")
    assert g["1"]["inputs"]["image"] == "new.png"
    assert g["4"]["inputs"]["noise_seed"] == 999       # noise-adding pass
    assert g["5"]["inputs"]["noise_seed"] == 0         # refine pass left alone


def test_apply_overrides_does_not_mutate_original():
    original = _i2v_graph()
    apply_overrides(original, positive="x", seed=5, input_image="y.png")
    assert original["2"]["inputs"]["text"] == "old positive"
    assert original["1"]["inputs"]["image"] == "old.png"
    assert original["4"]["inputs"]["noise_seed"] == 1


def test_apply_overrides_handles_wanvideo_text_encode():
    g = {
        "1": {"class_type": "WanVideoTextEncode",
              "inputs": {"positive_prompt": "p", "negative_prompt": "n"}},
        "2": {"class_type": "WanVideoSampler", "inputs": {"seed": 1}},
    }
    out = apply_overrides(g, positive="np", negative="nn", seed=42)
    assert out["1"]["inputs"]["positive_prompt"] == "np"
    assert out["1"]["inputs"]["negative_prompt"] == "nn"
    assert out["2"]["inputs"]["seed"] == 42


def test_apply_overrides_skips_absent_fields():
    # A graph with no LoadImage: an input_image override is simply ignored.
    g = {"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "t"},
               "_meta": {"title": "CLIP Text Encode (Prompt)"}}}
    out = apply_overrides(g, input_image="x.png")
    assert all(n["class_type"] != "LoadImage" for n in out.values())


def test_extract_output_files_collects_images_and_gifs():
    history = {"outputs": {
        "9": {"images": [{"filename": "a.png", "subfolder": "image", "type": "output"}]},
        "16": {"gifs": [{"filename": "b.mp4", "subfolder": "video", "type": "output"}]},
        "20": {"images": [{"filename": "c.mp4", "subfolder": "video", "type": "output"}],
               "animated": [True]},
    }}
    files = extract_output_files(history)
    names = {f["filename"] for f in files}
    assert names == {"a.png", "b.mp4", "c.mp4"}


def test_missing_inputs_flags_absent_loadimage(tmp_path):
    (tmp_path / "here.png").write_bytes(b"")
    graph = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "here.png"}},
        "2": {"class_type": "LoadImage", "inputs": {"image": "gone.png"}},
    }
    assert missing_inputs(graph, tmp_path) == ["gone.png"]
