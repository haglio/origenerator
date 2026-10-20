from __future__ import annotations

from tools import fix_lora_trainer


def test_a_part_is_cropped_to_a_square_twice_its_size_around_it():
    assert fix_lora_trainer.square_crop((100, 200, 160, 240), (1000, 800)) == (70, 160, 190, 280)


def test_a_crop_near_the_photos_edge_or_bigger_than_it_stays_inside_it():
    assert fix_lora_trainer.square_crop((0, 0, 60, 40), (1000, 800)) == (0, 0, 120, 120)
    assert fix_lora_trainer.square_crop((100, 100, 900, 700), (1000, 800)) == (100, 0, 900, 800)


def _option(command, name):
    return command[command.index(name) + 1]


def test_the_training_makes_an_sdxl_lora_from_the_crops_in_comfyuis_lora_folder():
    job = {"sd_scripts": "C:/sd-scripts", "base_model": "C:/models/base.safetensors",
           "output_dir": "C:/loras/fixes", "output_name": "hands 2026-10-19 0130"}

    command = fix_lora_trainer.train_command(job, "C:/work/dataset", python="py.exe")

    assert command[:2] == ["py.exe", "C:/sd-scripts/sdxl_train_network.py"]
    assert _option(command, "--pretrained_model_name_or_path") == "C:/models/base.safetensors"
    assert _option(command, "--train_data_dir") == "C:/work/dataset"
    assert _option(command, "--output_dir") == "C:/loras/fixes"
    assert _option(command, "--output_name") == "hands 2026-10-19 0130"
    assert _option(command, "--network_module") == "networks.lora"


def test_the_training_writes_its_log_as_utf8_so_a_line_in_japanese_does_not_stop_it():
    assert fix_lora_trainer.training_environment({"PATH": "C:/bin"}) == {
        "PATH": "C:/bin", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}


def test_fewer_photos_are_each_seen_more_times_and_every_photo_at_least_once():
    assert fix_lora_trainer.dataset_folder("C:/work", "hands", 10) == "C:/work/15_hands"
    assert fix_lora_trainer.dataset_folder("C:/work", "hands", 100) == "C:/work/2_hands"
    assert fix_lora_trainer.dataset_folder("C:/work", "hands", 400) == "C:/work/1_hands"
