from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime

from PIL import Image

from origenerator.completion import mark_generation_completed
from origenerator.gallery.output import output_file_path
from origenerator.gallery.signatures import parse_params
from origenerator.generation_state import GenerationSource, GenerationStatus
from origenerator.library_filing import file_into_library
from origenerator.media import MediaType
from origenerator.output_places import IMAGES, OutputFolders
from origenerator.outside_videos import Made as Recorded
from origenerator.outside_videos import made_at, recorded_fields
from origenerator.site_generation import Made
from origenerator.thumbnail import generate_thumbnail
from origenerator.workflows.outside import outside_source

KINDS = {"WEBP": ".webp", "PNG": ".png", "JPEG": ".jpg"}


def begin(db, workflow_name: str, params: dict, *, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    prompt_id = str(uuid.uuid4())
    recorded = recorded_fields(GenerationSource.OUTSIDE, workflow_name, params,
                               (made_at(Recorded(), now), now), action=None)
    db.insert_rows([{**recorded, "completed_at": None, "prompt_id": prompt_id,
                     "workflow_version": "outside", "workflow_json": "{}",
                     "status": GenerationStatus.RUNNING}])
    return prompt_id


def take_in(db, prompt_id: str, made: Made, image: bytes, folders: OutputFolders, *,
            now: datetime | None = None) -> bool:
    row = db.get_generation(prompt_id)
    if row is None:
        return False
    now = now or datetime.now(UTC)
    places, thumb_dir = folders
    waiting = places.run(prompt_id) / IMAGES
    waiting.mkdir(parents=True, exist_ok=True)
    name = f"{outside_source(row['workflow_name'])}_image_00001_{kind_of(image)}"
    (waiting / name).write_bytes(image)
    files = file_into_library(
        [{"filename": name, "subfolder": waiting.relative_to(places.comfyui).as_posix(),
          "type": "output"}], places, prompt_id)
    thumb_dir.mkdir(parents=True, exist_ok=True)
    thumbnail = generate_thumbnail(output_file_path(files[0], places), MediaType.IMAGE, thumb_dir,
                                   name=prompt_id)
    params = {**parse_params(row.get("params_json")), **({"seed": made.seed} if made.seed else {})}
    db.set_recorded_fields([{"prompt_id": prompt_id, **recorded_fields(
        GenerationSource.OUTSIDE, row["workflow_name"], params, (row["created_at"], now),
        action=row.get("action"))}])
    mark_generation_completed(db, prompt_id, files, str(thumbnail), None)
    return True


def give_up(db, prompt_id: str, why: str) -> None:
    if db.get_generation(prompt_id) is not None:
        db.update_generation(prompt_id, status=GenerationStatus.ERROR, error_message=why)


def kind_of(image: bytes) -> str:
    with Image.open(io.BytesIO(image)) as read:
        kind = KINDS.get(read.format)
    if kind is None:
        raise OSError(f"a site sent a {read.format} file, which is no kind of image kept here")
    return kind

