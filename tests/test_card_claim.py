from __future__ import annotations

import json
from pathlib import Path

from tools import card_claim


def test_a_free_tile_is_taken_with_who_holds_it_and_since_when(tmp_path):
    claim = tmp_path / "claim.json"

    assert card_claim.take("Example Look 1.1 training", 4242, claim)

    written = json.loads(claim.read_text(encoding="utf-8"))
    assert written["holder"] == "Example Look 1.1 training"
    assert written["pid"] == 4242
    assert written["since"] > 0


def test_a_tile_a_live_program_holds_is_not_taken_and_reads_as_held_by_another(
        tmp_path, another_program):
    claim = tmp_path / "claim.json"
    assert card_claim.take("hand training", another_program.pid, claim)

    assert not card_claim.take("Example Look 1.1 training", 4242, claim)
    assert card_claim.held_by_another(4242, claim)
    assert not card_claim.held_by_another(another_program.pid, claim)
    assert json.loads(claim.read_text(encoding="utf-8"))["holder"] == "hand training"


def test_a_claim_whose_holder_has_died_goes_to_the_next_taker(tmp_path, another_program):
    claim = tmp_path / "claim.json"
    assert card_claim.take("hand training", another_program.pid, claim)
    another_program.kill()
    another_program.wait()

    assert not card_claim.held_by_another(4242, claim)
    assert card_claim.take("Example Look 1.1 training", 4242, claim)
    assert json.loads(claim.read_text(encoding="utf-8"))["pid"] == 4242


def test_a_holder_takes_its_own_claim_again_and_lets_go_of_only_its_own(tmp_path, another_program):
    claim = tmp_path / "claim.json"
    assert card_claim.take("hand training", another_program.pid, claim)

    assert card_claim.take("hand training", another_program.pid, claim)
    card_claim.release(4242, claim)
    assert claim.exists()
    card_claim.release(another_program.pid, claim)
    assert not claim.exists()
    card_claim.release(another_program.pid, claim)


def test_a_claim_nobody_can_read_is_stale(tmp_path):
    claim = tmp_path / "claim.json"
    claim.write_text("not a claim", encoding="utf-8")

    assert not card_claim.held_by_another(4242, claim)
    assert card_claim.take("Example Look 1.1 training", 4242, claim)
    assert json.loads(claim.read_text(encoding="utf-8"))["pid"] == 4242


def test_a_program_that_never_was_is_not_alive():
    assert not card_claim.alive(None)
    assert not card_claim.alive(0)


def test_a_shell_script_takes_holds_and_lets_go_of_the_claim_through_the_module_as_a_command(
        tmp_path, another_program):
    claim = str(tmp_path / "claim.json")
    assert card_claim.main(["take", "hand training", str(another_program.pid), claim]) == 0
    assert card_claim.main(["held-by-another", "4242", claim]) == 0
    assert card_claim.main(["held-by-another", str(another_program.pid), claim]) == 1
    assert card_claim.main(["take", "Example Look 1.1 training", "4242", claim]) == 1
    assert card_claim.main(["release", "4242", claim]) == 0
    assert json.loads(Path(claim).read_text(encoding="utf-8"))["holder"] == "hand training"
    assert card_claim.main(["release", str(another_program.pid), claim]) == 0
    assert not Path(claim).exists()
