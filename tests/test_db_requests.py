from origenerator.db import Database, NewGeneration, NewRequest


def test_recording_a_request_again_for_one_generation_replaces_the_earlier_record(tmp_path):
    db = Database(tmp_path / "test.db")
    db.record_request(NewRequest(prompt_id="gen-1", source_prompt_id="src-1", heard="Request, no hat, over."))

    db.record_request(NewRequest(prompt_id="gen-1", source_prompt_id="src-1", heard="Request, no scarf, over."))

    assert [r["heard"] for r in db.list_requests()] == ["Request, no scarf, over."]


def test_a_folder_wide_rewrite_is_recorded_with_no_single_term(tmp_path):
    db = Database(tmp_path / "test.db")
    db.record_request(NewRequest(prompt_id="gen-1", source_prompt_id="src-1", heard="", asked="two cats"))

    record = db.get_request("gen-1")

    assert record["heard"] == ""
    assert record["term"] is None
    assert record["polarity"] is None
    assert record["action"] is None


def test_requests_made_in_one_second_list_in_the_order_they_were_recorded(tmp_path):
    db = Database(tmp_path / "test.db")
    for prompt_id in ("gen-1", "gen-2", "gen-3"):
        db.record_request(NewRequest(prompt_id=prompt_id, source_prompt_id="src-1", heard=""))

    assert [r["prompt_id"] for r in db.requests_about("src-1")] == ["gen-3", "gen-2", "gen-1"]
    assert [r["prompt_id"] for r in db.list_requests()] == ["gen-3", "gen-2", "gen-1"]


def test_a_request_outlives_the_generation_it_queued(tmp_path):
    db = Database(tmp_path / "test.db")
    db.insert_generation(NewGeneration(
        prompt_id="gen-1", workflow_name="sdxl_t2i", workflow_version="v1",
        params_json="{}", workflow_json="{}"))
    db.record_request(NewRequest(prompt_id="gen-1", source_prompt_id="src-1", heard=""))

    db.delete_generation("gen-1")

    assert db.get_request("gen-1") is not None
