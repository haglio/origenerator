from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from origenerator import config
from origenerator.model_titles import kept_by_stem, model_stem, write_kept
from origenerator.workflows.model_files import ANY, is_no_lora, list_lora_files

CIVITAI_BY_HASH = "https://civitai.com/api/v1/model-versions/by-hash"
CIVITAI_HASHES_AT_A_TIME = 100


def ask_civitai(hashes: list[str]) -> list[dict]:
    request = urllib.request.Request(
        CIVITAI_BY_HASH, data=json.dumps(hashes).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "Origenerator"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _records() -> dict:
    return {config.TRIGGER_WORDS_PATH: lambda version: list(version.get("trainedWords") or []),
            config.BASE_MODELS_PATH: lambda version: str(version.get("baseModel") or "")}


def _loras_not_written_down() -> list[Path]:
    loras = config.COMFYUI_DIR / "models" / "loras"
    written = [kept_by_stem(path) for path in _records()]
    return [loras / name for name in list_lora_files([], accepts=ANY)
            if not is_no_lora(name) and not all(model_stem(name) in kept for kept in written)]


def _versions_on_civitai(paths: list[Path], ask) -> dict[str, dict | None]:
    by_hash: dict[str, list[Path]] = {}
    for path in paths:
        by_hash.setdefault(_sha256(path), []).append(path)
    hashes = list(by_hash)
    versions = [version for start in range(0, len(hashes), CIVITAI_HASHES_AT_A_TIME)
                for version in ask(hashes[start:start + CIVITAI_HASHES_AT_A_TIME])]
    own: dict[str, dict] = {}
    for version in versions:
        for file in version.get("files") or []:
            sha = str((file.get("hashes") or {}).get("SHA256") or "").lower()
            if sha not in own or file.get("primary"):
                own[sha] = version
    return {model_stem(path): own.get(sha) for sha, copies in by_hash.items()
            for path in copies}


def main(argv=None, ask=ask_civitai) -> int:
    argparse.ArgumentParser(
        description="Ask Civitai for the trigger words and the base model of each installed "
                    "LoRA.").parse_args(argv)
    found = _versions_on_civitai(_loras_not_written_down(), ask)
    for path, kept_from in _records().items():
        written = kept_by_stem(path)
        write_kept(path, {stem: kept_from(version or {}) for stem, version in found.items()
                            if stem not in written})
    known = [version for version in found.values() if version is not None]
    worded = sum(1 for version in known if version.get("trainedWords"))
    print(f"Asked Civitai about {len(found)} LoRAs: {worded} with trigger words, "
          f"{len(known) - worded} with none, {len(found) - len(known)} it does not know.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
