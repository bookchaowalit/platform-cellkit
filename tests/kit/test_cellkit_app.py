

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
