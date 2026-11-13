"""Signed finance events (SPEC-002): each producer signs its envelopes with its own Ed25519 key.

Producer: ``<CELL>_EVENT_SIGNING_KEY`` (base64 of the raw 32-byte seed, a secret).
Consumer: ``<CELL>_EVENT_KEYS`` (JSON ``{"<producer cell>": ["<base64 public key>", ...]}``) and
``<CELL>_EVENT_SIGNATURES`` (``off`` default, ``report`` or ``enforce``; anything else is enforce).
No key or signature value is ever printed or put in an exception.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from collections.abc import Mapping
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from cellkit.spec import Cell

ALG = "Ed25519"
MODES = ("off", "report", "enforce")
VERDICTS = ("valid", "missing", "invalid", "unknown_producer")
Keys = dict[str, dict[str, Ed25519PublicKey]]  # producer -> key id -> public key


class BadKey(ValueError):
    """A signing key or the pinned public keys could not be read (the value is never included)."""


def canonical(envelope: Mapping[str, Any]) -> bytes:
    """The signed bytes: the envelope as it reads back from the wire, without ``signature``."""
    wire = json.loads(json.dumps(dict(envelope), default=str))
    wire.pop("signature", None)
    return json.dumps(
        wire, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def key_id(public: Ed25519PublicKey) -> str:
    raw = public.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()[:16]


def _raw(value: str, what: str) -> bytes:
    try:
        raw = base64.b64decode(value.strip(), validate=True)
    except (binascii.Error, ValueError, AttributeError):
        raise BadKey(what) from None
    if len(raw) != 32:
        raise BadKey(what)
    return raw


def private_key(seed: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(_raw(seed, "bad signing key"))


def sign(envelope: Mapping[str, Any], private: Ed25519PrivateKey) -> dict[str, Any]:
    out = dict(envelope)
    out.pop("signature", None)
    value = private.sign(canonical(out))
    out["signature"] = {
        "alg": ALG,
        "key": key_id(private.public_key()),
        "value": base64.b64encode(value).decode(),
    }
    return out


def maybe_sign(
    envelope: dict[str, Any], private: Ed25519PrivateKey | None
) -> dict[str, Any]:
    """The envelope signed with ``private``, or the same object untouched when there is none."""
    return envelope if private is None else sign(envelope, private)


def parse_keys(text: str) -> Keys:
    try:
        raw = json.loads(text)
        if not isinstance(raw, dict):
            raise TypeError
        out: Keys = {}
        for producer, values in raw.items():
            if not isinstance(producer, str) or not isinstance(values, list):
                raise TypeError
            pinned = [
                Ed25519PublicKey.from_public_bytes(_raw(v, "bad event keys"))
                for v in values
            ]
            out[producer] = {key_id(k): k for k in pinned}
    except (ValueError, TypeError, AttributeError):
        raise BadKey("bad event keys") from None
    return out


def verdict(envelope: Mapping[str, Any], producer: str, keys: Keys) -> str:
    """valid, missing (unsigned), invalid, or unknown_producer (no keys pinned for it)."""
    signature = envelope.get("signature")
    if signature is None:
        return "missing"
    pinned = keys.get(producer)
    if not pinned:
        return "unknown_producer"
    if not isinstance(signature, Mapping) or signature.get("alg") != ALG:
        return "invalid"
    public = pinned.get(str(signature.get("key")))
    value = signature.get("value")
    if public is None or not isinstance(value, str):
        return "invalid"
    try:
        public.verify(base64.b64decode(value, validate=True), canonical(envelope))
    except (InvalidSignature, binascii.Error, ValueError):
        return "invalid"
    return "valid"


# --- settings -------------------------------------------------------------------------------------

_SIGNERS: dict[tuple[str, str], Ed25519PrivateKey] = {}


def signer(
    cell: Cell, environ: Mapping[str, str] = os.environ
) -> Ed25519PrivateKey | None:
    """The cell's signing key, or None when unset; BadKey when it is set but unreadable."""
    seed = environ.get(f"{cell.env}_EVENT_SIGNING_KEY")
    if not seed:
        return None
    cache = (cell.name, hashlib.sha256(seed.encode()).hexdigest())
    if cache not in _SIGNERS:
        _SIGNERS[cache] = private_key(seed)
    return _SIGNERS[cache]


def mode(cell: Cell, environ: Mapping[str, str] = os.environ) -> str:
    value = environ.get(f"{cell.env}_EVENT_SIGNATURES")
    if not value:
        return "off"
    return value if value in MODES else "enforce"  # fail closed on a typo


def keys(cell: Cell, environ: Mapping[str, str] = os.environ) -> Keys:
    text = environ.get(f"{cell.env}_EVENT_KEYS")
    return parse_keys(text) if text else {}
