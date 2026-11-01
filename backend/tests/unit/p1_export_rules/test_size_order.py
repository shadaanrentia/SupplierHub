
from size_order import size_key


def test_clothing_size_order():
    sizes = [
        "XL",
        "Small",
        "3XL",
        "Medium",
        "XS",
        "Large",
        "2XL",
        "2XS",
        "3XS"
    ]

    result = sorted(sizes, key=size_key)

    expected = [
        "3XS",
        "2XS",
        "XS",
        "Small",
        "Medium",
        "Large",
        "XL",
        "2XL",
        "3XL"
    ]

    assert result == expected


def test_size_aliases():
    assert size_key("Small") == size_key("S")
    assert size_key("Medium") == size_key("M")
    assert size_key("Large") == size_key("L")


def test_empty_size():
    result = size_key("")
    assert result is not None
