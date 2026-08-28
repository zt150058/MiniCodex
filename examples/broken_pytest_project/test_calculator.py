from calculator import add, is_even


def test_adds_positive_numbers() -> None:
    assert add(2, 3) == 5


def test_detects_even_and_odd_numbers() -> None:
    assert is_even(4) is True
    assert is_even(3) is False
