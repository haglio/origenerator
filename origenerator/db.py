"""The app's database: every table of it, under one object.

`Database` is a facade. Each table's queries live in their own module —
:mod:`origenerator.db_generations`, :mod:`~origenerator.db_deletions`,
:mod:`~origenerator.db_requests`, :mod:`~origenerator.db_folder_meta`,
:mod:`~origenerator.db_custom_folders`, :mod:`~origenerator.db_branch_curation`
— and this holds one of each, forwarding the method names ~700 call sites across
this package, the gui package and the suite already spell.

**Hand a unit the store it needs, not this.** Every consumer here uses a
disjoint slice: recovery and gallery_actions touch only `deletions`, reconcile
only `folder_meta` and `custom_folder_members`, branch_session only
`branch_curation` and `generations`. A store is whole on its own, so a unit that
takes one can be given a narrow fake and a change to one table stops being a
change to the file 24 modules import.

The schema is :mod:`origenerator.db_schema` and the connection policy
:mod:`origenerator.db_connection`; tests/test_db_schema.py holds the file on disk
as a snapshot, because evolver reads it.
"""
from pathlib import Path

from origenerator.db_branch_curation import BranchCurationStore
from origenerator.db_connection import SqliteFile
from origenerator.db_custom_folders import CustomFolderStore
from origenerator.db_deletions import DeletionStore
from origenerator.db_folder_meta import FolderMetaStore
from origenerator.db_generations import GenerationStore
from origenerator.db_requests import RequestStore
from origenerator.db_salvage import salvage_if_malformed
from origenerator.db_schema import SCHEMA, create


class Database:
    """One store per table, and the method names that predate the split."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        salvage_if_malformed(self.path, SCHEMA)
        file = SqliteFile(self.path)
        with file.connect() as conn:
            create(conn)
        self.generations = GenerationStore(file)
        self.deletions = DeletionStore(file)
        self.requests = RequestStore(file)
        self.folder_meta = FolderMetaStore(file)
        self.custom_folders = CustomFolderStore(file)
        self.branch_curation = BranchCurationStore(file)

    # --- generations (see origenerator.db_generations) -----------------------

    def insert_generation(self, *, prompt_id: str, workflow_name: str,
                          workflow_version: str, positive_prompt: str | None = None,
                          negative_prompt: str | None = None, seed: int | None = None,
                          params_json: str, workflow_json: str,
                          source: str = "generated"):
        return self.generations.insert_generation(
            prompt_id=prompt_id, workflow_name=workflow_name,
            workflow_version=workflow_version, positive_prompt=positive_prompt,
            negative_prompt=negative_prompt, seed=seed, params_json=params_json,
            workflow_json=workflow_json, source=source)

    def update_generation(self, prompt_id: str, **fields):
        return self.generations.update_generation(prompt_id, **fields)

    def set_workflow_name(self, prompt_id: str, workflow_name: str):
        return self.generations.set_workflow_name(prompt_id, workflow_name)

    def set_params_json(self, prompt_id: str, params_json: str):
        return self.generations.set_params_json(prompt_id, params_json)

    def set_recipe_source(self, prompt_id: str, *, category: str | None = None,
                          video_prompt_id: str | None = None):
        return self.generations.set_recipe_source(
            prompt_id, category=category, video_prompt_id=video_prompt_id)

    def set_generation_starred(self, prompt_id: str, starred: bool):
        return self.generations.set_generation_starred(prompt_id, starred)

    def set_experiment_verdict(self, prompt_id: str, verdict: str | None):
        return self.generations.set_experiment_verdict(prompt_id, verdict)

    def mark_evolver_exported(self, prompt_id: str):
        return self.generations.mark_evolver_exported(prompt_id)

    def mark_genau_exported(self, prompt_id: str):
        return self.generations.mark_genau_exported(prompt_id)

    def mark_genau_requested(self, prompt_id: str):
        return self.generations.mark_genau_requested(prompt_id)

    def recent_durations(self, workflow_name: str, limit: int = 10) -> list[float]:
        return self.generations.recent_durations(workflow_name, limit)

    def completed_without_duration(self) -> list[dict]:
        return self.generations.completed_without_duration()

    def delete_generation(self, prompt_id: str):
        return self.generations.delete_generation(prompt_id)

    def restore_generation(self, row: dict):
        return self.generations.restore_generation(row)

    def get_generation(self, prompt_id: str) -> dict | None:
        return self.generations.get_generation(prompt_id)

    def list_generations(self) -> list[dict]:
        return self.generations.list_generations()

    # --- the recovery bin (see origenerator.db_deletions) --------------------

    def record_deletion(self, prompt_id: str, row: dict, batch: dict):
        return self.deletions.record_deletion(prompt_id, row, batch)

    def list_deletions(self) -> list[dict]:
        return self.deletions.list_deletions()

    def get_deletion(self, prompt_id: str) -> dict | None:
        return self.deletions.get_deletion(prompt_id)

    def forget_deletion(self, prompt_id: str):
        return self.deletions.forget_deletion(prompt_id)

    # --- spoken requests (see origenerator.db_requests) ----------------------

    def record_request(self, *, prompt_id: str, source_prompt_id: str, heard: str,
                       term: str | None = None, polarity: str | None = None,
                       action: str | None = None, old_positive: str = "",
                       old_negative: str = "", new_positive: str = "",
                       new_negative: str = ""):
        return self.requests.record_request(
            prompt_id=prompt_id, source_prompt_id=source_prompt_id, heard=heard,
            term=term, polarity=polarity, action=action,
            old_positive=old_positive, old_negative=old_negative,
            new_positive=new_positive, new_negative=new_negative)

    def list_requests(self) -> list[dict]:
        return self.requests.list_requests()

    def get_request(self, prompt_id: str) -> dict | None:
        return self.requests.get_request(prompt_id)




    # --- folder metadata (see origenerator.db_folder_meta) ------------------

    def folder_meta_map(self) -> dict[str, dict]:
        return self.folder_meta.folder_meta_map()

    def rename_folder(self, folder_key: str, custom_name: str | None):
        return self.folder_meta.rename_folder(folder_key, custom_name)

    def set_folder_starred(self, folder_key: str, starred: bool):
        return self.folder_meta.set_folder_starred(folder_key, starred)

    def folder_meta_full(self) -> list[dict]:
        return self.folder_meta.folder_meta_full()

    def upsert_folder_meta(self, folder_key: str, *, custom_name: str | None,
                           starred: bool, level: str | None, ref_prompt_id: str | None):
        return self.folder_meta.upsert_folder_meta(
            folder_key, custom_name=custom_name, starred=starred,
            level=level, ref_prompt_id=ref_prompt_id)

    def delete_folder_meta(self, folder_key: str):
        return self.folder_meta.delete_folder_meta(folder_key)

    # --- branch-session curation (see origenerator.db_branch_curation) -------

    def branch_curation_state(self, branch: str) -> dict | None:
        return self.branch_curation.branch_curation_state(branch)

    def set_branch_curation_state(self, branch: str, state: dict):
        return self.branch_curation.set_branch_curation_state(branch, state)



    # --- custom folders (see origenerator.db_custom_folders) ----------------

    def create_custom_folder(self, name: str, folder_id: int | None = None) -> int:
        return self.custom_folders.create_custom_folder(name, folder_id)

    def rename_custom_folder(self, folder_id: int, name: str):
        return self.custom_folders.rename_custom_folder(folder_id, name)

    def delete_custom_folder(self, folder_id: int):
        return self.custom_folders.delete_custom_folder(folder_id)

    def add_custom_folder_members(self, folder_id: int, members: list[tuple]):
        return self.custom_folders.add_custom_folder_members(folder_id, members)

    def remove_custom_folder_member(self, folder_id: int, folder_key: str):
        return self.custom_folders.remove_custom_folder_member(folder_id, folder_key)

    def list_custom_folders(self) -> list[dict]:
        return self.custom_folders.list_custom_folders()

    def custom_folder_members_full(self) -> list[dict]:
        return self.custom_folders.custom_folder_members_full()

    def repoint_custom_folder_member(self, folder_id: int, old_key: str, new_key: str,
                                     *, level: str | None, ref_prompt_id: str | None):
        return self.custom_folders.repoint_custom_folder_member(
            folder_id, old_key, new_key, level=level, ref_prompt_id=ref_prompt_id)

    def stamp_custom_folder_member(self, folder_id: int, folder_key: str,
                                   *, level: str | None, ref_prompt_id: str | None):
        return self.custom_folders.stamp_custom_folder_member(
            folder_id, folder_key, level=level, ref_prompt_id=ref_prompt_id)
