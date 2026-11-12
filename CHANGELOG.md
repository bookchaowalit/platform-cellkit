# Changelog

Each release is a tag `vX.Y.Z` with the wheel attached. Services pin it in `pyproject.toml`.

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
