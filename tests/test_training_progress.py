from __future__ import annotations

import io

from origenerator import training_rounds


class _Trainer:
    def __init__(self, *chunks: bytes) -> None:
        self.stdout = io.BufferedReader(io.BytesIO(b"".join(chunks)), buffer_size=16)


def _reported(*chunks: bytes) -> list[dict]:
    reported = []
    progress = training_rounds._Progress(_Trainer(*chunks), {"steps": 10}, 0,
                                         report=lambda _job, **fields: reported.append(fields))
    progress.run()
    return reported


def test_a_step_is_written_down_once_however_many_lines_the_trainer_prints_after_it():
    reported = _reported(b"steps:  30%|###       | 3/10 [00:03<00:07]\n",
                         b"loss 0.1 " * 200 + b"\n",
                         b"steps:  30%|###       | 3/10 [00:03<00:07]\n",
                         b"steps:  40%|####      | 4/10 [00:04<00:06]\n")

    assert [fields["done"] for fields in reported] == [3, 4]
