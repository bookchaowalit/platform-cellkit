# Changelog

Each release is a tag `vX.Y.Z` with the wheel attached. Services pin it in `pyproject.toml`.

## 1.1.0 (2026-11-13)
- SPEC-002, signed finance events (owner approved 2026-11-13): each producer signs its envelopes with its own Ed25519 key, set in `<CELL>_EVENT_SIGNING_KEY`. Consumers check the signature against the keys pinned in `<CELL>_EVENT_KEYS` for the cell named in the event's type. `<CELL>_EVENT_SIGNATURES` is `off` (the default), `report` (count, then apply) or `enforce` (apply only `valid`). The hourly relay job prints the counts. With nothing set, the behaviour and the envelopes are unchanged. A bad key fails the relay with `bad signing key`, and the value is never printed. This answers the specs/001 open question (the producer field could be forged).
- New dependency, `cryptography>=43`, which pyjwt[crypto] already pulled in.
- Red: 00ae032.

## 1.0.11 (2026-11-13)
- app: a create fills in defaults only for the fields in `ranges`. A default the API type cannot take, such as `text` with `default: 0`, is left to the database. 1.0.10 could answer 500 for such a field even on a resource without ranges.
- testing: patterned samples first try the old truncated `<name>-<hex>`, then pick the rarest generated match, so a fixed branch no longer repeats on unique fields. `\W`, `\D` and `\S` are real complements, and an empty character set is a clear error.
- Codex review of 1.0.10. Red: 3 tests (on e237ae2).

## 1.0.10 (2026-11-13)
- spec: a `pattern` that pydantic's Rust regex engine cannot compile (lookaround, backreferences) is refused when `cell.yaml` loads. Before, it loaded and then broke the API models at startup.
- app: a create checks `ranges` on the row with the field defaults filled in, as the database will store it. Before, `end: 5` with `start` defaulting to 10 was accepted.
- testing: patterned samples are built within `max_length` (repeat counts and branches respect the length left), so they never fail at random for a short field.
- Codex review. Red: 4 tests (on 18e1840).

## 1.0.9 (2026-11-13)
- testing: a patterned sample first tries the old `<name>-<8 hex>` (and plain hex), so unique fields keep their entropy. Only if the pattern refuses those does it generate a value, and then it keeps the longest match that fits. An optional group may now be left out, so `^key(-[0-9a-f]+)?$` with `max_length: 3` gives `key`. Codex review of 1.0.8. Red: 2 tests (on 8238888).

## 1.0.8 (2026-11-13)
- refs: `deleted` must be a JSON boolean or null. `"false"`, `0` and the like are malformed, and the message is skipped. Before, `bool("false")` read it as a delete and could clear a live dependent, which let a referenced record be deleted.
- mcp: `Extension.add(..., keep_null=True)` gives a write tool exactly what the caller set: an explicit null clears a field and unset arguments stay out. The default is unchanged (nulls dropped, like list filters), so platform-intake's search tools behave as before.
- testing: `sample()` makes a value that matches a text field's `pattern`, so the contract suite works for patterned cells. It raises a clear error for a pattern it cannot satisfy.
- uv.lock records the package version again (it was left at 1.0.6 in 1.0.7).
- Codex review of 9d5aa92. Red: 3 tests (on 1a5eac8).

## 1.0.7 (2026-11-13)
- platform: a refusal (401/403/409) whose body is HTML, a JSON non-object or a plain-string `detail` is a plain Denied (deny, no reason). It used to raise `JSONDecodeError`/`AttributeError`, so the API answered 500. A 201 without an `execution_id` object is PlatformUnavailable. Closes the strict xfail `test_a_refusal_with_a_non_json_body_is_still_a_denial`.
- db: `LocalCluster.start` keeps its trust-auth socket in an owner-only directory: created 0700, an existing one of ours is tightened, a symlink or another user's directory is refused, and PostgreSQL gets `unix_socket_permissions=0700`. Before, on a shared `/tmp` (no `XDG_RUNTIME_DIR`) another local user could connect as any role. Security review P2.
- Red: 9 tests in `test_cellkit_platform.py` and `test_cellkit_db.py` (on e931bdd).
- Not in this release: the refs producer check still trusts the envelope's `producer` field (any finance producer credential can write the shared topic). Binding the origin needs signed envelopes or per-producer topics; see the open question in specs/001.

## 1.0.6 (2026-11-12)
- mcp: `find_cell()` also looks in the repository that owns the virtualenv it runs in (`<repo>/.venv`). With the kit installed as a wheel, the old fallback was the kit's own location in site-packages, so `<cell>-mcp` started by absolute path from another directory (no `CELL_APP_ROOT`) exited with "cell.yaml not found". Codex review in finance-subscriptions-api. Red: `test_find_cell_uses_the_repository_that_owns_the_virtualenv` (on 508da1a).

## 1.0.5 (2026-11-12)
- refs (SPEC-006 1.11, owner approved 2026-11-12, reverses the 1.1 line "the reader starts at the low watermark"): a fresh reader (no `ref_offsets` rows) whose low watermark is above 0 now gets Unavailable (503), "history expired before the first read". It used to call the read complete without reading anything, which could let a referenced record be deleted. Bootstrap is an operator step. Rebuild the reference state (re-snapshot the producers), then seed the position for each partition: `INSERT INTO <schema>.ref_offsets (topic, partition, next_offset) VALUES ('finance.events.v1', <p>, <low watermark>)`. Codex review in finance-accounts-api. Red: `test_a_fresh_reader_refuses_history_that_expired_before_its_first_read` (on 68b1bb7).

## 1.0.4 (2026-11-12)
- refs (SPEC-006 1.10): when applying stops at the deadline, a partition with nothing applied yet still stores its first unapplied offset. Before, it got no `ref_offsets` row and the next read counted it from 0. Once the low watermark was above 0, every read then failed with "unread history expired", which kept the API and the hourly job on 503. Reported by Codex review in finance-reconciliations-api. Red: `test_a_partition_left_unapplied_at_the_deadline_still_gets_a_position` (8b88fca).

## 1.0.3 (2026-11-12)
- sqlgen: `roles.sql` creates `extra_roles`, like the runtime roles. Cells without `extra_roles` get byte-identical SQL.

## 1.0.2 (2026-11-12)
- refs (SPEC-006 1.9): a boolean reference is malformed, never "no reference". Watermark reads share the catch-up deadline.

## 1.0.1 (2026-11-12)
- Ships `py.typed`.

## 1.0.0 (2026-11-12)
- First release: the finance line of the vendored `src/cellkit`, plus the opt-in `pattern`, `extra_roles` and `mcp_extend` keys.
