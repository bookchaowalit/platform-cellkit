# Review guide (platform-cellkit)

The Codex Stop-hook review reads this file from the default branch, never from the change under
review. Owner-written; keep it under 16 KiB.

## What failure looks like here

Treat these as `[P0]`/`[P1]`:

- **Breaking ~25 services**: a change that alters generated SQL, routes or permissions for an
  existing `cell.yaml` without a major version (`README.md`); a swapped-in wheel must leave each
  service's migration SQL unchanged (`specs/001-platform-cellkit-package/spec.md` AC-04).
- **Opt-in keys with effect when unset**: new `cell.yaml` keys must do nothing unless set (spec 001 AC-02).
- **RLS and grants widened** in `src/cellkit/sqlgen.py`: FORCE RLS, column-limited UPDATE grants on
  the outbox.
- **Signed events** (`specs/002-signed-events/spec.md`): under `enforce` an unsigned or forged event
  changes no reference rows; an unknown mode counts as `enforce`, an empty one as `off`; a missing key
  under `enforce` sends nothing; key and seed values are never printed.
- **Relay and set-event logic** (`SKIP LOCKED`, batch quotas): churned in 1.1.7-1.1.10 (`CHANGELOG.md`);
  lost or duplicated events are `[P1]`.
- **Release rules**: a published release is never replaced; tag, `pyproject` version and
  `__version__` agree (`release.yml`).

A change here reaches every cell on its next bump: say in the summary which consumers are affected.

## Severity

- `[P0]` a service's data exposed or corrupted through generated SQL/RLS, forged events accepted, a key printed.
- `[P1]` a consumer service broken on its next version bump (contract tests, routes, migrations).
- `[P2]` edge case, or changed behaviour without a test.
- `[P3]` nit. **At most 3 nits.**

## Skip

- `uv.lock`, `tests/fixtures/**` (fixture cells and migrations), `src/platform_cellkit.egg-info`.

## Evidence

Every finding gives `file:line` and input -> wrong result. No finding without evidence from the diff
or the code it calls. Start the summary with the count, e.g. `2 findings (1 P1, 1 P3)`.
