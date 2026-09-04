"""How a folder's enhancement is configured, and how one is described.

What an enhancement is configured with is a property of the FOLDER, not of any
one image: :class:`EnhanceSettings` is what the gallery's Enhance subpanel edits
and stores per settings folder. :data:`ENHANCE_SETTING_KEYS` is the whole of what
a folder may set — everything else about the job (the input file, the prompts
steering the added texture) is read off the image being enhanced, and the seed is
re-rolled per launch like any variation.

The same keys are what a level is remembered by, so :func:`level_knobs` and
:func:`describe_enhance_params` live here too: what one enhancement ran at, and
the line the versions list says it in.
"""

import json
from dataclasses import dataclass, field

from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.detail_parts import detail_fixes_of

# The standalone workflow one enhancement runs. Machinery rather than a
# generation of its own: its defaults are where an unconfigured folder starts.
ENHANCE_WORKFLOW = "image_enhance"

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


def level_knobs(params: dict) -> dict:
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
