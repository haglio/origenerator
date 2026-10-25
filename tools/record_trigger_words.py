from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from origenerator import config
from origenerator.model_titles import is_a_fixs_lora, model_stem
from origenerator.trigger_words import trigger_words_by_lora, write_trigger_words
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


def _loras_with_nothing_written_down() -> list[Path]:
    loras = config.COMFYUI_DIR / "models" / "loras"
    written = trigger_words_by_lora()
    return [loras / name for name in list_lora_files([], accepts=ANY)
            if not (is_no_lora(name) or is_a_fixs_lora(name) or model_stem(name) in written)]


def _words_on_civitai(paths: list[Path], ask) -> dict[str, list[str] | None]:
    by_hash: dict[str, list[Path]] = {}
    for path in paths:
        by_hash.setdefault(_sha256(path), []).append(path)
    hashes = list(by_hash)
    versions = [version for start in range(0, len(hashes), CIVITAI_HASHES_AT_A_TIME)
                for version in ask(hashes[start:start + CIVITAI_HASHES_AT_A_TIME])]
    words: dict[str, list[str]] = {}
    for version in versions:
        for file in version.get("files") or []:
            sha = str((file.get("hashes") or {}).get("SHA256") or "").lower()
            words.setdefault(sha, list(version.get("trainedWords") or []))
    return {model_stem(path): words.get(sha) for sha, copies in by_hash.items()
            for path in copies}


def main(argv=None, ask=ask_civitai) -> int:
    argparse.ArgumentParser(
        description="Ask Civitai for the trigger words of each installed LoRA.").parse_args(argv)
    found = _words_on_civitai(_loras_with_nothing_written_down(), ask)
    write_trigger_words({stem: words or [] for stem, words in found.items()})
    answers = list(found.values())
    print(f"Asked Civitai about {len(answers)} LoRAs: "
          f"{sum(1 for words in answers if words)} with trigger words, "
          f"{answers.count([])} with none, {answers.count(None)} it does not know.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
