QWIDGETSIZE_MAX = (1 << 24) - 1

_ONE_LINE_ROOM = 100_000


def narrowest_on_fewest_rows(widget) -> int:
    fewest = widget.heightForWidth(_ONE_LINE_ROOM)
    low, high = 1, _ONE_LINE_ROOM
    while low < high:
        middle = (low + high) // 2
        if widget.heightForWidth(middle) <= fewest:
            high = middle
        else:
            low = middle + 1
    return low
