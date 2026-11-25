"""platform-empire SPEC-002: a resource's catalog links become set events in its outbox."""

from __future__ import annotations

from pathlib import Path

import pytest

from cellkit.spec import SpecError, parse


def set_events(harness, record_id: str) -> list[dict]:
    cell = harness.cell
    rows = harness.superuser(
        f"SELECT payload FROM {cell.schema}.outbox WHERE subject = %s AND type = %s ORDER BY occurred_at",
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


def test_reimported_legacy_id_versions_above_its_tombstone(client, owner, harness):
    """A legacy id reused after a delete starts above the versions it already sent.

    The graph keeps the highest version per subject: the delete's tombstone (row version + 1) would make a
    re-import at version 1 `stale`, so the node stayed deleted and its in-domain set was dropped.
    """
    legacy = 424242
    body = {"title": "w-legacy", "category": "alpha", "legacy_id": legacy}
    first = client.post("/v1/widgets", headers=owner, json=body)
    assert first.status_code == 201, first.text
    edited = client.patch(f"/v1/widgets/{legacy}", headers=owner, json={"quantity": 2})
    assert edited.json()["version"] == 2
    assert client.delete(f"/v1/widgets/{legacy}", headers=owner).status_code == 204
    cell = harness.cell
    [(tombstone,)] = harness.superuser(
        f"SELECT (payload->>'version')::bigint FROM {cell.schema}.outbox"
        " WHERE subject = %s AND type = %s",
        (f"empire:{cell.name}:widget:{legacy}", f"{cell.name}.widget.deleted"),
    )
    assert tombstone == 3

    again = client.post("/v1/widgets", headers=owner, json=body)
    assert again.status_code == 201, again.text
    record = again.json()
    assert record["version"] == tombstone + 1
    created = harness.superuser(
        f"SELECT payload FROM {cell.schema}.outbox WHERE subject = %s AND type = %s"
        " ORDER BY occurred_at DESC LIMIT 1",
        (f"empire:{cell.name}:widget:{legacy}", f"{cell.name}.widget.created"),
    )[0][0]
    assert created["version"] == tombstone + 1
    assert set_events(harness, str(legacy))[-1]["set_version"] == tombstone + 1


def test_a_fresh_legacy_import_still_starts_at_version_one(client, owner):
    made = client.post(
        "/v1/widgets", headers=owner, json={"title": "w-legacy-2", "legacy_id": 434343}
    )
    assert made.status_code == 201, made.text
    assert made.json()["version"] == 1


def base(catalog, graph=("title",), cell="sample", resource_name="thing"):
    resource = {
        "fields": {
            "title": {"type": "text"},
            "kind": {"type": "text"},
            "meta": {"type": "json"},
        },
        "catalog": catalog,
    }
    if graph is not None:
        resource["graph"] = list(graph)
    return {"cell": cell, "resources": {resource_name: resource}}


@pytest.mark.parametrize(
    ("catalog", "graph", "message"),
    [
        ({"related-to": {"field": "kind"}}, ("title",), "not one of"),
        ({"in-domain": {"field": "missing"}}, ("title",), "is not a field"),
        ({"in-domain": {"field": ["kind"]}}, ("title",), "is not a field"),
        (
            {"in-domain": {"field": "kind", "map": {"a": "Bad Slug"}}},
            ("title",),
            "concept slug",
        ),
        ({"in-domain": {"field": "kind", "extra": 1}}, ("title",), "keys are"),
        ({"in-domain": {"field": "kind"}}, None, "need graph events"),
        ([], ("title",), "mapping of relation"),
        ({"serves-value": {"field": "kind"}}, ("title",), "accepts it only from"),
        ({"in-domain": {"field": "meta"}}, ("title",), "text or enum"),
        ({"in-domain": {"field": "kind", "map": []}}, ("title",), "mapping of value"),
        (
            {"in-domain": {"field": "kind", "map": False}},
            ("title",),
            "mapping of value",
        ),
        (
            {"in-domain": {"field": "kind", "map": {True: "work"}}},
            ("title",),
            "map keys",
        ),
        (
            {"in-domain": {"field": "kind", "default": "health\n"}},
            ("title",),
            "concept slug",
        ),
    ],
)
def test_bad_catalog_links_are_refused(catalog, graph, message):
    with pytest.raises(SpecError, match=message):
        parse(base(catalog, graph), Path("."))


def test_serves_value_without_default_is_an_empty_set():
    spec = base(
        {"serves-value": {"field": "kind", "map": {"x": "freedom"}}},
        cell="goals",
        resource_name="goal",
    )
    [link] = parse(spec, Path(".")).resources[0].catalog
    assert link.targets("x") == ["empire:platform:value:freedom"]
    assert link.targets("y") == []
    assert link.targets(None) == []
