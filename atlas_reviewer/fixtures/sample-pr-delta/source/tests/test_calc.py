from calc import line_total


def test_line_total_rounds_once():
    assert line_total(1000, 3, 5) == 2850
    assert line_total(999, 1, 0) == 999
