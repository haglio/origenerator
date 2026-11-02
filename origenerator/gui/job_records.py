from __future__ import annotations

import json

from origenerator import provenance
from origenerator.db import NewGeneration, NewSeedUse
from origenerator.generation_state import GenerationSource
from origenerator.seed_history import SeedUseKind, output_size
from origenerator.thumbnail import frame_thumbnail


def insert_generation_row(db, job):
    params = job.params
    db.insert_generation(NewGeneration(
        prompt_id=job.prompt_id,
        workflow_name=job.workflow.name,
        workflow_version=job.workflow.version,
        positive_prompt=params.get("positive_prompt", ""),
        negative_prompt=params.get("negative_prompt", ""),
        seed=params.get("seed"),
        params_json=json.dumps(params),
        workflow_json=json.dumps(job.payload),
        source=job.source,
        provenance=json.dumps(provenance.at_launch(job.workflow)),
        shielded=job.shielded,
    ))


def record_unfinished_run(db, job, kind: SeedUseKind) -> None:
    if job.source != GenerationSource.GENERATED:
        return
    frame = job.last_preview
    thumbnail = (frame_thumbnail(frame, job.thumb_dir, name=f"{job.prompt_id}_{kind}")
                 if frame else None)
    width, height = output_size(job.workflow.name, job.params) or (None, None)
    for key in job.workflow.seed_keys():
        if job.params.get(key) is not None:
            db.record_seed_use(NewSeedUse(kind=kind, seed_key=key, seed=int(job.params[key]),
                               media_type=job.workflow.output_type, width=width, height=height,
                               thumbnail_path=str(thumbnail) if thumbnail else None))


def record_canceled_run(db, job) -> None:
    record_unfinished_run(db, job, SeedUseKind.CANCELED)


def record_failed_run(db, job) -> None:
    record_unfinished_run(db, job, SeedUseKind.FAILED)
