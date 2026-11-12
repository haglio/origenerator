from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from origenerator.db_combine_video_uses import CombineVideoUseStore
from origenerator.db_connection import SqliteFile
from origenerator.db_custom_collections import CustomCollectionStore
from origenerator.db_folder_meta import FolderMetaStore
from origenerator.db_generations import GenerationStore, NewGeneration
from origenerator.db_item_numbers import ItemNumberStore
from origenerator.db_requests import NewRequest, RequestStore
from origenerator.db_salvage import salvage_if_malformed
from origenerator.db_schema import SCHEMA, create
from origenerator.db_seed_uses import NewSeedUse, SeedUseStore
from origenerator.db_trash import TrashStore


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        salvage_if_malformed(self.path, SCHEMA)
        file = SqliteFile(self.path)
        with file.connect() as conn:
            create(conn)
        self.generations = GenerationStore(file)
        self.deletions = TrashStore(file)
        self.requests = RequestStore(file)
        self.seed_uses = SeedUseStore(file)
        self.combine_video_uses = CombineVideoUseStore(file)
        self.folder_meta = FolderMetaStore(file)
        self.custom_collections = CustomCollectionStore(file)
        self.item_numbers = ItemNumberStore(file)

    def insert_generation(self, new: NewGeneration):
        return self.generations.insert_generation(new)

    def update_generation(self, prompt_id: str, **fields):
        return self.generations.update_generation(prompt_id, **fields)

    def set_workflow_name(self, prompt_id: str, workflow_name: str):
        return self.generations.set_workflow_name(prompt_id, workflow_name)

    def set_params_json(self, prompt_id: str, params_json: str):
        return self.generations.set_params_json(prompt_id, params_json)

    def set_params_and_workflow(self, prompt_id: str, *, params_json: str, workflow_json: str):
        return self.generations.set_params_and_workflow(
            prompt_id, params_json=params_json, workflow_json=workflow_json)

    def set_settings_source(self, prompt_id: str, *, category: str | None = None,
                            video_prompt_id: str | None = None):
        return self.generations.set_settings_source(
            prompt_id, category=category, video_prompt_id=video_prompt_id)

    def set_enhance_target(self, prompt_id: str, source_prompt_id: str | None):
        return self.generations.set_enhance_target(prompt_id, source_prompt_id)

    def fill_in(self, column, values):
        self.generations.fill_in(column, values)

    def set_recorded_fields(self, rows: list[dict]):
        return self.generations.set_recorded_fields(rows)

    def set_generation_favorite(self, prompt_id: str, favorite: bool):
        return self.generations.set_generation_favorite(prompt_id, favorite)

    def set_experiment_verdict(self, prompt_id: str, verdict: str | None):
        return self.generations.set_experiment_verdict(prompt_id, verdict)

    def say_why_it_cannot_be_made_again(self, prompt_id: str, reason: str):
        return self.generations.say_why_it_cannot_be_made_again(prompt_id, reason)

    def set_image_state(self, prompt_id: str, state: str | None):
        return self.generations.set_image_state(prompt_id, state)

    def set_action(self, prompt_id: str, action: str | None):
        return self.generations.set_action(prompt_id, action)

    def set_actions(self, prompt_id: str, side: str, item_actions):
        return self.generations.set_actions(prompt_id, side, item_actions)

    def set_many_actions(self, side: str, actions_by_id: dict):
        return self.generations.set_many_actions(side, actions_by_id)

    def set_shielded(self, prompt_id: str, shielded: bool):
        return self.generations.set_shielded(prompt_id, shielded)

    def set_source(self, prompt_id: str, source: str):
        return self.generations.set_source(prompt_id, source)

    def set_evolver_upscale(self, prompt_id: str, path: str, upscaled_at: str | None):
        return self.generations.set_evolver_upscale(prompt_id, path, upscaled_at)

    def set_watch_counts(self, prompt_id: str, counts: dict):
        return self.generations.set_watch_counts(prompt_id, counts)

    def set_library_record(self, prompt_id: str, **fields):
        return self.generations.set_library_record(prompt_id, **fields)

    def mark_evolver_exported(self, prompt_id: str):
        return self.generations.mark_evolver_exported(prompt_id)

    def mark_evolver_unsent(self, prompt_id: str):
        return self.generations.mark_evolver_unsent(prompt_id)

    def mark_genau_exported(self, prompt_id: str):
        return self.generations.mark_genau_exported(prompt_id)

    def mark_genau_unsent(self, prompt_id: str):
        return self.generations.mark_genau_unsent(prompt_id)

    def mark_genau_requested(self, prompt_id: str):
        return self.generations.mark_genau_requested(prompt_id)

    def recent_durations(self, workflow_name: str, limit: int = 10) -> list[float]:
        return self.generations.recent_durations(workflow_name, limit)

    def completed_without_duration(self) -> list[dict]:
        return self.generations.completed_without_duration()

    def highest_id_issued(self) -> int:
        return self.generations.highest_id_issued()

    def delete_generation(self, prompt_id: str):
        return self.generations.delete_generation(prompt_id)

    def restore_generation(self, row: dict):
        return self.generations.restore_generation(row)

    def insert_rows(self, rows: list[dict]):
        return self.generations.insert_rows(rows)
    def library_paths(self) -> set[str]:
        return self.generations.library_paths()

    def output_files_of_every_row(self) -> list[str]:
        return self.generations.output_files_of_every_row()

    def get_generation(self, prompt_id: str) -> dict | None:
        return self.generations.get_generation(prompt_id)

    def list_generations(self) -> list[dict]:
        return self.generations.list_generations()

    def rows_left_out(self) -> list[dict]:
        return self.generations.rows_left_out()

    def library_version(self) -> int:
        return self.generations.library_version()

    def when_changed(self, told):
        return self.generations.when_changed(told)

    def rows_made_by(self, workflow_name: str) -> list[dict]:
        return self.generations.rows_made_by(workflow_name)

    def seed_history_rows(self) -> list[dict]:
        return self.generations.seed_history_rows()

    def custom_combinations(self) -> list[dict]:
        return self.generations.custom_combinations()

    def record_seed_use(self, use: NewSeedUse) -> None:
        return self.seed_uses.record_seed_use(use)

    def list_seed_uses(self) -> list[dict]:
        return self.seed_uses.list_seed_uses()

    def record_combine_video_use(self, intent: str, video_prompt_id: str,
                                 generation_prompt_id: str | None = None) -> None:
        return self.combine_video_uses.record_combine_video_use(
            intent, video_prompt_id, generation_prompt_id)

    def repoint_combine_video_uses(self, gone: str, stays: str) -> None:
        return self.combine_video_uses.repoint_combine_video_uses(gone, stays)

    def list_combine_video_uses(self) -> list[dict]:
        return self.combine_video_uses.list_combine_video_uses()

    def record_trashed(self, prompt_id: str, row: dict, batch: dict, *,
                        deleted_at: str | None = None):
        return self.deletions.record_trashed(prompt_id, row, batch, deleted_at=deleted_at)

    def list_trashed(self) -> list[dict]:
        return self.deletions.list_trashed()

    def get_trashed(self, prompt_id: str) -> dict | None:
        return self.deletions.get_trashed(prompt_id)

    def forget_trashed(self, prompt_id: str):
        return self.deletions.forget_trashed(prompt_id)

    def trashed_file(self, original: Path) -> Path | None:
        return self.deletions.trashed_file(original)

    def trashed_library_paths(self) -> set[str]:
        return self.deletions.trashed_library_paths()

    def list_item_numbers(self) -> dict[str, tuple[str, int]]:
        return self.item_numbers.list_item_numbers()

    def record_item_numbers(self, numbers: Mapping[str, tuple[str, int]]):
        return self.item_numbers.record_item_numbers(numbers)

    def forget_item_numbers(self, prompt_ids: list[str]):
        return self.item_numbers.forget_item_numbers(prompt_ids)

    def record_request(self, request: NewRequest):
        return self.requests.record_request(request)

    def list_requests(self) -> list[dict]:
        return self.requests.list_requests()

    def requests_about(self, source_prompt_id: str) -> list[dict]:
        return self.requests.requests_about(source_prompt_id)

    def get_request(self, prompt_id: str) -> dict | None:
        return self.requests.get_request(prompt_id)

    def folder_meta_map(self) -> dict[str, dict]:
        return self.folder_meta.folder_meta_map()

    def set_folder_favorite(self, folder_key: str, favorite: bool):
        return self.folder_meta.set_folder_favorite(folder_key, favorite)

    def folder_meta_full(self) -> list[dict]:
        return self.folder_meta.folder_meta_full()

    def upsert_folder_meta(self, folder_key: str, *, custom_name: str | None,
                           favorite: bool, level: str | None, ref_prompt_id: str | None):
        return self.folder_meta.upsert_folder_meta(
            folder_key, custom_name=custom_name, favorite=favorite,
            level=level, ref_prompt_id=ref_prompt_id)

    def delete_folder_meta(self, folder_key: str):
        return self.folder_meta.delete_folder_meta(folder_key)

    def create_custom_collection(self, name: str, folder_id: int | None = None,
                             shape: str | None = None) -> int:
        return self.custom_collections.create_custom_collection(name, folder_id, shape)

    def set_custom_collection_shape(self, folder_id: int, shape: str):
        return self.custom_collections.set_custom_collection_shape(folder_id, shape)

    def delete_custom_collection(self, folder_id: int):
        return self.custom_collections.delete_custom_collection(folder_id)

    def add_folders_to_custom_collection(self, folder_id: int, folders: list[tuple]):
        return self.custom_collections.add_folders_to_custom_collection(folder_id, folders)

    def add_items_to_custom_collection(self, folder_id: int, prompt_ids: list[str]):
        return self.custom_collections.add_items_to_custom_collection(folder_id, prompt_ids)

    def remove_items_from_custom_collection(self, folder_id: int, prompt_ids: list[str]):
        return self.custom_collections.remove_items_from_custom_collection(folder_id, prompt_ids)

    def repoint_item_in_custom_collections(self, old_prompt_id: str, new_prompt_id: str):
        return self.custom_collections.repoint_item_in_custom_collections(old_prompt_id, new_prompt_id)

    def remove_folder_from_custom_collection(self, folder_id: int, folder_key: str):
        return self.custom_collections.remove_folder_from_custom_collection(folder_id, folder_key)

    def list_custom_collections(self) -> list[dict]:
        return self.custom_collections.list_custom_collections()

    def folders_in_custom_collections(self) -> list[dict]:
        return self.custom_collections.folders_in_custom_collections()

    def repoint_folder_in_custom_collection(self, folder_id: int, old_key: str, new_key: str,
                                        *, level: str | None, ref_prompt_id: str | None):
        return self.custom_collections.repoint_folder_in_custom_collection(
            folder_id, old_key, new_key, level=level, ref_prompt_id=ref_prompt_id)

    def stamp_folder_in_custom_collection(self, folder_id: int, folder_key: str,
                                      *, level: str | None, ref_prompt_id: str | None):
        return self.custom_collections.stamp_folder_in_custom_collection(
            folder_id, folder_key, level=level, ref_prompt_id=ref_prompt_id)
