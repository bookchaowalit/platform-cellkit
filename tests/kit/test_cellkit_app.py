"""cellkit.app helpers: range checks with the defaults the database fills in."""

from __future__ import annotations

import pytest


def test_a_range_is_checked_with_the_field_defaults_filled_in():
    from cellkit.app import range_errors, with_defaults
    from cellkit.spec import parse

    cell = parse(
        {
            "cell": "kit",
            "resources": {
                "slot": {
                    "fields": {
                        "start": {"type": "int", "default": 10},
                        "end": {"type": "int"},
                    },
                    "ranges": [["start", "end"]],
                }
            },
        }
    )
    r = cell.resource("slot")
    assert range_errors(r, with_defaults(r, {"end": 5})) == ["end", "start"]
    assert range_errors(r, with_defaults(r, {"end": 15})) == []
    assert range_errors(r, with_defaults(r, {"start": 1, "end": 5})) == []


def test_defaults_are_only_filled_in_for_range_fields_and_never_crash_a_create():
    from cellkit.app import with_defaults
    from cellkit.spec import parse

    cell = parse(
        {
            "cell": "kit",
            "resources": {
                "slot": {
                    "fields": {
                        "label": {
                            "type": "text",
                            "default": 0,
                        },  # PostgreSQL casts it; the API never checks it
                        "start": {"type": "int", "default": 10},
                        "end": {"type": "int"},
                    },
                    "ranges": [["start", "end"]],
                },
                "plain": {"fields": {"label": {"type": "text", "default": 0}}},
            },
        }
    )
    assert with_defaults(cell.resource("slot"), {"end": 5}) == {"end": 5, "start": 10}
    assert with_defaults(cell.resource("plain"), {}) == {}


def test_a_numeric_range_default_is_rounded_to_the_column_scale_like_postgresql():
    from decimal import Decimal

    from cellkit.app import range_errors, with_defaults
    from cellkit.spec import parse

    cell = parse(
        {
            "cell": "kit",
            "resources": {
                "band": {
                    "fields": {
                        "low": {
                            "type": "money",
                            "default": "10.00005",
                        },  # numeric(19,4) stores 10.0001
                        "high": {"type": "money"},
                    },
                    "ranges": [["low", "high"]],
                }
            },
        }
    )
    r = cell.resource("band")
    filled = with_defaults(r, {"high": Decimal("10.0000")})
    assert filled["low"] == Decimal("10.0001")
    assert range_errors(r, filled) == ["high", "low"]


def test_a_wide_decimal_range_default_never_breaks_a_create():
    from decimal import Decimal

    from cellkit.app import with_defaults
    from cellkit.spec import parse

    wide = "12345678901234567890.1234567890"  # 30 digits: fits numeric(30,10), not a 28-digit context
    cell = parse(
        {
            "cell": "kit",
            "resources": {
                "band": {
                    "fields": {
                        "low": {"type": "decimal", "default": wide},
                        "high": {"type": "decimal"},
                    },
                    "ranges": [["low", "high"]],
                }
            },
        }
    )
    filled = with_defaults(cell.resource("band"), {"high": Decimal(1)})
    assert filled["low"] == Decimal(wide)


def test_a_non_finite_range_default_is_left_to_the_database():
    from decimal import Decimal

    from cellkit.app import range_errors, with_defaults
    from cellkit.spec import parse

    for bad in ("NaN", "Infinity", "-Infinity", "sNaN"):
        cell = parse(
            {
                "cell": "kit",
                "resources": {
                    "band": {
                        "fields": {
                            "low": {"type": "money", "default": bad},
                            "high": {"type": "money"},
                        },
                        "ranges": [["low", "high"]],
                    }
                },
            }
        )
        r = cell.resource("band")
        filled = with_defaults(r, {"high": Decimal(1)})
        assert "low" not in filled, bad
        assert range_errors(r, filled) == []


@pytest.mark.parametrize(
    ("kind", "default", "expected"),
    [
        ("int", 10, 10),
        ("int", "10", 10),
        ("int", True, None),  # a boolean is not a number here
        ("int", 1.5, None),
        ("real", 2.5, 2.5),
        ("real", "nan", None),
        ("date", "2026-01-01", "date:2026-01-01"),
        ("date", "20260101", None),  # PostgreSQL reads it, the API would not: leave it
        ("timestamp", "2026-01-01T00:00:00+00:00", "ts:2026-01-01T00:00:00+00:00"),
        (
            "timestamp",
            "2026-01-01T07:00:00",
            "ts:2026-01-01T07:00:00+00:00",
        ),  # naive = UTC
        ("timestamp", "20260101", None),  # would be read as a Unix time by the API
        ("timestamp", "now()", None),
    ],
)
def test_range_defaults_are_read_only_where_postgresql_reads_them_the_same(
    kind, default, expected
):
    from datetime import date, datetime

    from cellkit.app import with_defaults
    from cellkit.spec import parse

    cell = parse(
        {
            "cell": "kit",
            "resources": {
                "band": {
                    "fields": {
                        "low": {"type": kind, "default": default},
                        "high": {"type": kind},
                    },
                    "ranges": [["low", "high"]],
                }
            },
        }
    )
    got = with_defaults(cell.resource("band"), {}).get("low")
    if expected is None:
        assert got is None
    elif str(expected).startswith("date:"):
        assert got == date.fromisoformat(expected[5:])
    elif str(expected).startswith("ts:"):
        assert got == datetime.fromisoformat(expected[3:])
    else:
        assert got == expected
