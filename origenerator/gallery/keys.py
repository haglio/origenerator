"""How a derived folder is identified, and what it is called before you name it.

A folder's *key* is what its star, its custom name and its membership of a custom
folder hang off, so it has to be derivable from any member row and has to stay
put as the library grows. Every level below the workflow is keyed by a hash of
the facet it projects — the model, the LoRA, the start frame, the full settings —
tagged with the media type, the workflow and a letter for the level.

A folder's generic *name* falls out of that key: :func:`folder_id` renders it as
a short code. The settings leaves used to be named after their prompt, and a
prompt is a paragraph where a folder name is a line — the breadcrumb over the
browser pane ran to a dozen lines and squeezed the pictures it sits above. A code
is one line, is the same code in the tree, the header and a branch preview, and
lasts exactly as long as the folder does. Nothing is lost by it: what the prompt
said is on every generation inside the folder, the settings that set it apart
from its siblings ride its tooltip, and any folder worth telling apart at a
glance is one worth naming — every folder here can be renamed in place
(:meth:`origenerator.db.Database.rename_folder`), which is the whole point of a
name that starts out generic.
"""

import hashlib

# How much of a key's digest a folder's generic name shows. Eight hex characters
# is four billion codes — no library will ever put two of them on one screen —
# and still short enough to read as a name rather than as a hash. Hex is the
# right alphabet for it by accident: it has no O to mistake for 0 and no I to
# mistake for 1.
FOLDER_ID_CHARS = 8

# How much of the digest a *key* carries. Wider than the name on purpose: the key
# is the identity a bookmark is stored under, so it is sized against every folder
# that has ever existed rather than against the ones on screen together.
_KEY_DIGEST_CHARS = 12


def _digest(signature: str) -> str:
    return hashlib.sha1(signature.encode("utf-8")).hexdigest()


def sig_key(media_type: str, workflow_name: str, signature: str, prefix: str = "") -> str:
    """A folder's stable key from its signature, tagged by level.

    The one-letter ``prefix`` (``m`` model, ``l`` LoRA, ``i`` source image; none
    for settings) keeps each level's key clear of the others' — a settings
    folder's segment is pure hex, so no prefixed key can collide with it in
    ``folder_meta``.
    """
    return f"{media_type}/{workflow_name}/{prefix}{_digest(signature)[:_KEY_DIGEST_CHARS]}"


def settings_key(media_type: str, workflow_name: str, signature: str) -> str:
    return sig_key(media_type, workflow_name, signature)


def model_key(media_type: str, workflow_name: str, signature: str) -> str:
    return sig_key(media_type, workflow_name, signature, "m")


def lora_key(media_type: str, workflow_name: str, signature: str) -> str:
    return sig_key(media_type, workflow_name, signature, "l")


def source_image_key(media_type: str, workflow_name: str, signature: str) -> str:
    return sig_key(media_type, workflow_name, signature, "i")


def folder_id(key: str) -> str:
    """The generic name a derived folder wears until it is given a real one."""
    return _digest(key)[:FOLDER_ID_CHARS].upper()
