from origenerator.comfy_graph import (
    clip_prompt_nodes,
    conditioning_node,
    dual_sampler_model_files,
    follow,
    graph_model_params,
    input_image_name,
)


def test_follow_resolves_link_else_none():
    graph = {"2": {"class_type": "CLIPTextEncode", "inputs": {"text": "hi"}}}
    assert follow(graph, ["2", 0])["inputs"]["text"] == "hi"
    assert follow(graph, None) is None
    assert follow(graph, "2") is None  # not a link


def test_conditioning_node_finds_wan_node():
    graph = {
        "1": {"class_type": "CLIPTextEncode", "inputs": {}},
        "2": {"class_type": "WanFirstLastFrameToVideo", "inputs": {}},
    }
    assert conditioning_node(graph) is graph["2"]
    assert conditioning_node({"1": {"class_type": "KSampler", "inputs": {}}}) is None


def test_clip_prompt_nodes_structural_via_conditioning():
    graph = {
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "pos"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "neg"}},
        "5": {"class_type": "WanImageToVideo",
              "inputs": {"positive": ["2", 0], "negative": ["3", 0]}},
    }
    pos, neg = clip_prompt_nodes(graph)
    assert pos["inputs"]["text"] == "pos"
    assert neg["inputs"]["text"] == "neg"


def test_clip_prompt_nodes_falls_back_to_titles():
    graph = {
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "pos"},
              "_meta": {"title": "CLIP Text Encode (Positive Prompt)"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "neg"},
              "_meta": {"title": "CLIP Text Encode (Negative Prompt)"}},
    }
    pos, neg = clip_prompt_nodes(graph)
    assert pos["inputs"]["text"] == "pos"
    assert neg["inputs"]["text"] == "neg"


def test_dual_sampler_model_files_pairs_high_low_unet_and_lora():
    # A WAN i2v model chain: each stage's sampler -> ModelSamplingSD3 -> LoRA
    # loader -> UNET loader. High is the noise-adding stage, low the other.
    graph = {
        "4": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan_high.safetensors"}},
        "5": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan_low.safetensors"}},
        "6": {"class_type": "LoraLoaderModelOnly",
              "inputs": {"model": ["4", 0], "lora_name": "styleA_high.safetensors"}},
        "7": {"class_type": "LoraLoaderModelOnly",
              "inputs": {"model": ["5", 0], "lora_name": "styleA_low.safetensors"}},
        "8": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["6", 0]}},
        "9": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["7", 0]}},
        "15": {"class_type": "KSamplerAdvanced",
               "inputs": {"model": ["8", 0], "add_noise": "enable"}},
        "16": {"class_type": "KSamplerAdvanced",
               "inputs": {"model": ["9", 0], "add_noise": "disable"}},
    }
    assert dual_sampler_model_files(graph) == {
        "unet_high": "wan_high.safetensors",
        "unet_low": "wan_low.safetensors",
        "lora_high": "styleA_high.safetensors",
        "lora_low": "styleA_low.safetensors",
    }


def test_dual_sampler_model_files_returns_only_unets_without_lora():
    # WAN t2i has the dual samplers but no LoRA loaders in the model chain.
    graph = {
        "3": {"class_type": "UNETLoader", "inputs": {"unet_name": "t2v_high.safetensors"}},
        "4": {"class_type": "UNETLoader", "inputs": {"unet_name": "t2v_low.safetensors"}},
        "5": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["3", 0]}},
        "6": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["4", 0]}},
        "10": {"class_type": "KSamplerAdvanced",
               "inputs": {"model": ["5", 0], "add_noise": "enable"}},
        "11": {"class_type": "KSamplerAdvanced",
               "inputs": {"model": ["6", 0], "add_noise": "disable"}},
    }
    assert dual_sampler_model_files(graph) == {
        "unet_high": "t2v_high.safetensors",
        "unet_low": "t2v_low.safetensors",
    }


def test_dual_sampler_model_files_empty_without_advanced_samplers():
    # A plain KSampler graph (SDXL) has no high/low split to read.
    graph = {"5": {"class_type": "KSampler", "inputs": {"model": ["1", 0]}}}
    assert dual_sampler_model_files(graph) == {}


def test_graph_model_params_reads_sdxl_checkpoint():
    graph = {"1": {"class_type": "CheckpointLoaderSimple",
                   "inputs": {"ckpt_name": "reapony_v80.safetensors"}}}
    assert graph_model_params(graph) == {"checkpoint": "reapony_v80.safetensors"}


def test_graph_model_params_reads_flux_gguf_unet():
    # Flux loads its diffusion model via UnetLoaderGGUF; the gallery groups Flux
    # runs by this "unet" value, so it must be pulled out of the graph.
    graph = {
        "1": {"class_type": "UnetLoaderGGUF",
              "inputs": {"unet_name": "ultrarealFineTune_v4_fp16.gguf"}},
        "8": {"class_type": "KSampler", "inputs": {"model": ["1", 0]}},
    }
    assert graph_model_params(graph) == {"unet": "ultrarealFineTune_v4_fp16.gguf"}


def test_graph_model_params_reads_wan_dual_sampler_unets():
    graph = {
        "3": {"class_type": "UNETLoader", "inputs": {"unet_name": "t2v_high.safetensors"}},
        "4": {"class_type": "UNETLoader", "inputs": {"unet_name": "t2v_low.safetensors"}},
        "10": {"class_type": "KSamplerAdvanced",
               "inputs": {"model": ["3", 0], "add_noise": "enable"}},
        "11": {"class_type": "KSamplerAdvanced",
               "inputs": {"model": ["4", 0], "add_noise": "disable"}},
    }
    assert graph_model_params(graph) == {
        "unet_high": "t2v_high.safetensors",
        "unet_low": "t2v_low.safetensors",
    }


def test_graph_model_params_empty_when_no_model_loaders():
    assert graph_model_params({"5": {"class_type": "KSampler", "inputs": {}}}) == {}


def test_input_image_name_reads_the_loadimage_filename():
    # i2v/flf2v graphs start from a LoadImage; its filename is the source frame
    # the gallery links back to.
    graph = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "sdxl_t2i_00022_.png"}},
        "5": {"class_type": "WanFirstLastFrameToVideo", "inputs": {"start_image": ["1", 0]}},
    }
    assert input_image_name(graph) == "sdxl_t2i_00022_.png"


def test_input_image_name_none_without_a_string_source():
    # No LoadImage, or one whose image is a wired link rather than a filename,
    # names no source image.
    assert input_image_name({"5": {"class_type": "KSampler", "inputs": {}}}) is None
    linked = {"1": {"class_type": "LoadImage", "inputs": {"image": ["9", 0]}}}
    assert input_image_name(linked) is None
