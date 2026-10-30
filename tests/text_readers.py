from __future__ import annotations

from tokenizers import Tokenizer, models, pre_tokenizers


def word_reader(path) -> None:
    reader = Tokenizer(models.WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    reader.pre_tokenizer = pre_tokenizers.Whitespace()
    path.parent.mkdir(parents=True, exist_ok=True)
    reader.save(str(path))


def clap_reader(hub) -> None:
    repo = hub / "models--laion--larger_clap_general"
    (repo / "refs").mkdir(parents=True)
    (repo / "refs" / "main").write_text("examplerevision", encoding="utf-8")
    word_reader(repo / "snapshots" / "examplerevision" / "tokenizer.json")
