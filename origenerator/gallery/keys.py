from __future__ import annotations

import hashlib

FOLDER_ID_CHARS = 8

_KEY_DIGEST_CHARS = 12


def _digest(signature: str) -> str:
    return hashlib.sha1(signature.encode("utf-8")).hexdigest()


def sig_key(media_type: str, workflow_name: str, signature: str, prefix: str = "") -> str:
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
    return _digest(key)[:FOLDER_ID_CHARS].upper()
