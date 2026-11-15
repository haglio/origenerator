from __future__ import annotations

import json

from origenerator.db import Database, NewGeneration
from origenerator.db_requests import NewRequest
from origenerator.workflows import workflow_named
from tools import remake_request_images


def _image(db, prompt_id, seed, *, prompt="a red kite over a beach"):
    db.insert_generation(NewGeneration(
        prompt_id=prompt_id, workflow_name="sdxl_t2i", workflow_version="v1",
        positive_prompt=prompt, seed=seed,
        params_json=json.dumps({**workflow_named("sdxl_t2i").default_params(),
                                "positive_prompt": prompt, "seed": seed}),
        workflow_json="{}"))
    db.update_generation(prompt_id, status="completed", output_files=json.dumps(
        [{"filename": f"{prompt_id}_00001_.png", "subfolder": "", "type": "output"}]))


def test_the_count_says_how_many_request_images_took_the_wrong_seed_and_changes_nothing(
        tmp_path, capsys):
    db_path = tmp_path / "t.db"
    db = Database(db_path)
    _image(db, "first", 7)
    _image(db, "second", 9, prompt="two red kites over a beach")
    db.record_request(NewRequest(prompt_id="second", source_prompt_id="first", heard="two kites",
                                 asked="two kites"))
    db.set_generation_favorite("second", True)
    before = db_path.read_bytes()

    assert remake_request_images.main([], db_path=db_path) == 0

    assert capsys.readouterr().out.splitlines() == [
        "1 Request image(s) took the wrong seed, 1 of them starred",
        "0 video(s) were animated from them and 0 enhancement(s) made of them",
        "production Origenerator makes them again by itself at its next launch",
    ]
    assert db_path.read_bytes() == before
