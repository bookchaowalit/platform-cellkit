"""SPEC-002: finance events are signed per producer (Ed25519) and checked by the consumer."""

from __future__ import annotations

import base64
import copy
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from cellkit import signing


def _pair() -> tuple[str, str]:
    key = Ed25519PrivateKey.generate()
    seed = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(seed).decode(), base64.b64encode(public).decode()


def _envelope() -> dict:
    return {
        "id": "e1",
        "type": "finance-accounts.account.created",
        "version": 1,
        "occurred_at": "2026-11-13T08:00:00+00:00",
        "producer": "finance-accounts",
        "correlation_id": "c",
        "causation_id": None,
        "data": {"workspace_id": "w", "record_id": 7, "name": "ไทย", "deleted": False},
    }


def _wire(envelope: dict) -> dict:
    return json.loads(json.dumps(envelope, separators=(",", ":"), default=str))


def test_a_signed_envelope_verifies_and_any_change_breaks_it():
    seed, public = _pair()
    signed = _wire(signing.sign(_envelope(), signing.private_key(seed)))
    assert signed["signature"]["alg"] == "Ed25519"
    keys = signing.parse_keys(json.dumps({"finance-accounts": [public]}))
    assert signing.verdict(signed, "finance-accounts", keys) == "valid"
    for change in (
        lambda e: e["data"].__setitem__("deleted", True),
        lambda e: e.__setitem__("producer", "finance-budgets"),
        lambda e: e["data"].__setitem__("name", "x"),
        lambda e: e["signature"].__setitem__(
            "value", base64.b64encode(b"0" * 64).decode()
        ),
    ):
        tampered = copy.deepcopy(signed)
        change(tampered)
        assert signing.verdict(tampered, "finance-accounts", keys) == "invalid"


def test_verdicts_for_missing_unknown_and_wrong_keys():
    seed, _public = _pair()
    _other_seed, other_public = _pair()
    signed = _wire(signing.sign(_envelope(), signing.private_key(seed)))
    keys = signing.parse_keys(json.dumps({"finance-accounts": [other_public]}))
    assert signing.verdict(_wire(_envelope()), "finance-accounts", keys) == "missing"
    assert signing.verdict(signed, "finance-accounts", keys) == "invalid"
    assert signing.verdict(signed, "finance-budgets", keys) == "unknown_producer"
    for bad in ("nope", {"alg": "RS256"}, {"alg": "Ed25519", "key": 1, "value": None}):
        broken = dict(signed, signature=bad)
        assert signing.verdict(broken, "finance-accounts", keys) == "invalid"


def test_rotation_accepts_any_pinned_key():
    old_seed, old_public = _pair()
    new_seed, new_public = _pair()
    keys = signing.parse_keys(
        json.dumps({"finance-accounts": [old_public, new_public]})
    )
    for seed in (old_seed, new_seed):
        signed = _wire(signing.sign(_envelope(), signing.private_key(seed)))
        assert signing.verdict(signed, "finance-accounts", keys) == "valid"


def test_settings_and_their_failures(monkeypatch):
    from cellkit.spec import parse

    mini_cell = parse(
        {"cell": "kit", "resources": {"tag": {"fields": {"key": {"type": "text"}}}}}
    )
    env = mini_cell.env
    for name in ("EVENT_SIGNING_KEY", "EVENT_KEYS", "EVENT_SIGNATURES"):
        monkeypatch.delenv(f"{env}_{name}", raising=False)
    assert signing.signer(mini_cell) is None
    assert signing.mode(mini_cell) == "off"
    for value, expected in (
        ("report", "report"),
        ("enforce", "enforce"),
        ("Report", "enforce"),
        ("bogus", "enforce"),
    ):
        monkeypatch.setenv(f"{env}_EVENT_SIGNATURES", value)
        assert signing.mode(mini_cell) == expected
    secret = base64.b64encode(b"too-short").decode()  # decodes, but not 32 bytes
    monkeypatch.setenv(f"{env}_EVENT_SIGNING_KEY", secret)
    signing._SIGNERS.clear()
    with pytest.raises(signing.BadKey) as info:
        signing.signer(mini_cell)
    assert str(info.value) == "bad signing key"
    assert secret not in repr(info.value)
    monkeypatch.setenv(f"{env}_EVENT_KEYS", "[1]")
    with pytest.raises(signing.BadKey, match="bad event keys"):
        signing.keys(mini_cell)


def test_without_a_signing_key_the_envelope_is_unchanged():
    envelope = _envelope()
    assert signing.maybe_sign(envelope, None) is envelope
