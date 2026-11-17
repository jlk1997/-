from app.services.fx import convert_map, convert_minor, get_rates


def test_convert_same_currency_is_identity():
    assert convert_minor(12345, "CNY", "CNY") == 12345


def test_convert_usd_to_cny_uses_table():
    rates = get_rates()
    expected = int(round(100 * rates["CNY"]))
    assert convert_minor(100, "USD", "CNY") == expected


def test_convert_map_skips_unknown():
    result = convert_map({"USD": 100, "ZZZ": 50}, target="USD")
    assert result["currency"] == "USD"
    assert result["amount_minor"] == 100
    assert "ZZZ" in result["skipped"]
