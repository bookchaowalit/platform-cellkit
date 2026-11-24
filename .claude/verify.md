# Verify recipe (platform-cellkit)

The `verify` skill follows this file. The checks are the ones CI runs.

## Checks

```bash
uv sync --frozen --all-extras
uvx ruff@0.17.1 check . && uvx ruff@0.17.1 format --check .
uv run mypy .
./run-tests.sh -q                 # tests/kit, then tests/finance against both fixture cells
uv run coverage report --fail-under=93
```

Tests use an embedded `pgserver` (Python 3.12 wheels only); no network.

## End to end

For generator changes, diff the generated SQL and routes for both fixture cells
(`tests/fixtures/finance-accounts`, `finance-transactions`) before and after: unchanged output for an
unchanged `cell.yaml` is the main evidence. For a release, build the wheel and run one consumer's
test suite against it (e.g. finance-transactions-api) before tagging.

## Never

- `<cell>-db provision` (creates Neon projects).
- `<cell>-db migrate`, `<cell>-publish` or the relay with `<CELL>_DB_MODE=hosted`.
- Replacing a published release.
