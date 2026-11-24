# Verify recipe (platform-cellkit)

The `verify` skill follows this file. The checks are the ones CI runs (Python 3.12).

## Checks

```bash
uv sync --frozen --all-extras --python 3.12   # pgserver is locked as cp312 wheels only
uvx ruff@0.17.1 check . && uvx ruff@0.17.1 format --check .
.venv/bin/mypy .
PYTHON=.venv/bin/python ./run-tests.sh -q   # tests/kit, then tests/finance against both fixture cells
.venv/bin/coverage report --precision=2 --fail-under=93   # CI's gate: 92.8% fails
```

Tests use an embedded `pgserver` (Python 3.12 wheels only); no network.

## End to end

For generator changes, diff the generated SQL and routes for both fixture cells
(`tests/fixtures/finance-accounts`, `finance-transactions`) before and after: unchanged output for an
unchanged `cell.yaml` is the main evidence. For a release, build the wheel and run one consumer's
test suite against it (e.g. finance-transactions-api) before tagging.

## Never

- `<cell>-db provision` (creates Neon projects).
- `<cell>-db migrate` with `<CELL>_DB_MODE=hosted`.
- `<cell>-relay` with `<CELL>_RELAY_DATABASE_URL` or any `<CELL>_KAFKA_*` set to a real database or
  broker: it ignores `_DB_MODE` (`src/cellkit/relay.py`).
- `<cell>-publish` with `EMPIRE_PLATFORM_URL` or `<CELL>_PUBLISHER_TOKEN` pointing at production: it
  posts to the platform even from a local database (`src/cellkit/server.py`).
- Replacing a published release.
