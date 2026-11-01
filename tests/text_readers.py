from __future__ import annotations

import json
import string

from tokenizers import Tokenizer, models, pre_tokenizers

from origenerator.prompt_tokens import READ_IN_PIECES, PromptReading


def _words_alone() -> Tokenizer:
    reader = Tokenizer(models.WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    reader.pre_tokenizer = pre_tokenizers.Whitespace()
    return reader


def word_reader(path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _words_alone().save(str(path))


def word_reading(reads_well: int, past_it: str) -> PromptReading:
    return PromptReading(reads_well, past_it, past_it == READ_IN_PIECES, _words_alone())


def clap_reader(hub) -> None:
    repo = hub / "models--laion--larger_clap_general"
    (repo / "refs").mkdir(parents=True)
    (repo / "refs" / "main").write_text("examplerevision", encoding="utf-8")
    word_reader(repo / "snapshots" / "examplerevision" / "tokenizer.json")


def clip_reader(root):
    folder = root / "comfy" / "sd1_tokenizer"
    folder.mkdir(parents=True)
    pieces = ["<|startoftext|>", "<|endoftext|>"]
    for char in string.ascii_lowercase + string.digits + ",.:()":
        pieces += [char, f"{char}</w>"]
    pieces += ["ca", "cat</w>"]
    (folder / "vocab.json").write_text(json.dumps({p: i for i, p in enumerate(pieces)}),
                                       encoding="utf-8")
    (folder / "merges.txt").write_text("#version: 0.2\nc a\nca t</w>\n", encoding="utf-8")
    return folder
