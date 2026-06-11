import pytest
from src.utils.helpers import (
    ton_to_nano, nano_to_ton, calculate_discount_percent,
    calculate_profit_percent, safe_divide, clamp, format_ton, format_percent,
    chunk_list, flatten, safe_json_loads,
)


def test_ton_nano_conversion():
    assert ton_to_nano(1.0) == 1_000_000_000
    assert ton_to_nano(0.5) == 500_000_000
    assert nano_to_ton(1_000_000_000) == 1.0
    assert nano_to_ton(500_000_000) == 0.5


def test_calculate_discount():
    assert calculate_discount_percent(8.0, 10.0) == pytest.approx(20.0)
    assert calculate_discount_percent(10.0, 10.0) == pytest.approx(0.0)
    assert calculate_discount_percent(10.0, 0.0) == 0.0


def test_calculate_profit():
    assert calculate_profit_percent(10.0, 12.0) == pytest.approx(20.0)
    assert calculate_profit_percent(10.0, 8.0) == pytest.approx(-20.0)
    assert calculate_profit_percent(0.0, 10.0) == 0.0


def test_safe_divide():
    assert safe_divide(10.0, 2.0) == 5.0
    assert safe_divide(10.0, 0.0) == 0.0
    assert safe_divide(10.0, 0.0, default=99.0) == 99.0


def test_clamp():
    assert clamp(5.0, 0.0, 10.0) == 5.0
    assert clamp(-5.0, 0.0, 10.0) == 0.0
    assert clamp(15.0, 0.0, 10.0) == 10.0


def test_format_ton():
    assert format_ton(1.5) == "1.5000 TON"
    assert format_ton(0.001) == "0.0010 TON"


def test_format_percent():
    assert format_percent(20.5) == "+20.50%"
    assert format_percent(-5.0) == "-5.00%"


def test_chunk_list():
    result = chunk_list([1, 2, 3, 4, 5], 2)
    assert result == [[1, 2], [3, 4], [5]]


def test_flatten():
    result = flatten([[1, 2], [3, 4], [5]])
    assert result == [1, 2, 3, 4, 5]


def test_safe_json_loads():
    assert safe_json_loads('{"a": 1}') == {"a": 1}
    assert safe_json_loads("invalid") is None
    assert safe_json_loads("invalid", default={}) == {}
