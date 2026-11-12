from __future__ import annotations

from origenerator.db_seed_uses import (
    forget_the_seeds_tabs_picked_for_their_next_press,
    give_old_seed_uses_their_kind,
)

SCHEMA = """\
CREATE TABLE IF NOT EXISTS generations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id       TEXT    NOT NULL UNIQUE,
    source          TEXT    NOT NULL DEFAULT 'generated',
    workflow_name   TEXT    NOT NULL,
    workflow_version TEXT   NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'pending',
    positive_prompt TEXT,
    negative_prompt TEXT,
    seed            INTEGER,
    params_json     TEXT    NOT NULL,
    workflow_json   TEXT    NOT NULL,
    output_files    TEXT,
    -- Set when a standalone enhance was folded into this row: the output_files
    -- it had before (the pre-enhance file, still on disk and listed among the
    -- current output_files). Presence marks the row enhanced-in-place.
    original_files  TEXT,
    -- One entry per enhancement folded into this row, newest first: the file it
    -- produced and the settings that produced it. What lets the Generate pane list
    -- every version an image has received rather than just "enhanced".
    enhance_history TEXT,
    thumbnail_path  TEXT,
    error_message   TEXT,
    -- The user's per-item favorite: a favorited image or video, independent of the
    -- folder-level star in folder_meta.
    starred         INTEGER NOT NULL DEFAULT 0,
    -- Last live progress of a still-running job (a ProgressTracker snapshot), so a
    -- restart mid-generation can resume the bar at its last position instead of an
    -- indeterminate spin while ComfyUI's next per-step push is awaited.
    progress_json   TEXT,
    -- The user's review of a background experiment (source 'experiment'):
    -- 'up' admits it to the gallery, 'down' rejects it, NULL awaits review.
    experiment_verdict TEXT,
    duration_seconds REAL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    completed_at    TEXT,
    evolver_exported_at TEXT,
    -- Set when the user takes that send back, and the timestamp above cleared in
    -- the same write: the pair is one fact, and half-written it would either hide
    -- a copy Evolver still holds or condemn one just sent. Evolver reads this
    -- column out of this table (it reads no other app's), and deletes every copy
    -- of the video it is holding -- the send is a file copy, so undoing it has to
    -- be a file delete, and only the app whose folders they are can find them.
    -- It stays set afterwards rather than being cleared, because nothing on this
    -- side learns when Evolver has finished; it is the standing answer to "should
    -- this video be in the library", not a request that drains.
    evolver_unsent_at TEXT,
    -- The twin of evolver_exported_at for the Genau lane: a video sent to be
    -- upscaled and delivered to Genau's folder. Separate because the two sends
    -- go to different source folders and mean different things, so a video can
    -- have had one, the other, or both.
    genau_exported_at TEXT,
    -- The Genau lane's twin of evolver_unsent_at, and read the same way: a video
    -- withdrawn here is deleted from Genau's own folder as well as from the
    -- pipeline that put it there.
    genau_unsent_at TEXT,
    -- Set at launch on a run a spoken animation started, so its completion hands
    -- the video on without being asked again. On the row rather than in memory
    -- because a restart mid-generation is routine, and it is the only thing
    -- separating such a run from the identical loop workflow started by hand,
    -- which must stay put until Send-to-Genau is pressed.
    genau_requested_at TEXT,
    -- Where a combine launch got its settings: the action picked in the Combine
    -- Combine's dropdown, and the video whose settings the run re-uses. Either can
    -- stand alone — a dropped video names no action, and an action the overlay pins
    -- settings for is answered from no past video. Nothing else about the run
    -- records it: the params carry the settings' values, never which video they
    -- came from or what the user called the action. Stamped at launch, because a
    -- queue row is read while the run is still pending. Read as ``action`` and
    -- ``source_video`` (STORED_NAMES).
    recipe_category TEXT,
    recipe_video_id TEXT,
    -- The image a standalone enhance run is *of*, by that image's prompt_id.
    -- The run's params name the file it reads, and a file name is not an
    -- identity: ComfyUI's counters are per prefix, a trashed file frees its
    -- number, and several rows have ended up naming one file. Stamped at
    -- launch, so every surface that shows the run on its image's tile, and the
    -- fold that lands its result there, agree on which image that is (see
    -- origenerator.gallery.enhance.enhance_target_id). NULL on a row from
    -- before this was recorded, which falls back to matching the file.
    enhance_of TEXT,
    -- The video this row is one cycle of, by that video's prompt_id. Nothing
    -- writes it any more: cutting a finished video down was how a Genau flick was
    -- made for one afternoon, until the lane learned to ask the sampler for a
    -- loop one cycle long instead (origenerator.gallery.combine.cycle_shaped),
    -- which is the same answer without a second file. The cuts that were made
    -- are still here and still in Genau's folder, so the column stays and the
    -- Generate tab still follows it back to the video each came out of. An
    -- identity rather than a filename, for the reason enhance_of is one, and the
    -- whole of what the two rows know about each other: a cut's params are its
    -- source's, so it sits in the same settings folder and nothing else on it
    -- says which of that folder's videos it was cut from.
    trimmed_from TEXT,
    -- What made the row, as a JSON block (origenerator.provenance): stamped at
    -- launch, or worked out later for a row from before launches were stamped.
    provenance TEXT,
    -- What a still image was sorted as showing: one of the overlay's
    -- image_states, by name. The user's own reading of the finished image
    -- rather than anything its prompt asked for, which is why it is a column and
    -- not a param: NULL until someone has looked, and free to differ between two
    -- images of one settings folder. Never set on a video. Read as ``image_state``.
    picture_state TEXT,
    -- The shield on a queue row: while set, nothing the queue does for later
    -- work stops this run partway. On the row so a restart keeps it.
    shielded        INTEGER NOT NULL DEFAULT 0,
    -- The video a run of the backfill, retired 2026-11-07, was made to take
    -- the place of, by its prompt_id.
    backfill_of TEXT,
    -- Set on a backfill run whose old video's copy in Kino was a Fun Time
    -- favorite, which its own copy is to be once Evolver has filed it.
    fun_time_favorite_owed INTEGER NOT NULL DEFAULT 0,
    -- When the backfill last made this video again in place, for Evolver to
    -- take the new one in place of the copies it holds of the old.
    remade_at TEXT,
    -- On the old version the backfill sent to Trash, the video it was made
    -- again as, by its prompt_id: what Trash labels it an old version by.
    old_version_of TEXT,
    shape TEXT,
    image_actions TEXT,
    image_checked TEXT,
    video_actions TEXT,
    video_checked TEXT,
    combined_labels TEXT,
    why_it_cannot_be_made_again TEXT,
    evolver_upscale TEXT,
    evolver_upscaled_at TEXT,
    finale_id TEXT,
    watch_completions INTEGER NOT NULL DEFAULT 0,
    watch_skips INTEGER NOT NULL DEFAULT 0,
    watch_locks INTEGER NOT NULL DEFAULT 0,
    web_url TEXT,
    library_id TEXT,
    upscale_provenance TEXT
);

CREATE INDEX IF NOT EXISTS idx_generations_status ON generations(status);
CREATE INDEX IF NOT EXISTS idx_generations_workflow ON generations(workflow_name);
CREATE INDEX IF NOT EXISTS idx_generations_created ON generations(created_at DESC);

CREATE TABLE IF NOT EXISTS folder_meta (
    folder_key    TEXT PRIMARY KEY,
    custom_name   TEXT,
    starred       INTEGER NOT NULL DEFAULT 0,
    -- A favorite's identity: the tree tier it sits at and a generation under it, so
    -- its key can be recomputed under any future key formula (see reconcile).
    level         TEXT,
    ref_prompt_id TEXT
);

-- A folder the user composed by hand (see origenerator.gallery.custom). The name
-- is the whole of it; the folders it gathers live in custom_folder_items, and the
-- images and videos it holds on their own in custom_folder_generations.
CREATE TABLE IF NOT EXISTS custom_folders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    side       TEXT
);

CREATE TABLE IF NOT EXISTS custom_folder_items (
    folder_id     INTEGER NOT NULL REFERENCES custom_folders(id) ON DELETE CASCADE,
    -- The gathered folder, by tree key, plus the same identity a folder_meta
    -- favorite carries so the reconcile can re-point it when a key formula moves.
    folder_key    TEXT    NOT NULL,
    level         TEXT,
    ref_prompt_id TEXT,
    -- The order they were added, so a custom collection lists what it holds that way.
    position      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (folder_id, folder_key)
);

CREATE TABLE IF NOT EXISTS custom_folder_generations (
    folder_id INTEGER NOT NULL REFERENCES custom_folders(id) ON DELETE CASCADE,
    prompt_id TEXT    NOT NULL,
    position  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (folder_id, prompt_id)
);

-- A request and the generation it queued: the item it was made about, what was
-- heard, and the prompt pair before the edit (the pair after it is the queued
-- generation's own params). The only record of why that generation differs from
-- the one it came from. Kept even when its generation goes: a delete here is
-- undoable, and a restored item should come back with the request that made it.
--
-- A request records one, and so does a folder's Modify batch (all seeds), which
-- rewrites every image in a folder at once and records one per image,
-- linking each result to the one it was rewritten from. A Modify batch has nothing
-- heard and no single term — it says what it wanted by rewriting the prompt,
-- which the old/new pair holds — so `heard` is empty there and
-- `term`/`polarity`/`action` are unset.
CREATE TABLE IF NOT EXISTS requests (
    prompt_id        TEXT PRIMARY KEY,
    source_prompt_id TEXT NOT NULL,
    heard            TEXT NOT NULL,
    term             TEXT,
    polarity         TEXT,
    action           TEXT,
    old_positive     TEXT,
    old_negative     TEXT,
    new_positive     TEXT,
    new_negative     TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    -- The request's own words: what was said between "Request" and "over", or
    -- what was typed into a tab's Request section. NULL on a record from before
    -- the column, whose words are read back out of `heard`.
    asked            TEXT
);

-- The exchange that led to the item `prompt_id`, a turn per row: a Request's
-- words and what the model answered. A spoken Request is one turn; typed ones
-- are as many as were typed before Generate was pressed.
CREATE TABLE IF NOT EXISTS request_turns (
    id           INTEGER PRIMARY KEY,
    prompt_id    TEXT NOT NULL,
    said         TEXT NOT NULL,
    answered     TEXT NOT NULL DEFAULT '',
    old_positive TEXT NOT NULL DEFAULT '',
    old_negative TEXT NOT NULL DEFAULT '',
    new_positive TEXT NOT NULL DEFAULT '',
    new_negative TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    settings_json TEXT NOT NULL DEFAULT '',
    made         TEXT NOT NULL DEFAULT ''
);

-- A deleted generation the Trash is still holding: the whole row the
-- delete dropped, and where in the trash its files went, so the Trash collection can
-- list it, put both back, or end it for good (see origenerator.trash_collection). The
-- record goes away when the item is restored or purged, and not otherwise; the
-- generations row itself is gone the moment it is deleted,
-- which is why the row travels here rather than staying gated by a flag.
CREATE TABLE IF NOT EXISTS deletions (
    prompt_id  TEXT PRIMARY KEY,
    row_json   TEXT NOT NULL,
    batch_json TEXT NOT NULL,
    deleted_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS item_numbers (
    prompt_id  TEXT PRIMARY KEY,
    folder_key TEXT    NOT NULL,
    number     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS seed_uses (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    kind           TEXT    NOT NULL,
    seed_key       TEXT    NOT NULL,
    seed           INTEGER NOT NULL,
    width          INTEGER,
    height         INTEGER,
    thumbnail_path TEXT,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    media_type     TEXT
);

-- A video put in Combine's (custom) drop zone by hand, under the lane showing then,
-- and a generation launched from one, by that generation's prompt_id. One made
-- from the drop zone that no row here names was launched before anything was written
-- here, so which lane it was for is not known.
CREATE TABLE IF NOT EXISTS combine_video_uses (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    intent               TEXT    NOT NULL,
    video_prompt_id      TEXT    NOT NULL,
    generation_prompt_id TEXT,
    created_at           TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

ADDED_COLUMNS = {
    "generations": {
        "duration_seconds": "REAL",
        "evolver_exported_at": "TEXT",
        "evolver_unsent_at": "TEXT",
        "genau_exported_at": "TEXT",
        "genau_unsent_at": "TEXT",
        "genau_requested_at": "TEXT",
        "progress_json": "TEXT",
        "starred": "INTEGER NOT NULL DEFAULT 0",
        "experiment_verdict": "TEXT",
        "original_files": "TEXT",
        "enhance_history": "TEXT",
        "recipe_category": "TEXT",
        "recipe_video_id": "TEXT",
        "enhance_of": "TEXT",
        "trimmed_from": "TEXT",
        "provenance": "TEXT",
        "why_it_cannot_be_made_again": "TEXT",
        "picture_state": "TEXT",
        "shielded": "INTEGER NOT NULL DEFAULT 0",
        "backfill_of": "TEXT",
        "fun_time_favorite_owed": "INTEGER NOT NULL DEFAULT 0",
        "remade_at": "TEXT",
        "old_version_of": "TEXT",
        "shape": "TEXT",
        "image_actions": "TEXT",
        "image_checked": "TEXT",
        "video_actions": "TEXT",
        "video_checked": "TEXT",
        "combined_labels": "TEXT",
        "evolver_upscale": "TEXT",
        "evolver_upscaled_at": "TEXT",
        "finale_id": "TEXT",
        "watch_completions": "INTEGER NOT NULL DEFAULT 0",
        "watch_skips": "INTEGER NOT NULL DEFAULT 0",
        "watch_locks": "INTEGER NOT NULL DEFAULT 0",
        "web_url": "TEXT",
        "library_id": "TEXT",
        "upscale_provenance": "TEXT",
    },
    "folder_meta": {
        "level": "TEXT",
        "ref_prompt_id": "TEXT",
    },
    "custom_folders": {
        "side": "TEXT",
    },
    "request_turns": {
        "settings_json": "TEXT NOT NULL DEFAULT ''",
        "made": "TEXT NOT NULL DEFAULT ''",
    },
    "seed_uses": {
        "media_type": "TEXT",
    },
    "requests": {
        "asked": "TEXT",
    },
}

RENAMED_TABLES = {"custom_collection_members": "custom_folder_items"}

_NEW_FILES_FORGET_THE_RECORDED_SHAPE = """CREATE TRIGGER IF NOT EXISTS new_files_forget_the_recorded_shape
AFTER UPDATE OF output_files, thumbnail_path, params_json, workflow_name ON generations
WHEN NEW.shape IS OLD.shape AND NEW.shape IS NOT NULL
BEGIN
    UPDATE generations SET shape = NULL WHERE id = NEW.id;
END;
"""

GENERATION_COLUMNS = (
    "id", "prompt_id", "source", "workflow_name", "workflow_version", "status",
    "positive_prompt", "negative_prompt", "seed", "params_json", "workflow_json",
    "output_files", "original_files", "enhance_history", "thumbnail_path",
    "error_message", "starred", "progress_json", "experiment_verdict",
    "duration_seconds", "created_at", "completed_at", "evolver_exported_at",
    "evolver_unsent_at", "genau_exported_at", "genau_unsent_at",
    "genau_requested_at", "recipe_category", "recipe_video_id",
    "enhance_of", "trimmed_from", "provenance", "picture_state", "shielded",
    "backfill_of", "fun_time_favorite_owed", "remade_at", "old_version_of", "shape",
    "image_actions", "image_checked", "video_actions", "video_checked", "combined_labels",
    "why_it_cannot_be_made_again", "evolver_upscale", "evolver_upscaled_at", "finale_id",
    "watch_completions", "watch_skips", "watch_locks", "web_url", "library_id",
    "upscale_provenance",
)


STORED_NAMES = {"action": "recipe_category", "source_video": "recipe_video_id",
                "image_state": "picture_state"}


def as_read(row) -> dict:
    read = dict(row)
    for name, stored in STORED_NAMES.items():
        if stored in read:
            read[name] = read.pop(stored)
    return read


def as_stored(row: dict) -> dict:
    stored = dict(row)
    for name, column in STORED_NAMES.items():
        if name in stored:
            stored[column] = stored.pop(name)
    return stored


def create(conn) -> None:
    rename_tables(conn)
    conn.executescript(f"BEGIN;\n{SCHEMA}\nCOMMIT;")
    migrate(conn)


def rename_tables(conn) -> None:
    have = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    for old, new in RENAMED_TABLES.items():
        if old in have and new not in have:
            conn.execute(f"ALTER TABLE {old} RENAME TO {new}")


def migrate(conn) -> None:
    for table, columns in ADDED_COLUMNS.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, declaration in columns.items():
            if column not in existing:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
    conn.execute(_NEW_FILES_FORGET_THE_RECORDED_SHAPE)
    conn.execute("DROP TABLE IF EXISTS branch_curation")
    give_old_seed_uses_their_kind(conn)
    forget_the_seeds_tabs_picked_for_their_next_press(conn)
