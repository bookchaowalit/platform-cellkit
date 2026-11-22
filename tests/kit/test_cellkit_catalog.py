"""platform-empire SPEC-002: a resource's catalog links become set events in its outbox."""

from __future__ import annotations

from pathlib import Path

import pytest

from cellkit.spec import SpecError, parse


def set_events(harness, record_id: str) -> list[dict]:
    cell = harness.cell
    rows = harness.superuser(
        f"SELECT payload FROM {cell.schema}.outbox WHERE subject = %s AND type = %s ORDER BY occurred_at, seq",
        (f"empire:{cell.name}:widget:{record_id}", f"{cell.name}.widget.linked"),
    )
    return [row[0] for row in rows]


def test_catalog_set_events(client, owner, harness):
    made = client.post(
        "/v1/widgets", headers=owner, json={"title": "w-cat-1", "category": "alpha"}
    )
    assert made.status_code == 201, made.text
    record = made.json()
    [first] = set_events(harness, record["id"])
    assert first == {
        "relation": "in-domain",
        "mode": "replace",
        "targets": ["empire:platform:domain:health"],
        "set_version": record["version"],
        "version": record["version"],
    }
    # a change to another field emits no set event
    client.patch(f"/v1/widgets/{record['id']}", headers=owner, json={"quantity": 5})
    assert len(set_events(harness, record["id"])) == 1
    changed = client.patch(
        f"/v1/widgets/{record['id']}", headers=owner, json={"category": "beta"}
    ).json()
    last = set_events(harness, record["id"])[-1]
    assert (last["targets"], last["set_version"]) == (
        ["empire:platform:domain:work"],
        changed["version"],
    )
    cleared = client.patch(
        f"/v1/widgets/{record['id']}", headers=owner, json={"category": None}
    ).json()
    last = set_events(harness, record["id"])[-1]
    assert (last["targets"], last["set_version"]) == (
        ["empire:platform:domain:unclassified"],
        cleared["version"],
    )
    # deleting emits no set event (the graph retracts a deleted subject's edges)
    client.delete(f"/v1/widgets/{record['id']}", headers=owner)
    assert len(set_events(harness, record["id"])) == 3


def base(catalog, graph=("title",)):
    resource = {
        "fields": {"title": {"type": "text"}, "kind": {"type": "text"}},
        "catalog": catalog,
    }
    if graph is not None:
        resource["graph"] = list(graph)
    return {"cell": "sample", "resources": {"thing": resource}}


@pytest.mark.parametrize(
    ("catalog", "graph", "message"),
    [
        ({"related-to": {"field": "kind"}}, ("title",), "not one of"),
        ({"in-domain": {"field": "missing"}}, ("title",), "is not a field"),
        (
            {"in-domain": {"field": "kind", "map": {"a": "Bad Slug"}}},
            ("title",),
            "concept slug",
        ),
        ({"in-domain": {"field": "kind", "extra": 1}}, ("title",), "keys are"),
        ({"in-domain": {"field": "kind"}}, None, "need graph events"),
        ([], ("title",), "mapping of relation"),
    ],
)
def test_bad_catalog_links_are_refused(catalog, graph, message):
    with pytest.raises(SpecError, match=message):
        parse(base(catalog, graph), Path("."))


def test_serves_value_without_default_is_an_empty_set():
    cell = parse(
        base({"serves-value": {"field": "kind", "map": {"x": "freedom"}}}), Path(".")
    )
    [link] = cell.resources[0].catalog
    assert link.targets("x") == ["empire:platform:value:freedom"]
    assert link.targets("y") == []
    assert link.targets(None) == []
