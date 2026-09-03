"""The app's database: the schema it writes, and how it is opened.

The DDL and the migration are here rather than beside any one store because
they are the whole file, not any table of it -- ``salvage_if_malformed`` rebuilds
from this text, and ``migrate`` patches every table at once.

tests/test_db_schema.py holds all of it as a snapshot: another app reads this
file (evolver mounts it read-only and selects seven columns off ``generations``
by name), and every user's database is migrated in place rather than rebuilt.
"""
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
    -- produced and the settings that produced it. What lets the info pane list
    -- every level an image has received rather than just "enhanced".
    enhance_history TEXT,
    thumbnail_path  TEXT,
    error_message   TEXT,
    -- The user's per-item bookmark: a starred image or video, independent of the
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
    -- The twin of evolver_exported_at for the Genau lane: a clip sent to be
    -- upscaled and delivered to Genau's folder. Separate because the two sends
    -- go to different source folders and mean different things, so a video can
    -- have had one, the other, or both.
    genau_exported_at TEXT,
    -- Set at launch on a run a spoken "genau it" started, so its completion hands
    -- the clip on without being asked again. On the row rather than in memory
    -- because a restart mid-generation is routine, and it is the only thing
    -- separating such a run from the identical loop workflow started by hand,
    -- which must stay put until Send-to-Genau is pressed.
    genau_requested_at TEXT,
    -- Where a combine launch got its recipe: the act picked in the Combine
    -- panel's dropdown, and the video whose settings the run re-uses. Either can
    -- stand alone — a dropped video names no act, and an act the overlay curates
    -- a recipe for is answered from no past video. Nothing else about the run
    -- records it: the params carry the recipe's values, never which video they
    -- came from or what the user called the act. Stamped at launch, because a
    -- queue row is read while the run is still pending.
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
    enhance_of TEXT
);

CREATE INDEX IF NOT EXISTS idx_generations_status ON generations(status);
CREATE INDEX IF NOT EXISTS idx_generations_workflow ON generations(workflow_name);
CREATE INDEX IF NOT EXISTS idx_generations_created ON generations(created_at DESC);

CREATE TABLE IF NOT EXISTS folder_meta (
    folder_key    TEXT PRIMARY KEY,
    custom_name   TEXT,
    starred       INTEGER NOT NULL DEFAULT 0,
    -- A bookmark's identity: the tree tier it sits at and a member generation, so
    -- its key can be recomputed under any future key formula (see reconcile).
    level         TEXT,
    ref_prompt_id TEXT
);

-- A folder the user composed by hand out of other folders (see
-- origenerator.gallery.custom). The name is the whole of it; what it holds lives
-- in custom_folder_members.
CREATE TABLE IF NOT EXISTS custom_folders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS custom_folder_members (
    folder_id     INTEGER NOT NULL REFERENCES custom_folders(id) ON DELETE CASCADE,
    -- The gathered folder, by tree key, plus the same identity a folder_meta
    -- bookmark carries so the reconcile can re-point it when a key formula moves.
    folder_key    TEXT    NOT NULL,
    level         TEXT,
    ref_prompt_id TEXT,
    -- Membership order, so a custom folder lists what it holds the way it was built.
    position      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (folder_id, folder_key)
);

-- A request and the generation it queued: the item it was made about, what was
-- heard, and the prompt pair before the edit (the pair after it is the queued
-- generation's own params). What the Requests shelf lists, and the only record
-- of why that generation differs from the one it came from. Kept even when its
-- generation goes: a delete here is undoable, and a restored item should come
-- back with the request that made it, so the shelf skips a record it can't
-- resolve rather than the record being dropped.
--
-- Spoken ("Request … over") or typed: a folder rewrite asks the same thing of
-- every picture in a folder at once and records one of these per picture, which
-- is what links each result to the one it was rewritten from. Such a record has
-- nothing heard and no single term — it says what it wanted by rewriting the
-- prompt, which the old/new pair holds — so `heard` is empty there and
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
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- A deleted generation the recovery bin is still holding: the whole row the
-- delete dropped, and where in the trash its files went, so the Trash shelf can
-- list it, put both back, or end it for good (see origenerator.recovery). The
-- record goes away when the item is restored, purged, or ages out of the
-- retention window; the generations row itself is gone the moment it is deleted,
-- which is why the row travels here rather than staying behind a flag.
-- What a branch session had bookmarked when the live app last adopted from it:
-- the items that worktree's database starred, and its folder bookmarks. Only
-- what has *changed* there since is applied at the next launch, so a star the
-- user has removed here is not reinstated on every launch by a worktree copy
-- that still carries it, and an unstar made in a preview crosses exactly once
-- (see origenerator.branch_session.adopt_branch_curation). Keyed by worktree
-- directory name; a row outlives its worktree harmlessly.
CREATE TABLE IF NOT EXISTS branch_curation (
    branch     TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    adopted_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS deletions (
    prompt_id  TEXT PRIMARY KEY,
    row_json   TEXT NOT NULL,
    batch_json TEXT NOT NULL,
    deleted_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Columns added to a table after it first shipped, and how the DDL above
# declares each one. ``CREATE TABLE IF NOT EXISTS`` leaves a user's existing
# table exactly as it was, so these reach an older database only through
# ``migrate`` — as data rather than as thirteen copies of one `if`, so that
# adding a column is one entry rather than a fourth place to remember.
# tests/test_db_schema.py holds this against the schema from both sides: an
# older table gains every one of them, and each arrives with the type, NOT NULL
# and default the DDL gives it.
ADDED_COLUMNS = {
    "generations": {
        "duration_seconds": "REAL",
        "evolver_exported_at": "TEXT",
        "genau_exported_at": "TEXT",
        "genau_requested_at": "TEXT",
        "progress_json": "TEXT",
        "starred": "INTEGER NOT NULL DEFAULT 0",
        "experiment_verdict": "TEXT",
        "original_files": "TEXT",
        "enhance_history": "TEXT",
        "recipe_category": "TEXT",
        "recipe_video_id": "TEXT",
        "enhance_of": "TEXT",
    },
    "folder_meta": {
        "level": "TEXT",
        "ref_prompt_id": "TEXT",
    },
}

# Every column of the generations table, in declaration order. Used to restore a
# previously-captured row verbatim (see ``restore_generation``).
GENERATION_COLUMNS = (
    "id", "prompt_id", "source", "workflow_name", "workflow_version", "status",
    "positive_prompt", "negative_prompt", "seed", "params_json", "workflow_json",
    "output_files", "original_files", "enhance_history", "thumbnail_path",
    "error_message", "starred", "progress_json", "experiment_verdict",
    "duration_seconds", "created_at", "completed_at", "evolver_exported_at",
    "genau_exported_at", "genau_requested_at", "recipe_category", "recipe_video_id",
    "enhance_of",
)


def create(conn) -> None:
    """Make every table and index this app needs, if they are not there already."""
    conn.executescript(SCHEMA)
    migrate(conn)


def migrate(conn) -> None:
    """Bring an older database up to the current schema.

    ``CREATE TABLE IF NOT EXISTS`` leaves a pre-existing table untouched, so
    every column in ``ADDED_COLUMNS`` is patched in here. Guarded against what
    the table already has, so this stays idempotent.
    """
    for table, columns in ADDED_COLUMNS.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, declaration in columns.items():
            if column not in existing:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
