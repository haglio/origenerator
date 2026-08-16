import json
import struct

import pytest

from origenerator.workflows import model_arch
from origenerator.workflows.model_arch import FLUX, LTX, QWEN, SD15, SDXL, WAN


def _write(path, tensor_names):
    header = json.dumps(
        {name: {"dtype": "F16", "shape": [1], "data_offsets": [0, 2]} for name in tensor_names}
    ).encode()
    path.write_bytes(struct.pack("<Q", len(header)) + header + b"\x00\x00")
    return path


# The tensor-name shapes the installed models actually have, one case per
# collision the signature order in model_arch._arch_from exists to settle.
# Fabricated names in the real layouts — no file contents were copied.
ARCH_CASES = [
    # SDXL: as a checkpoint (`conditioner.`), as a bare UNet in
    # diffusion_models (`label_emb`, no text encoder at all), as a diffusers
    # ControlNet (`add_embedding`), and as a LoRA (the te1/te2 pair).
    (SDXL, ["conditioner.embedders.0.transformer.x", "model.diffusion_model.input_blocks.0.y"]),
    (SDXL, ["model.diffusion_model.label_emb.0.0.weight", "model.diffusion_model.input_blocks.0.y"]),
    (SDXL, ["add_embedding.linear_1.weight", "controlnet_cond_embedding.conv_in.weight"]),
    (SDXL, ["lora_te1_text_model_encoder_layers_0_mlp_fc1.lora_down.weight",
            "lora_te2_text_model_encoder_layers_0_mlp_fc1.lora_down.weight"]),
    # SD1.5: single text encoder, and the original ControlNet layout, which is
    # SD1.5's only because none of SDXL's extra conditioning showed up.
    (SD15, ["cond_stage_model.transformer.x", "model.diffusion_model.input_blocks.0.y"]),
    (SD15, ["lora_te_text_model_encoder_layers_0_mlp_fc1.lora_down.weight",
            "lora_unet_down_blocks_0_attn.lora_down.weight"]),
    (SD15, ["control_model.zero_convs.0.0.weight", "control_model.input_hint_block.0.weight"]),
    # Flux, in all three forms it ships in.
    (FLUX, ["double_blocks.0.img_attn.qkv.weight", "single_blocks.0.linear1.weight"]),
    (FLUX, ["lora_unet_double_blocks_0_img_attn_qkv.lora_down.weight"]),
    (FLUX, ["transformer.transformer_blocks.0.attn.to_q.lora_A.weight",
            "transformer.single_transformer_blocks.0.attn.to_q.lora_A.weight"]),
    # LTX and Qwen are both `transformer_blocks` models; LTX is asked first, and
    # a Qwen LoRA has nothing but transformer_blocks to go on.
    (LTX, ["patchify_proj.weight", "transformer_blocks.0.attn1.to_q.weight"]),
    (QWEN, ["transformer_blocks.0.attn.to_q.weight", "txt_norm.weight", "time_text_embed.x"]),
    (QWEN, ["transformer_blocks.0.attn.to_q.lora_A.weight"]),
    # WAN, bare and wrapped and as either LoRA form.
    (WAN, ["blocks.0.self_attn.q.weight", "patch_embedding.weight", "time_projection.1.weight"]),
    (WAN, ["model.diffusion_model.blocks.0.self_attn.q.weight",
           "model.diffusion_model.head.head.weight"]),
    (WAN, ["blocks.0.cross_attn.k.lora_A.weight"]),
    (WAN, ["lora_unet_blocks_0_cross_attn_k.lora_down.weight"]),
    (WAN, ["vace_blocks.0.before_proj.weight", "vace_patch_embedding.weight"]),
]


@pytest.mark.parametrize("expected,tensor_names", ARCH_CASES)
def test_reads_the_architecture_off_the_tensor_names(tmp_path, expected, tensor_names):
    assert model_arch.describe(_write(tmp_path / "m.safetensors", tensor_names)).arch == expected


def test_an_unrecognized_file_reads_as_unknown_rather_than_wrong(tmp_path):
    # "We could not tell" is its own answer, and every picker keeps those: a
    # listed option that errors costs one submit, where a working model missing
    # from the dropdown gives the user no symptom to act on.
    unknown = _write(tmp_path / "future.safetensors", ["some.brand.new.layout.weight"])
    assert model_arch.describe(unknown).arch is None

    (tmp_path / "old.ckpt").write_bytes(b"pickled weights, no readable index")
    assert model_arch.describe(tmp_path / "old.ckpt").arch is None

    (tmp_path / "truncated.safetensors").write_bytes(struct.pack("<Q", 4096) + b"{}")
    assert model_arch.describe(tmp_path / "truncated.safetensors").arch is None

    (tmp_path / "empty.safetensors").write_bytes(b"")
    assert model_arch.describe(tmp_path / "empty.safetensors").arch is None

    # A wild length prefix is not a header to read — honoring it would pull the
    # whole file into memory to answer a question about its index.
    (tmp_path / "wild.safetensors").write_bytes(struct.pack("<Q", 1 << 40) + b"{}")
    assert model_arch.describe(tmp_path / "wild.safetensors").arch is None


def test_tells_a_lora_from_the_model_it_was_trained_against(tmp_path):
    # Both folders hold the wrong kind: a WAN LoRA sits in diffusion_models, and
    # a full SD1.5 checkpoint sits in loras. Neither loads in the other's slot.
    lora = _write(tmp_path / "l.safetensors", ["blocks.0.cross_attn.k.lora_A.weight"])
    assert model_arch.describe(lora).is_lora
    kohya = _write(tmp_path / "k.safetensors", ["lora_unet_blocks_0_ffn_0.lora_down.weight"])
    assert model_arch.describe(kohya).is_lora
    model = _write(tmp_path / "m.safetensors", ["blocks.0.self_attn.q.weight"])
    assert not model_arch.describe(model).is_lora


def test_reads_the_wan_expert_off_the_filename(tmp_path):
    # Which of WAN 2.2's two experts a file is lives only in its name — nothing
    # inside the file distinguishes them. Invented names, in the spellings the
    # published LoRAs actually use: separators, casing and camel humps all vary.
    def expert(name):
        return model_arch.describe(_write(tmp_path / name, ["blocks.0.x"])).expert

    assert expert("wan2.2_t2v_high_noise_14B.safetensors") == "high"
    assert expert("wan22-example-54epoc-low-abcd.safetensors") == "low"
    assert expert("EXAMPLELORA_22_HIGH_e149.safetensors") == "high"
    assert expert("23High noise-Example Aesthetics.safetensors") == "high"
    assert expert("SampleLoRA_LowNoise_Wan2.2.safetensors") == "low"
    # camelCase, where the marker has a letter immediately before it
    assert expert("exampleRemixT2VI2V_t2vHighV20.safetensors") == "high"
    assert expert("sampleMixWan2214BI2V_t2vLowV30.safetensors") == "low"


def test_a_word_merely_containing_high_or_low_is_not_a_marker(tmp_path):
    # Ordinary words swallow these letters — "yellow", "slow", "flow" — and a
    # plain substring search would file every one of them under low-noise and
    # drop them from the High picker. Installed LoRAs really are named this way.
    def expert(name):
        return model_arch.describe(_write(tmp_path / name, ["blocks.0.x"])).expert

    assert expert("wan_i2v_slowmo_pan_v1.2.safetensors") is None
    assert expert("wan_yellow_light_v3.safetensors") is None
    assert expert("WAN-2.2-I2V-Yellow-Filter-HIGH-v1.safetensors") == "high"
    # Naming both, or neither, claims nothing usable — such a file stays offered
    # in either slot rather than being guessed into one.
    assert expert("wan2.2_high_and_low_merged.safetensors") is None
    assert expert("wan2.1_t2v_14B_fp16.safetensors") is None


def test_a_sharded_download_is_not_a_selectable_model(tmp_path):
    # Each part holds a slice of the tensors and none loads alone, so listing
    # them offers six broken picks in place of one model that isn't selectable.
    shard = _write(tmp_path / "diffusion_pytorch_model-00002-of-00006.safetensors",
                   ["blocks.7.self_attn.q.weight"])
    assert model_arch.describe(shard).is_shard
    whole = _write(tmp_path / "diffusion_pytorch_model.safetensors", ["blocks.0.x"])
    assert not model_arch.describe(whole).is_shard


def test_reads_a_gguf_index_past_its_metadata(tmp_path):
    # The quantized Flux models are GGUF, whose tensor names sit after a
    # variable-length metadata block — so reaching them means stepping over
    # every typed value in that block, not seeking a fixed offset.
    def kv(key, text):
        return (struct.pack("<Q", len(key)) + key + struct.pack("<I", 8)
                + struct.pack("<Q", len(text)) + text)

    def tensor(name):
        return (struct.pack("<Q", len(name)) + name + struct.pack("<I", 1)
                + struct.pack("<Q", 16) + struct.pack("<I", 0) + struct.pack("<Q", 0))

    names = [b"double_blocks.0.img_attn.qkv.weight", b"single_blocks.0.linear1.weight"]
    path = tmp_path / "flux-Q8_0.gguf"
    path.write_bytes(
        b"GGUF" + struct.pack("<I", 3) + struct.pack("<QQ", len(names), 2)
        + kv(b"general.architecture", b"flux")
        + kv(b"general.name", b"whatever")
        + b"".join(tensor(name) for name in names)
    )
    assert model_arch.describe(path).arch == FLUX


def test_a_malformed_gguf_reads_as_unknown(tmp_path):
    path = tmp_path / "broken.gguf"
    path.write_bytes(b"GGUF" + struct.pack("<I", 3) + struct.pack("<QQ", 900, 900))
    assert model_arch.describe(path).arch is None
