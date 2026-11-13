# SPEC-002: Signed finance events

Status: approved by the owner on 2026-11-13 (option 1 of the specs/001 open question). Ships in kit 1.1.0.

## Problem

`refs._apply` trusts an event only when its envelope `producer` names the cell in its `type`.
The sender chooses both fields. The Kafka ACL lets each of the ten finance producer credentials
write to `finance.events.v1`. So a leaked credential from one cell can forge another cell's
creates and deletes, and a referenced record could then look deletable.

## Decision

Each producer signs its envelopes with its own Ed25519 key. A consumer checks the signature
against the public keys pinned for the cell named in the event's `type`.

- **Signed bytes:** the canonical JSON of the envelope without `signature`. That is
  `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` of the envelope
  as it reads back from the wire (it is first serialised with `default=str`, then parsed).
- **Envelope field:** `"signature": {"alg": "Ed25519", "key": "<key id>", "value": "<base64>"}`.
  The key id is the first 16 hex characters of the SHA-256 of the raw 32-byte public key.
  Consumers that do not know the field ignore it; the lake sink stores the whole envelope.
- **Producer setting:** `<CELL>_EVENT_SIGNING_KEY` is the base64 of the raw 32-byte private
  seed, a secret. Both the API's inline relay and the hourly relay job need it. When it is
  unset, events go out unsigned, as before. When it is set but invalid, the relay fails with
  `bad signing key` and sends nothing.
- **Consumer settings** (not secret):
  - `<CELL>_EVENT_KEYS` is JSON mapping a producer cell name to a list of base64 public keys,
    for example `{"finance-budgets": ["..."], ...}`. A list allows rotation: add the new key,
    switch the producer, then drop the old key.
  - `<CELL>_EVENT_SIGNATURES` is `off` (the default), `report` or `enforce`. Any other value
    counts as `enforce` (fail closed). An empty value counts as unset (`off`) on purpose: GitHub
    Actions passes an unset repository variable (`${{ vars.X }}`) as `""`, and unset must keep
    1.0.11 behaviour. A typo is caught; a blank is not a mode.
- **Check:** each event a cell would apply gets a verdict: `valid`, `missing` (no signature),
  `invalid` (bad shape, unknown key id or bad signature) or `unknown_producer` (no keys pinned
  for that cell).
  - `off`: no check.
  - `report`: every verdict is counted and the event is applied as before.
  - `enforce`: only `valid` is applied. Any other event is skipped like a malformed one: the read
    position moves past it and the reference rows stay as they were.
- **Counts:** the hourly relay job prints the counts in its JSON line:
  `"signatures": {"valid": n, "missing": n, "invalid": n, "unknown_producer": n}`.
  No key or signature value is ever printed.

## Rollout

1. Release kit 1.1.0, then pin it in the ten finance services. Nothing changes until the
   settings are set.
2. Generate ten key pairs. Store each private seed in Infisical at `/finance-events`, key
   `<CELL>_EVENT_SIGNING_KEY`, then copy it to the service's Railway variables and its GitHub
   Actions secrets. Never print a seed.
3. Set `<CELL>_EVENT_KEYS` (all ten public keys) and `<CELL>_EVENT_SIGNATURES=report` on every
   finance service and in each relay job.
4. Watch the counts. Once new events show `valid` and no `invalid`, switch to `enforce`. Old
   unsigned history stays behind the stored read positions. A rebuild (re-snapshot) emits new,
   signed events.

## Acceptance criteria

- AC-01: a signed envelope verifies, and changing any byte of it makes the verdict `invalid`.
- AC-02: in `enforce` an unsigned, forged or wrongly keyed event changes no reference rows. In
  `report` it is applied and counted.
- AC-03: with no signing key the relay's output is byte-identical to 1.0.11.
- AC-04: a bad signing key fails the relay with `bad signing key`, without its value.
- AC-05: an unknown mode is `enforce`.
