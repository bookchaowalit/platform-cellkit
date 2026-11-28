# Changelog

Each release is a tag `vX.Y.Z` with the wheel attached. Services pin it in `pyproject.toml`.

## 1.2.4 (2026-11-28)
- mcp (SPEC-003, Codex review of the cell bumps, P1): a confirmation is bound to the workspace it named. When the person is asked, the kit reads the bearer token once, adds `Where: workspace <ws>.` to the question (claim `ws`, read for display only; a token that is not a JWT with `ws` shows a 12-hex fingerprint, never the token) and sends the DELETE with that same token. Before, the DELETE re-read the token, so an `EMPIRE_TOKEN_FILE` swapped to another workspace while the form was open could delete that workspace's record with the same id. On 2026-07-28 the answering request rebuilds the question with the token current then: another workspace changes the question, so the SDK asks again and nothing is sent.
- `off` and the no-form shortcut ask nothing and read the token as before.
- Red: tests/kit/test_cellkit_mcp_confirm.py (named workspace, token swapped while the form is open, 2026 answer for another workspace: 3 fail on 1.2.3).

## 1.2.3 (2026-11-28)
- mcp (SPEC-003, Codex review of the cell bumps to 1.2.2): `inputResponses: {}` without `requestState` answers nothing, so it is a first round. Under the default `ask`, a 2026-07-28 client without forms that sent it was treated as answering an earlier question and got `cancelled: not confirmed`; it now keeps the 1.1.x delete (and `require` refuses it with `cancelled: confirmation unavailable`). A form client sending it is asked as before.
- Red: tests/kit/test_cellkit_mcp_confirm.py (empty inputResponses: 2 of 3 fail on 1.2.2).

## 1.2.2 (2026-11-28)
- mcp (SPEC-003, fourth Codex review): only an answer to a form that was actually shown spends a round. Under `EMPIRE_MCP_CONFIRM=off`, a 2026-07-28 client sending `inputResponses: {}` without `requestState` had every call share one key, so the second delete with the tool was refused as `confirmation already used`.
- mcp: spent tokens expire by `time.time()`, the clock the SDK checks token `exp` with; `time.monotonic()` could forget a token the SDK still accepted after the wall clock was set back.
- Disputed (documented in the spec): an extension whose validated payload is not a pure function of its arguments is asked again on 2026-07-28 and sends nothing. That is fail-closed; snapshotting the payload server-side across rounds would replay a stale question into a new call.
- Red: tests/kit/test_cellkit_mcp_confirm.py (off two deletes; clock set back: both fail on 1.2.1).

## 1.2.1 (2026-11-28)
- mcp (SPEC-003, third Codex review of 1.2.0): a 2026-07-28 confirmation is spent under the round's sealed `requestState` token (captured by `CaptureSealedState`, a middleware just outside the SDK's `RequestStateBoundary`), remembered for the SDK ttl (600 s) + 60 s. 1.2.0 keyed on tool + question for 5 minutes, so a replay between 300 s and 600 s went through, and a genuine re-confirmation (e.g. after a `409`) was refused.
- mcp: `Extension.add(..., confirm=True)` now requires `confirm_message` (refused at registration); 1.2.0's default `Run <tool>?` did not show what would be destroyed. No released cell uses `confirm=True` yet.
- mcp: the confirmation message is built only when the person is asked, so a builder that raises cannot block `EMPIRE_MCP_CONFIRM=off` or the no-form shortcut.
- Red: tests/kit/test_cellkit_mcp_confirm.py (53 tests; replay at 301-600 s and re-confirmation after a fresh round failed on 1.2.0).

## 1.2.0 (2026-11-28)
- mcp (SPEC-003): every generated `delete` tool asks the person through MCP form elicitation before it calls the API; only an accept with `confirm: true` sends the DELETE. Decline, cancel, an unticked box, an invalid reply or an error while asking return `cancelled: not confirmed` and send nothing. Built on the SDK's `Resolve`/`Elicit` resolvers, so it works on protocol 2026-07-28 (`InputRequiredResult` rounds) and on the initialize handshake (mid-call `elicitation/create`).
- mcp: `EMPIRE_MCP_CONFIRM=ask|require|off`. `ask` (default, also when empty) keeps the 1.1.13 behaviour for a client that declares no form elicitation; `require` refuses it with `cancelled: confirmation unavailable`; any other value counts as `require`.
- mcp: `Extension.add(..., confirm=True, confirm_message=fn)` lets an `mcp_extend` tool ask too; the default `confirm=False` leaves existing extension tools unchanged.
- Codex review of the first draft: the form is strict (`"true"` or `1` is not a tick); an answered 2026-07-28 round reaches the API once (replays refused for 5 minutes, because the SDK's `request_state` is deterministic); an extension's question is built from the same payload its handler gets; an error after the yes is no longer reported as `cancelled` (the tool body runs in a worker thread, so the yes now lives on a shared call object, not a context variable).
- Second Codex review: a later 2026-07-28 round is decided by its answer even without capabilities (the no-form shortcut is first-round only); the replay key is derived by the server from tool name + question, not from the client's echo; a full key store refuses instead of evicting an unexpired key; the payload is validated once per round and the handler gets the one the question showed.
- No change to generated SQL, routes, permissions or `cell.yaml`. Consumers: every cell's `<cell>-mcp` on its next pin bump; clients with form elicitation (Claude Code) start seeing a confirmation on delete.
- Red: tests/kit/test_cellkit_mcp_confirm.py (`Confirm` missing on 1.1.13; 50 tests now, end to end on both protocol eras).

## 1.1.13 (2026-11-26)
- app: the re-import version (1.1.11) is now read after the INSERT. A concurrent delete of the same legacy id holds the primary key until it commits, so the INSERT waits and the next statement (READ COMMITTED) sees that delete's tombstone; reading before the INSERT could miss it and start the row too low (Codex review of 1.1.12). The row is then moved to one above the highest version its subject already sent.
- The graph side of a re-import whose set event arrives before its `.created` is platform-empire migration 2012.
- Red: tests/kit/test_cellkit_catalog.py (re-import waiting on an uncommitted delete: 2 on 1.1.12, 8 now).

## 1.1.12 (2026-11-26)
- release: same code as the `v1.1.11` tag, whose release stopped because `__version__` still said 1.1.10 (no wheel was published for 1.1.11; pin 1.1.12).

## 1.1.11 (2026-11-26, not released)
- app: an import (`legacy_id`) reuses the old id, so a legacy id imported again after a delete names the same graph subject, whose tombstone holds the deleted version (the row's version + 1). The graph keeps the highest version per subject, so the new row at version 1 was `stale`: the node stayed deleted and its SPEC-002 `in-domain` set event was dropped (an edit only revived the node, without its set). An import of a resource with `graph:` now starts at one above the highest version its outbox already sent for that subject, so the `.created` event revives the node and the set event lands. A first import still starts at 1. Codex review of the platform-empire SPEC-002 rollout (goals and time cells).
- Red: tests/kit/test_cellkit_catalog.py (re-import after delete; first import at 1).

## 1.1.10 (2026-11-23)
- relay: set events no longer share the Kafka batch. The batch select leaves them out again with its own `LIMIT`, so set events ahead of sendable rows neither fill a batch nor end the sweep. A separate step marks at most 100 per batch as relayed (`SKIP LOCKED`). It runs only in a cell that declares `catalog` and only on rows the graph publisher has already sent, so the relay never locks a set event the graph still has to receive. A set event still never holds back a record and is never counted as unsent. Codex review of 1.1.9.
- relay: `RelayResult.marked` counts the set events a batch marked, and `<cell>-relay` keeps sweeping while batches only mark (it stopped after 100). The marking scan walks the unrelayed index, so set events still waiting for the graph are walked again each batch. No cell runs a relay and declares `catalog` today (the catalog cells' outboxes have no relay columns); before one does, it needs a partial index for those rows.
- Red: tests/finance/test_finance_events.py (set events ahead of the batch; a set event the graph has not received). Progress test for `marked`.

## 1.1.9 (2026-11-23)
- relay: a set event is what the graph treats as one: a `.linked` type, `mode: replace` and a catalog relation (`in-domain`, `serves-value`, `measured-by`, `defined-by`). The test is never NULL, so any other `.linked` event (a single link without `mode`, or another relation) is relayed and counted as before.
- relay: set events no longer get a cleanup query of their own, which scanned every unrelayed row in each batch. The batch select takes them in `seq` order (also out of an old backoff), marks them relayed with `SKIP LOCKED` instead of sending them, and never lets them hold back a record. So a row the graph publisher holds while it calls the graph no longer stalls the relay. Codex review of 1.1.8.
- Red: tests/finance/test_finance_events.py (other `.linked` shapes relayed; locked set event).

## 1.1.8 (2026-11-23)
- relay: a catalog set event (`<cell>.<resource>.linked`) is never relayed to Kafka (SPEC-005), which carries `graph:` fields only, and it does not count as unsent: each relay batch marks such rows relayed (so they leave the unrelayed index, and one an older relay left in backoff no longer holds back its record); the graph publisher still sends it. Cells without the relay columns are unaffected. Codex review of 1.1.7.
- Red: tests/finance/test_finance_events.py (never relayed; left in backoff).

## 1.1.7 (2026-11-22)
- spec/app: a resource may declare `catalog: {<relation>: {field, map, default}}` (platform-empire SPEC-002, relations `in-domain` and `serves-value`). On create and on an update that changes `field`, the write adds an outbox set event `<cell>.<resource>.linked` with `mode: replace`, the full `targets` list (`empire:platform:<kind>:<slug>` short form; a null or unmapped value uses `default`, or an empty set without one) and `set_version` = the row's version. Deleting emits no set event: the graph retracts a deleted subject's edges. Needs `graph:`. Without `catalog` nothing changes.
- contract: the created/deleted order check looks at lifecycle events only, since a set event shares the created event's transaction time (cells without the relay's `seq` column keep working).
- The mapped field must be `text` or `enum` with string map keys; `serves-value` is accepted only on `goals:goal`, `projects:project` and `habits:habit` (the graph's subjects); a set event follows every change of the stored value. Codex review.
- Red: tests/kit/test_cellkit_catalog.py.

## 1.1.6 (2026-11-13)
- app: a timestamp range default with more than 6 fractional-second digits is left to the database, because PostgreSQL rounds it while Python truncates it. Codex review of 1.1.5. Red: b40b609.

## 1.1.5 (2026-11-13)
- app: range defaults are read only in forms where PostgreSQL and the API agree: integers, finite numbers, exact numerics (rounded at the column's scale and precision), ISO dates, and ISO timestamps (naive means UTC). Any other default, such as `20260101`, `now()`, NaN or a boolean, is left to the database: it is not range-checked, and it can never fail or wrongly refuse a create. This replaces the API-input conversion (pydantic) that 1.0.10 to 1.1.4 used for defaults. Codex review. Red: 1161d03.

## 1.1.4 (2026-11-13)
- app: a NaN or Infinity numeric range default is never compared. It is left to the database instead of raising InvalidOperation, which used to make the create return 500. Codex review of 1.1.3. Red: 7469d80.

## 1.1.3 (2026-11-13)
- app: the 1.1.2 rounding now works at the column's precision. A `decimal` default with 30 digits raised InvalidOperation in Python's 28-digit context, which made the create return 500. A value the column cannot hold is left to the database. Codex review. Red: 806575d.

## 1.1.2 (2026-11-13)
- app: a `money` or `decimal` default in a range is rounded the way PostgreSQL stores it (half away from zero, at the column scale) before the range check. Before, a default with more decimals was skipped, so the check never saw it. No service sets such a default, so services pick this up on their next bump. Codex review. Red: 48ddf88.

## 1.1.1 (2026-11-13)
- relay: when a cell is in `enforce` and has no signing key (a lost secret reaches GitHub Actions as `""`), it sends nothing and fails with `missing signing key`. Before, it sent unsigned events, and every enforcing consumer would have dropped them.
- relay job: a reference-read failure (`refs.Unavailable`, which includes `bad event keys` under enforce) is a JSON error with exit 2, not a traceback.
- Codex review of 1.1.0. Red: c07b344.

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
