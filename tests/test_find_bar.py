import pytest

from origenerator.gui.find_bar import FindBar


@pytest.fixture
def bar(qtbot):
    widget = FindBar()
    qtbot.addWidget(widget)
    return widget


def test_the_strip_takes_no_room_until_it_is_opened(bar):
    assert bar.isHidden()


def test_opening_shows_it_and_takes_the_keyboard(qtbot, bar):
    bar.open_find()

    assert bar.isVisible()
    assert bar.focusWidget() is bar._query


def test_opening_selects_the_standing_query_so_typing_replaces_it(qtbot, bar):
    bar._query.setText("cat")

    bar.open_find()

    assert bar._query.selectedText() == "cat"  # and the old search is still in force


def test_typing_reports_the_query(qtbot, bar):
    seen = []
    bar.query_changed.connect(seen.append)

    bar._query.setText("cat")

    assert seen == ["cat"]


def test_enter_asks_for_the_next_match(qtbot, bar):
    steps = []
    bar.step_requested.connect(steps.append)

    bar._query.returnPressed.emit()

    assert steps == [1]


def test_the_arrows_ask_for_a_step_each_way(qtbot, bar):
    steps = []
    bar.step_requested.connect(steps.append)
    bar.show_count(1, 2)  # they only work with somewhere to step to

    bar._next_btn.click()
    bar._prev_btn.click()

    assert steps == [1, -1]


def test_the_close_button_dismisses(qtbot, bar):
    dismissed = []
    bar.dismissed.connect(lambda: dismissed.append(True))

    bar._close_btn.click()

    assert dismissed == [True]


def test_the_count_reads_as_a_place_in_the_results(qtbot, bar):
    bar._query.setText("cat")

    bar.show_count(3, 12)

    assert bar._count.text() == "3 of 12"


def test_a_query_that_finds_nothing_says_so(qtbot, bar):
    bar._query.setText("wombat")

    bar.show_count(0, 0)

    assert bar._count.text() == "No matches"


def test_nothing_typed_yet_reads_as_nothing_rather_than_zero(qtbot, bar):
    # A count of zero before you have searched anything reads as a failed search.
    bar.show_count(0, 0)

    assert bar._count.text() == ""


def test_the_arrows_gray_out_with_nowhere_to_step(qtbot, bar):
    bar._query.setText("cat")

    bar.show_count(1, 1)  # one match is already the one you're on

    assert not bar._next_btn.isEnabled() and not bar._prev_btn.isEnabled()

    bar.show_count(1, 2)

    assert bar._next_btn.isEnabled() and bar._prev_btn.isEnabled()
