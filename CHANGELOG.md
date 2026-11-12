# Changelog

Each release is a tag `vX.Y.Z` with the wheel attached. Services pin it in `pyproject.toml`.

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
