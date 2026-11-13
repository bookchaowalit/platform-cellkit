"""SPEC-003: a text field may carry an anchored pattern, enforced by the API and by PostgreSQL."""

from __future__ import annotations

import pytest

from cellkit import sqlgen
from cellkit.app import models
from cellkit.spec import Cell, SpecError, parse

SLUG = "^[a-z0-9][a-z0-9-]{0,9}$"


def cell_with(field: dict) -> Cell:
    return parse(
        {"cell": "kit", "resources": {"tag": {"fields": {"key": field}}}},
    )


def test_a_pattern_becomes_a_check_constraint():
    cell = cell_with({"type": "text", "required": True, "pattern": SLUG})
    key = cell.resource("tag").fields[0]
    assert key.pattern == SLUG
    assert f"key ~ '{SLUG}'" in sqlgen.column(cell, key)


def test_the_api_model_refuses_a_value_that_does_not_match():
    cell = cell_with({"type": "text", "pattern": SLUG})
    create, _ = models(cell.resource("tag"))
    assert create(key="ok-1").key == "ok-1"
    for bad in ("Not Ok", "-lead", "a" * 11, "ok-1\n"):
        with pytest.raises(ValueError, match="should match pattern"):
            create(key=bad)


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ({"type": "int", "pattern": SLUG}, "text field"),
        ({"type": "text", "pattern": 5}, "text field"),
        ({"type": "text", "pattern": "[a-z]+"}, "anchored"),
        ({"type": "text", "pattern": "^a'b$"}, "quote"),
        ({"type": "text", "pattern": "^(a$"}, "invalid pattern"),
    ],
)
def test_a_bad_pattern_is_refused_when_the_spec_loads(field, message):
    with pytest.raises(SpecError, match=message):
        cell_with(field)


def test_the_test_sample_of_a_patterned_field_matches_the_pattern():
    import re

    from cellkit.spec import Field
    from cellkit.testing import sample

    for pattern in (
        r"^[a-z0-9][a-z0-9-]{0,9}$",
        r"^[A-Z]{3}$",
        r"^[0-9a-f]{8}$",
        r"^x-[0-9]+$",
    ):
        f = Field(name="key", type="text", pattern=pattern)
        assert re.fullmatch(pattern, sample(f)), pattern


def test_an_optional_group_may_be_left_out_to_fit_max_length():
    from cellkit.spec import Field
    from cellkit.testing import sample

    f = Field(name="key", type="text", pattern=r"^key(-[0-9a-f]+)?$", max_length=3)
    assert sample(f) == "key"


def test_patterned_samples_keep_enough_entropy_for_unique_fields():
    from cellkit.spec import Field
    from cellkit.testing import sample

    f = Field(name="key", type="text", pattern=r"^key-[0-9a-f]+$", unique=True)
    values = [sample(f) for _ in range(200)]
    assert len(set(values)) == len(values)
    assert all(len(v) >= len("key-") + 8 for v in values)
