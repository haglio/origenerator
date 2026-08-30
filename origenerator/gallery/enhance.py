"""Which rows are enhanced, which await enhancement, how to enhance one — and
folding a finished enhance back into the image it upgraded.

An enhancement is not a generation of its own: its result is an upgraded layer
on an existing image. The standalone ``image_enhance`` workflow is machinery —
its job runs under a transient row (so in-flight cards and restart reconnection
work), and the moment it completes, :func:`fold_enhancement` moves its output
onto the source row: the source keeps its folder, star and identity, its
thumbnail and preview become the enhanced pixels, its pre-enhance file stays
listed (and on disk) as the original, and the transient row is deleted.
:func:`fold_completed_enhancements` runs the same fold at startup, healing
completions that landed while the app was closed — and retroactively converting
any older rows recorded as ``image_enhance`` generations.

Enhancement is a *layer*, and a row can carry several: each fold prepends its
file and records the settings that made it (:func:`enhance_levels`), so an image
shows its most-enhanced version by default while every level it has received
stays listed and reachable.

What an enhancement is configured with is a property of the FOLDER, not of any
one image: :class:`EnhanceSettings` is what the gallery's Enhance subpanel edits
and stores per settings folder, and :func:`enhance_params_for` is where it meets
a particular row. The thumbnail badge, the folder's Enhance All button, and the
selection's Enhance action all decide off the helpers here, so "enhanced" means
one thing everywhere: the row went through the upscale + low-denoise re-sample
tail — inline (its workflow's ``enhance`` toggle) or folded in from a standalone
run. ``enhance_detail_fixes`` adds a second stage past that tail, re-sampling
one named part at a time — the faces, the hands, the teeth — each at its own
denoise, one the whole-frame pass could never survive; it is one of the knobs a
level records, so an image can carry both a plain enhancement and a detail-fixed
one and show which is which.
"""

import json
import logging
from dataclasses import dataclass, field

from origenerator.gallery.output import (
    media_type_of_row,
    output_file_reference,
    parse_file_list,
    produced_output,
    row_output_files,
)
from origenerator.gallery.signatures import _frame_name, parse_params
from origenerator.gallery.source_image import source_image_id_for
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.base import UPSCALE_MODEL_FACTOR
from origenerator.workflows.detail_parts import (
    DEFAULT_FIX_DENOISE, detail_fixes_of, detector_part_label, fixable_parts,
)

logger = logging.getLogger(__name__)

ENHANCE_WORKFLOW = "image_enhance"

# The ``source`` a re-derived base render carries (see
# :mod:`origenerator.base_backfill`). Lives here rather than there because the
# tree filters on it and importing the backfill from the gallery would make a
# cycle — the backfill reads the gallery to decide what needs repairing.
BASE_RENDER_SOURCE = "base_render"

# The workflows that ran the enhance tail unconditionally, before it became a
# toggle: their rows carry the tail's params but no ``enhance`` flag.
_ALWAYS_ENHANCED = ("sdxl_t2i", "sdxl_pose_transfer")

# The knobs the Enhance subpanel offers, and so the only params a folder's
# settings may override on an enhance run. Everything else about the job — the
# input file, the prompts steering the added texture — is read off the image
# being enhanced, and the seed is re-rolled per launch like any variation.
ENHANCE_SETTING_KEYS = (
    "checkpoint", "upscale_model", "enhance_scale", "enhance_steps",
    "enhance_denoise", "enhance_detail_fixes",
)

# What a folder's settings leave to the source image rather than pinning: the
# refining checkpoint, which by default is whichever one made the image, so an
# enhanced image stays in its own style. The subpanel offers this as an option
# on its model picker; picking a real checkpoint pins it instead.
MATCH_SOURCE_MODEL = "(match the source image)"


def default_enhance_params() -> dict:
    """The ``image_enhance`` workflow's own defaults, narrowed to the knobs a
    folder may set — what the subpanel shows for a folder that has never been
    configured."""
    defaults = WORKFLOW_REGISTRY[ENHANCE_WORKFLOW].default_params()
    params = {k: defaults[k] for k in ENHANCE_SETTING_KEYS if k in defaults}
    params["checkpoint"] = MATCH_SOURCE_MODEL
    return params


def _level_knobs(params: dict) -> dict:
    """The knobs one enhancement is remembered by, out of whatever it recorded.

    :data:`ENHANCE_SETTING_KEYS` filtered off ``params``, with the detail pass
    read through :func:`~origenerator.workflows.detail_parts.detail_fixes_of` —
    so a level recorded under the old tick-and-two-detectors shape comes back as
    the parts it fixed, and captions, re-runs and duplicate checks all see one
    thing. A level that recorded no pass keeps none rather than an empty dict:
    an enhancement whose knobs are unknown must stay indistinguishable from one
    that recorded nothing at all, which is what an empty ``params`` means.
    """
    knobs = {k: v for k, v in params.items() if k in ENHANCE_SETTING_KEYS}
    fixes = detail_fixes_of(params)
    if fixes:
        knobs["enhance_detail_fixes"] = fixes
    else:
        knobs.pop("enhance_detail_fixes", None)
    return knobs


@dataclass(frozen=True)
class EnhanceSettings:
    """One folder's enhancement configuration.

    ``auto`` is the subpanel's box: with it on, every image the folder newly
    generates is enhanced as it lands, so a folder can be left to produce
    finished images rather than raw ones. ``params`` holds the knobs
    (:data:`ENHANCE_SETTING_KEYS`); a key absent from it falls back to the
    workflow default, and a ``checkpoint`` of :data:`MATCH_SOURCE_MODEL` falls
    back to whichever model made the image.
    """

    auto: bool = False
    params: dict = field(default_factory=default_enhance_params)

    @classmethod
    def parse(cls, raw: str | None) -> "EnhanceSettings":
        """Read back what :meth:`to_json` wrote, tolerating bad or absent data —
        an unconfigured folder is simply the defaults, box off.

        A folder configured before the detail pass became a number per part is
        read as what it asked for (:func:`~origenerator.workflows.detail_parts.
        detail_fixes_of`) rather than as a key this no longer knows: dropping it
        would quietly switch that folder's fix off, and a setting that stops
        applying without saying so is the one thing a stored configuration must
        never do.
        """
        try:
            data = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, TypeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        stored = data.get("params")
        params = default_enhance_params()
        if isinstance(stored, dict):
            params.update({k: v for k, v in stored.items() if k in ENHANCE_SETTING_KEYS})
            params["enhance_detail_fixes"] = detail_fixes_of(stored)
        return cls(auto=bool(data.get("auto")), params=params)

    def to_json(self) -> str:
        return json.dumps({"auto": self.auto, "params": self.params})


def describe_enhance_params(params: dict) -> str:
    """A one-line summary of an enhancement's knobs, for the levels list.

    Reads as "2.0x · 20 steps · 0.15 denoise" — the three numbers that actually
    distinguish one experiment from another, then each part the detail pass
    redrew at the denoise it redrew it at. A pinned model is named after them;
    the default (source-matched) one says nothing, since it is not a choice —
    and neither does a part left at zero, for the same reason.
    """
    bits = []
    scale = params.get("enhance_scale")
    if scale is not None:
        bits.append(f"{float(scale):g}x")
    steps = params.get("enhance_steps")
    if steps is not None:
        bits.append(f"{steps} steps")
    denoise = params.get("enhance_denoise")
    if denoise is not None:
        bits.append(f"{float(denoise):g} denoise")
    # Each part the pass redrew, at its own denoise — "teeth 0.5", or
    # "faces 0.45 & hands 0.6" where several ran.
    fixes = detail_fixes_of(params)
    if fixes:
        bits.append(" & ".join(f"{name} {value:g}"
                               for name, value in fixes.items()))
    checkpoint = params.get("checkpoint")
    if checkpoint and checkpoint != MATCH_SOURCE_MODEL:
        bits.append(str(checkpoint))
    return " · ".join(bits)


@dataclass(frozen=True)
class EnhanceLevel:
    """One version of an image: its file, and how it came to be.

    ``index`` counts enhancements from the original (0), so the labels read
    "Original", "Enhance 1", "Enhance 2"… ``params`` are the knobs that produced
    it — empty for the original, and for any level folded in before the settings
    were recorded — and ``settings`` is those knobs as a line of text. Both:
    the string captions the tile, the dict is what a tile dragged onto the
    Enhance subpanel hands over.
    """

    index: int
    label: str
    file: dict
    params: dict = field(default_factory=dict)

    @property
    def settings(self) -> str:
        return describe_enhance_params(self.params)

    @property
    def is_original(self) -> bool:
        return self.index == 0


def original_files_of(row: dict) -> list[dict]:
    """The pre-enhance version(s) this row holds, or ``[]`` for an unenhanced one.

    Two routes get here and both leave the same shape — the enhanced file(s)
    leading ``output_files``, the original(s) behind them:

    * a standalone enhance folded in, which records what the row held before its
      first enhance in ``original_files``;
    * an inline run of the enhance tail, which saves the base render alongside
      the enhanced one and tags it ``role: "original"`` (see
      :meth:`~origenerator.workflows.base.WorkflowTemplate.base_save_node`).

    Deliberately not "every file after the first": a batch generation saves
    several files from one run, and none of them is a version of any other.
    """
    stored = parse_file_list(row.get("original_files"))
    if stored:
        return stored
    return [f for f in row_output_files(row) if f.get("role") == "original"]


def enhance_levels(row: dict) -> list[EnhanceLevel]:
    """The enhancement(s) this image has received, newest first, with its
    pre-enhance original last when it kept one. ``[]`` for an unenhanced image.

    Every image the green badge marks lists here, because the badge and this
    answer the same question — what enhancement did this receive? Two shapes:

    * it kept an original (:func:`original_files_of`), so whatever sits ahead of
      that is the enhancements, newest first — each fold prepends the file it
      produced — and the original closes the list as level 0;
    * it kept none, which is every image the inline tail finished before the
      enhancement became a layer. There is one file and no "before" to compare
      it against, so the list is that single enhancement.

    Each level names the settings that made it: a folded enhance recorded its
    own (``enhance_history``), an inline one is described by the row's params,
    which are the very knobs its tail ran at. That is what makes a level worth
    dragging onto the Enhance panel even when it stands alone.

    A third shape appears once levels can be deleted (:func:`remove_enhance_levels`):
    the original binned out from under two or more enhancements. There is no
    "before" left to count back from, so the files the history names are the
    levels — which is also why the history entry, not the file's position, is
    what identifies one.
    """
    files = row_output_files(row)
    if not files:
        return []
    history = {
        entry.get("filename"): entry
        for entry in parse_file_list(row.get("enhance_history"))
        if isinstance(entry, dict)
    }
    # A row's own params describe its enhancement only when the tail ran inline;
    # a folded standalone enhance ran at its own settings, which live in the
    # history, and the source row's knobs would be a plausible-looking lie.
    inline = ({} if row.get("original_files")
              else _level_knobs(parse_params(row.get("params_json"))))

    def level(index: int, f: dict) -> EnhanceLevel:
        entry = history.get(f.get("filename")) or {}
        params = entry.get("params") if isinstance(entry.get("params"), dict) else inline
        return EnhanceLevel(index, f"Enhance {index}", f, _level_knobs(params))

    originals = original_files_of(row)
    if originals and len(files) > len(originals):
        enhanced = files[:len(files) - len(originals)]
        levels = [level(len(enhanced) - i, f) for i, f in enumerate(enhanced)]
        # The pre-enhance file, level 0 — the one a re-enhance runs from, and
        # the one the list offers as "what this looked like before".
        levels.append(EnhanceLevel(0, "Original", originals[0]))
        return levels
    if not originals and history:
        # The original was deleted out from under the enhancements: what is left
        # is levels all the way down, named by the history rather than by how
        # many files sit ahead of a "before" that no longer exists.
        enhanced = [f for f in files if f.get("filename") in history]
        if enhanced:
            return [level(len(enhanced) - i, f) for i, f in enumerate(enhanced)]
    if is_enhanced_row(row):
        # Enhanced with nothing kept behind it: the row's leading file IS the
        # enhancement. Only that one — a batch's other files are its siblings,
        # not versions of it.
        return [level(1, files[0])]
    return []


def is_enhanced_row(row: dict) -> bool:
    """Whether this generation carries enhanced pixels — what the green
    thumbnail badge marks. A folded-in standalone enhance (``original_files``
    set) counts, as does an inline run that kept its base render beside the
    enhanced one; a recorded ``enhance_history`` counts on its own, which is the
    row whose original has since been deleted; an explicit ``enhance`` param is
    authoritative for the rest of the inline runs; an SDXL row from the era the
    tail ran unconditionally (tail params stored, no flag yet) counts too."""
    if original_files_of(row):
        return True
    if parse_file_list(row.get("enhance_history")):
        return True
    workflow = row.get("workflow_name") or ""
    if workflow == ENHANCE_WORKFLOW:
        return True  # a transient/unfolded enhance row IS an enhanced image
    params = parse_params(row.get("params_json"))
    if "enhance" in params:
        return bool(params["enhance"])
    return workflow in _ALWAYS_ENHANCED and "enhance_denoise" in params


def displayed_levels(row: dict) -> list[EnhanceLevel]:
    """The versions the info pane lists for ``row`` — what :func:`enhance_levels`
    finds, or the row's one file as ``Original`` when it has received no
    enhancement yet.

    An image's versions are listed even before there are two of them: a place
    that appears only once you already have versions is a place you never find,
    and the enhance you just launched replaces the strip's only other content
    while it runs. ``[]`` for a video, which has no versions and no enhancer.

    Each version carries its own file, so the file rows live beside the level
    that produced them rather than in one undifferentiated block at the top —
    which is why :mod:`origenerator.generation_metadata` asks this what it no
    longer has to list.
    """
    if media_type_of_row(row) != "image":
        return []
    levels = enhance_levels(row)
    if levels:
        return levels
    files = row_output_files(row)
    return [EnhanceLevel(0, "Original", files[0])] if files else []


def remove_enhance_levels(row: dict, filenames) -> dict:
    """The column updates that drop the named versions from ``row``.

    Deleting a level is a file-level edit of one image, not a delete of the
    generation: the row keeps its folder, star, params and identity, and only
    the versions it lists change. So the file leaves ``output_files``, and its
    ``original_files`` / ``enhance_history`` bookkeeping goes with it.

    ``{}`` — change nothing — when the names match no file, or when they would
    take every version: a generation with no file is a generation deleted, which
    is the gallery's own action and not something a version list should do
    quietly.

    Deleting the last enhancement leaves a plain image, so the enhancement
    bookkeeping is cleared out with it — the column, the history, and the
    ``role`` tag an inline run left on its base render. Left behind, any of the
    three would make the one remaining file read as an enhancement of itself.
    """
    doomed = {name for name in filenames if name}
    files = row_output_files(row)
    kept = [f for f in files if f.get("filename") not in doomed]
    if len(kept) == len(files) or not kept:
        return {}
    originals = [f for f in parse_file_list(row.get("original_files"))
                 if f.get("filename") not in doomed]
    history = [e for e in parse_file_list(row.get("enhance_history"))
               if isinstance(e, dict) and e.get("filename") not in doomed]
    original_names = {f.get("filename") for f in original_files_of(row)}
    if not [f for f in kept if f.get("filename") not in original_names]:
        originals, history = [], []
        kept = [{k: v for k, v in f.items() if k != "role"} for f in kept]
    return {
        "output_files": json.dumps(kept),
        "original_files": json.dumps(originals) if originals else None,
        "enhance_history": json.dumps(history) if history else None,
    }


def is_enhanceable_row(row: dict) -> bool:
    """Whether the standalone enhancer can take this row: a finished image.

    An already-enhanced image still qualifies — selecting one and choosing
    Enhance is a deliberate re-enhance. The gestures made without the settings
    in view filter to the not-yet-enhanced instead
    (:func:`rows_awaiting_enhancement`, and :func:`is_enhanced_row` for a
    fullscreen hold's Down)."""
    return media_type_of_row(row) == "image" and produced_output(row)


def enhanced_source_names(rows) -> set[str]:
    """The source-image names (comparison-keyed, like an i2v frame lookup) with
    an un-folded standalone enhance among ``rows`` — normally just the jobs
    still in flight, since a completed one folds into its source and vanishes.
    Keeps a second button press from re-queuing an image already cooking."""
    names = set()
    for row in rows:
        if (row.get("workflow_name") or "") == ENHANCE_WORKFLOW:
            name = _frame_name(parse_params(row.get("params_json")).get("input_image"))
            if name:
                names.add(name)
    return names


def _knobs(params: dict) -> dict:
    """One enhancement's identity as every recorded knob, defaults filling the
    gaps — the parts its detail pass redrew included, since a targeted fix and
    a plain enhancement differ by nothing else."""
    defaults = WORKFLOW_REGISTRY[ENHANCE_WORKFLOW].default_params()
    base = {k: defaults[k] for k in ENHANCE_SETTING_KEYS if k in defaults}
    base["checkpoint"] = MATCH_SOURCE_MODEL
    base.update(_level_knobs(params))
    return base


def level_matching_settings(row: dict, settings: EnhanceSettings | None) -> int | None:
    """The position in :func:`enhance_levels` of the version this row already
    holds at ``settings``, or ``None`` when it holds none.

    Compared against the params an enhance would actually run with
    (:func:`enhance_params_for`), not against the panel's raw values, so the
    source-matched model resolves to this row's own checkpoint before the
    comparison — otherwise "the same settings" would read as different for every
    image the default is left on.

    Both sides are read as the FULL set of knobs, a level's missing ones filled
    from the workflow defaults: :data:`ENHANCE_SETTING_KEYS` grows over time, and
    a level recorded before a knob existed was made with that knob at its
    default — so it still matches settings that leave it there, and turning the
    new knob on correctly reads as a different enhancement.

    What tells the ``+ Enhance`` card it would only be making a duplicate.
    """
    return level_matching_params(row, enhance_params_for(row, settings))


def level_matching_params(row: dict, wanted: dict | None) -> int | None:
    """The position in :func:`enhance_levels` of the version already made at
    the launch params ``wanted``, or ``None`` when the row holds none — the
    same duplicate check as :func:`level_matching_settings`, for a run built
    directly (a spoken targeted fix) rather than from folder settings."""
    if wanted is None:
        return None
    knobs = _knobs(wanted)
    for position, level in enumerate(enhance_levels(row)):
        if level.params and _knobs(level.params) == knobs:
            return position
    return None


def enhance_targets_row(input_image: str | None, row: dict) -> bool:
    """Whether an enhance running on ``input_image`` is an enhance of ``row``.

    Compared by the same frame-name key an i2v start-frame lookup uses, against
    every file the row holds — a first enhance runs on its output, a re-enhance
    on the original still listed behind it, and both are this image.
    """
    name = _frame_name(input_image)
    if not name:
        return False
    return name in {_frame_name(f.get("filename")) for f in row_output_files(row)}


def enhancement_recency(rows) -> dict[str, int]:
    """Each image's newest enhancement, as the id of the run that made it —
    ``{prompt_id: id}``, for the images that have one.

    An enhancement is not an item beside the image but something that happens to
    it, so the shelf that lists what you have lately made has to list the image
    itself, moved: it belongs where its enhancement falls in the library's order,
    not where its own generation does (:func:`~origenerator.gallery.tree.
    recent_generations`). A run's id is that place, and it is available at both
    ends of the run — in flight it is the transient enhance row still among
    ``rows``, and once folded it is the id recorded on the level the run left
    behind.

    An image enhanced before that id was recorded has none here and keeps its own
    place, which is the right answer: an enhancement older than the record of it
    is an enhancement from long ago.
    """
    holders: dict[str, str] = {}
    for row in rows:
        # Every file an image holds, not just its leading one: a first enhance
        # runs on the image's output and a re-enhance on the original still
        # listed behind it, and both are the same image — the match
        # :func:`enhance_targets_row` makes one row at a time, indexed. First
        # match wins over the newest-first rows, which is the row
        # :func:`fold_enhancement` will pick when the run lands.
        if media_type_of_row(row) != "image":
            continue
        for stored in row_output_files(row):
            name = _frame_name(stored.get("filename"))
            if name:
                holders.setdefault(name, row.get("prompt_id"))
    recency: dict[str, int] = {}

    def note(prompt_id, run_id):
        if isinstance(run_id, int) and run_id > recency.get(prompt_id, 0):
            recency[prompt_id] = run_id

    for row in rows:
        if (row.get("workflow_name") or "") == ENHANCE_WORKFLOW:
            name = _frame_name(parse_params(row.get("params_json")).get("input_image"))
            target = holders.get(name) if name else None
            if target is not None and target != row.get("prompt_id"):
                note(target, row.get("id"))
        for entry in parse_file_list(row.get("enhance_history")):
            if isinstance(entry, dict):
                note(row.get("prompt_id"), entry.get("run_id"))
    return recency


def rows_awaiting_enhancement(folder_rows, all_rows) -> list[dict]:
    """The members of a folder its Enhance All button targets: finished images
    that aren't enhanced and don't have an enhance already in flight (checked
    against ``all_rows``, where the transient job rows live)."""
    cooking = enhanced_source_names(all_rows)
    awaiting = []
    for row in folder_rows:
        if not is_enhanceable_row(row) or is_enhanced_row(row):
            continue
        names = {_frame_name(f.get("filename")) for f in row_output_files(row)}
        if names & cooking:
            continue
        awaiting.append(row)
    return awaiting


def enhance_params_for(row: dict, settings: EnhanceSettings | None = None) -> dict | None:
    """The ``image_enhance`` params that enhance ``row``'s output: its file as
    the input, its own prompts steering the added texture, and — unless the
    folder pins a model — the checkpoint that made the source (the SDXL
    workflows record one), so an enhanced image stays in its own style.

    ``settings`` is the Enhance subpanel's current, app-wide configuration: the
    knobs it names (:data:`ENHANCE_SETTING_KEYS`) are laid over the workflow
    defaults, so Enhance All, a single enhance, and an auto-enhance of a newly
    generated image all run at whatever the panel says. Omitted, the workflow's
    own defaults apply.

    An already-enhanced row re-enhances from its ORIGINAL file, not the
    enhanced one, so a deliberate re-enhance re-derives at a fresh seed rather
    than compounding upscale upon upscale — and lands as another level beside
    the ones already there. ``None`` when the row has no output file to
    enhance. The seed is left at the default; the launcher re-rolls it like any
    variation."""
    files = original_files_of(row) or row_output_files(row)
    input_ref = output_file_reference(files)
    if input_ref is None:
        return None
    params = dict(WORKFLOW_REGISTRY[ENHANCE_WORKFLOW].default_params())
    src = parse_params(row.get("params_json"))
    params["input_image"] = input_ref
    params["positive_prompt"] = src.get("positive_prompt") or row.get("positive_prompt") or ""
    params["negative_prompt"] = src.get("negative_prompt") or row.get("negative_prompt") or ""
    checkpoint = src.get("checkpoint")
    if isinstance(checkpoint, str) and checkpoint:
        params["checkpoint"] = checkpoint
    for key, value in (settings.params if settings else {}).items():
        if key not in ENHANCE_SETTING_KEYS:
            continue
        if key == "checkpoint" and value == MATCH_SOURCE_MODEL:
            continue  # leave the source's own model in place
        params[key] = value
    return params


def fix_params_for(row: dict, parts, settings: EnhanceSettings | None = None) -> dict | None:
    """The ``image_enhance`` params for a spoken "fix <part>": the row's latest
    enhancement done again, with a detail pass aimed at each part named.

    The base is the newest level's own recorded knobs — the ask is "the same
    enhancement, plus the fix", so it must not quietly change the scale or
    model the image was finished at. An image never enhanced runs at
    ``settings`` the way any first enhance would.

    **The passes are what was asked for and what the picture already carries —
    never what the panel happens to have ticked.** A spoken fix is a targeted
    act made with no view of the Enhance panel, so a folder configured to fix
    every part must not turn "fix teeth" into a pass over all of them: that is
    a redraw of the whole picture in answer to a command about one part of it.
    The panel is still read for the *number* each part runs at, since nobody
    says a denoise out loud —
    :data:`~origenerator.workflows.detail_parts.DEFAULT_FIX_DENOISE` where it
    has none.

    What the picture already carries does ride along: a "fix eyes" after a "fix
    teeth" redraws both rather than trading the mended teeth away — every
    enhance re-derives from the original, so a pass left out is a fix undone on
    screen. Asking for a part again replaces its earlier pass instead of
    doubling it (which is also what lets the duplicate check read a repeat as a
    repeat).

    ``None`` when nothing installed can find any part asked for
    (:func:`~origenerator.workflows.detail_parts.fixable_parts`), or the row has
    nothing to enhance; the caller says which out loud.
    """
    wanted = fixable_parts(parts)
    if not wanted:
        return None
    newest = next((lvl for lvl in enhance_levels(row)
                   if not lvl.is_original and lvl.params), None)
    base = EnhanceSettings(params=dict(newest.params)) if newest is not None else settings
    params = enhance_params_for(row, base)
    if params is None:
        return None
    configured = detail_fixes_of(settings.params if settings else {})
    already = detail_fixes_of(newest.params) if newest is not None else {}
    params["enhance_detail_fixes"] = dict(
        already,
        **{part.name: configured.get(part.name, DEFAULT_FIX_DENOISE)
           for part in wanted},
    )
    return params


def enhance_file_stem() -> str:
    """The stem every file the enhance workflow saves is named with —
    ``image_enhance`` for ``image/image_enhance_00042_.png``.

    Read off the workflow's own ``filename_prefix`` rather than spelled out
    here, so renaming the output can't leave the recognition below pointed at a
    name nothing writes any more.
    """
    prefix = WORKFLOW_REGISTRY[ENHANCE_WORKFLOW].default_params().get(
        "filename_prefix", "")
    return str(prefix).rsplit("/", 1)[-1]


def is_enhance_product_row(row: dict) -> bool:
    """Whether this row *is* an enhancement rather than an image carrying one.

    An enhancement belongs inside the image it upgraded, so a row of its own is
    always something to fold away — but the row does not always say
    ``image_enhance``. A branch-session enhance folds in the worktree database,
    which the live app never adopts (adoption carries rows the branch *created*,
    and a fold creates none), so the enhanced file reaches the live install as a
    bare file on disk and the import scan reconstructs it from the embedded
    graph: a standalone image, workflow read as ``sdxl_t2i``, with a start-frame
    tile pointing at the very picture it is a version of. That is the shape this
    recognizes — what the enhance workflow wrote, however the row got here.

    So the test is the file, not the workflow name: every output named with
    :func:`enhance_file_stem`, and nothing already recording enhancements of its
    own (``original_files`` / ``enhance_history``), which is what a source row
    that has been folded into carries. A base-render repair is excluded outright
    — it is the opposite errand, and folds by its own route.
    """
    if row.get("source") == BASE_RENDER_SOURCE:
        return False
    if original_files_of(row) or parse_file_list(row.get("enhance_history")):
        return False
    files = row_output_files(row)
    if not files:
        return False
    stem = enhance_file_stem()
    return all((f.get("filename") or "").startswith(f"{stem}_") for f in files)


def _node_order(node_id) -> int:
    """A graph node's id as a number, for reading the order the workflow built
    its nodes in. Non-numeric ids (a hand-authored graph) sort last, together."""
    try:
        return int(node_id)
    except (TypeError, ValueError):
        return 1 << 30


def _graph_level_params(row: dict) -> dict:
    """The enhance knobs a row's stored ComfyUI graph gives up.

    A row the import scan reconstructed keeps the tail's numbers under the
    generic names any sampler has — ``steps`` and ``denoise`` — and says nothing
    at all about the upscale, so folding it on its params alone would file the
    level with a blank settings line and leave the Enhance panel unable to tell
    it apart from a level it has not made yet. The graph that ran is exact about
    all of it, and it is stored on the row: the upscale model by name, the scale
    as the fraction of the model's own 4x output the result was taken back down
    to, and the detail pass by whether its detector nodes are there at all.
    """
    try:
        graph = json.loads(row.get("workflow_json") or "{}")
    except (TypeError, ValueError):
        return {}
    if not isinstance(graph, dict):
        return {}
    found: dict = {}
    detailers: list[tuple[int, dict]] = []
    for node_id, node in graph.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        node_type = node.get("class_type")
        if node_type == "CheckpointLoaderSimple":
            found["checkpoint"] = inputs.get("ckpt_name")
        elif node_type == "UpscaleModelLoader":
            found["upscale_model"] = inputs.get("model_name")
        elif node_type == "ImageScaleBy":
            scale = inputs.get("scale_by")
            if isinstance(scale, (int, float)):
                found["enhance_scale"] = scale * UPSCALE_MODEL_FACTOR
        elif node_type == "KSampler":
            found["enhance_steps"] = inputs.get("steps")
            found["enhance_denoise"] = inputs.get("denoise")
        elif node_type == "DetailerForEach":
            # Sorted by node id below: the passes are laid out in the order they
            # run, which the graph's own key order only happens to keep.
            detailers.append((_node_order(node_id), inputs))
    fixes = {}
    for _, inputs in sorted(detailers, key=lambda pair: pair[0]):
        # Each pass says which part it redrew only by way of the detector two
        # nodes back, so the part is read off the model that found the regions.
        segs = _linked_inputs(graph, inputs.get("segs"))
        model = _linked_inputs(graph, segs.get("bbox_detector")).get("model_name")
        denoise = inputs.get("denoise")
        if isinstance(model, str) and isinstance(denoise, (int, float)):
            fixes[detector_part_label(model.rsplit("/", 1)[-1])] = denoise
    if fixes:
        found["enhance_detail_fixes"] = fixes
    return {k: v for k, v in found.items() if v is not None and k in ENHANCE_SETTING_KEYS}


def _linked_inputs(graph: dict, ref) -> dict:
    """The inputs of the node one input links to, or ``{}`` where there is none.

    A ComfyUI link is ``[node_id, output_index]``; anything else on an input is
    a literal. Every step is guarded because this reads a graph off a file —
    written by an older version of this app, or by ComfyUI itself.
    """
    if not (isinstance(ref, (list, tuple)) and ref and isinstance(ref[0], (str, int))):
        return {}
    node = graph.get(str(ref[0]))
    inputs = node.get("inputs") if isinstance(node, dict) else None
    return inputs if isinstance(inputs, dict) else {}


def enhance_level_params(row: dict) -> dict:
    """The knobs one enhancement ran at, as the keys a level records.

    The row's own params first — a standalone ``image_enhance`` row names every
    one of them — then the stored graph for whatever they leave out, which is
    everything but the sampler numbers on a row the import scan reconstructed.
    """
    params = parse_params(row.get("params_json"))
    level = _level_knobs(params)
    for key, value in _graph_level_params(row).items():
        level.setdefault(key, value)
    return level


def _history_entries(files: list[dict], params: dict,
                     run_id: int | None) -> list[dict]:
    """One ``enhance_history`` entry per file this enhance produced: the file's
    name, the knobs that made it — so a level can name its own settings even
    after the transient job row is gone — and ``run_id``, the id that row had.

    The id is kept for the same reason: the row about to be deleted is what said
    where this enhancement falls in the library's order, and the image it
    upgraded sorts on the shelf by the newest one it has received
    (:func:`enhancement_recency`)."""
    settings = _level_knobs(params)
    return [
        {"filename": f.get("filename"), "params": settings, "run_id": run_id}
        for f in files if f.get("filename")
    ]


def fold_enhancement(db, enhance_row: dict,
                     image_rows: list[dict] | None = None) -> str | None:
    """Fold a finished standalone enhance into the image it enhanced.

    The source row becomes the enhanced image in place: the enhanced file
    leads its ``output_files`` (so previews, thumbnails, and anything built
    from the row use the upgraded pixels), every earlier file stays listed —
    the pre-enhance original remains on disk, reachable from the metadata
    block, and no later import scan finds an orphan — and ``original_files``
    records what the row held before its first enhance, which is also what
    marks it enhanced. The settings this run used are appended to
    ``enhance_history``, so the level it just added can be told apart from the
    ones already there (:func:`enhance_levels`). Folder membership, star,
    params and identity are untouched: enhancing never moves or duplicates a
    node. The transient enhance row is deleted (row only — its file now
    belongs to the source).

    Returns the upgraded source's prompt_id, or ``None`` (and folds nothing)
    when the enhance produced no file or its source image is no longer in the
    database — such a row is left alone rather than half-migrated.

    ``image_rows`` is the pool the start frame is matched against, for a caller
    that already holds one: the startup sweep folds a whole backlog at once, and
    re-reading every generation (graphs included) per fold is the difference
    between a launch and a wait.
    """
    enhanced_files = row_output_files(enhance_row)
    if not enhanced_files:
        return None
    input_image = parse_params(enhance_row.get("params_json")).get("input_image")
    if image_rows is None:
        image_rows = db.list_generations()
    candidates = [
        r for r in image_rows
        if r.get("prompt_id") != enhance_row.get("prompt_id")
        and media_type_of_row(r) == "image"
    ]
    source_id = source_image_id_for(input_image, candidates)
    if source_id is None:
        return None
    source = db.get_generation(source_id)
    updates = {
        "output_files": json.dumps(enhanced_files + row_output_files(source)),
        "enhance_history": json.dumps(
            _history_entries(enhanced_files, enhance_level_params(enhance_row),
                             enhance_row.get("id"))
            + parse_file_list(source.get("enhance_history"))
        ),
    }
    if not source.get("original_files"):
        # First enhance: what the row holds now is the true original. A
        # re-enhance keeps this — the original is the pre-ANY-enhance file.
        updates["original_files"] = source.get("output_files")
    if enhance_row.get("thumbnail_path"):
        updates["thumbnail_path"] = enhance_row["thumbnail_path"]
    db.update_generation(source_id, **updates)
    db.delete_generation(enhance_row["prompt_id"])
    return source_id


def fold_completed_enhancements(db) -> int:
    """Fold every finished enhancement standing as a row of its own into the
    image it upgraded.

    The startup half of the fold: completions that landed while the app was
    closed (reconciled from /history), rows from before enhancement folded at
    all — the retroactive fix that turns old "Image Enhance generations" into
    upgrades of the images they enhanced — and the ones the import scan
    reconstructed from bare files, which is how a branch session's enhance
    arrives (:func:`is_enhance_product_row`). In-flight rows are left for their
    live completion; sourceless rows (the enhanced image was deleted) are left
    as they are. Returns how many rows were folded.

    Oldest first, so a stack of enhancements lands in the order it was made and
    an enhance *of* an enhance finds its input already folded onto the image it
    belongs to. The pool each fold matches against is read once and kept current
    as folds land, because reading it per row would mean pulling every stored
    graph in the library through memory for each one.
    """
    rows = sorted(db.list_generations(), key=lambda r: r.get("id") or 0)
    pool = [r for r in rows if media_type_of_row(r) == "image"]
    folded = 0
    for row in rows:
        if row.get("status") != "completed":
            continue
        if (row.get("workflow_name") or "") != ENHANCE_WORKFLOW                 and not is_enhance_product_row(row):
            continue
        source_id = fold_enhancement(db, row, image_rows=pool)
        if source_id is None:
            continue
        folded += 1
        # The pool's own copies go stale the moment a fold rewrites the source:
        # refresh the one that changed (so the file it just gained can be found
        # by an enhance made from it) and drop the row that no longer exists.
        upgraded = db.get_generation(source_id)
        pool = [r for r in pool if r.get("prompt_id") != row.get("prompt_id")]
        for candidate in pool:
            if candidate.get("prompt_id") == source_id and upgraded is not None:
                candidate.update(upgraded)
    if folded:
        logger.info("Folded %d enhancements into their source images", folded)
    return folded
