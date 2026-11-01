
def calculate_price(cost, markup_percentage):
    return cost + (cost * markup_percentage / 100)


def test_price_with_50_percent_markup():
    result = calculate_price(100, 50)
    assert result == 150


def test_price_with_zero_markup():
    result = calculate_price(100, 0)
    assert result == 100


def test_price_with_20_percent_markup():
    result = calculate_price(100, 20)
    assert result == 120
