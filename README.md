# platform-cellkit

The toolkit every Solo Empire cell is built with. A cell's `cell.yaml` drives its migration and
role SQL, FastAPI routes and models, permissions, graph events, outbox relay, cross-cell
references, database tool and MCP server.

**This is a library, not a service.** Each microservice keeps its own repository, `cell.yaml`,
service code, Neon database and Railway deploy, and pins one release of this package. Nothing here
runs on its own, holds service code or data, or merges services together.

## Use it in a service

```toml
# pyproject.toml
dependencies = [
    "platform-cellkit[mcp] @ https://github.com/bookchaowalit/platform-cellkit/releases/download/v1.1.1/platform_cellkit-1.1.1-py3-none-any.whl",
]
# add [kafka] for cells that relay their outbox or check cross-cell references (finance)

[project.scripts]
<cell>-api = "cellkit.server:api"
<cell>-publish = "cellkit.server:run_publish"
<cell>-db = "cellkit.server:run_db"
<cell>-mcp = "cellkit.mcp:main"
```

Then `uv lock`; the lock records the wheel's sha256. The import name stays `cellkit`. A service's
tests keep using the kit's fixtures and contract suite:

```python
# tests/conftest.py
from cellkit.testing import client, harness, owner, platform  # noqa: F401

# tests/test_contract.py
from cellkit.contract import *
```

## Opt-in `cell.yaml` keys

| key | what it does |
|---|---|
| `extend: module:function` | adds custom FastAPI routes |
| `mcp_extend: module:function` | adds custom MCP tools (`cellkit.mcp.Extension`) |
| `extra_roles: [relay]` | login roles beyond api and publisher |
| field `pattern: ^...$` | anchored regex, enforced by the API and a CHECK constraint |
| field `references: <cell>.<resource>` | cross-cell reference (SPEC-006, needs `[kafka]`) |

Signed events (SPEC-002, `specs/002-signed-events`): `<CELL>_EVENT_SIGNING_KEY` on the producer;
`<CELL>_EVENT_KEYS` and `<CELL>_EVENT_SIGNATURES=off|report|enforce` on consumers.

## Changing the kit

1. Spec first (`specs/NNN-<slug>/spec.md`, ADR-0004), red test, then the change.
2. `./run-tests.sh` runs the mini cell and both finance fixtures; CI gates coverage.
3. Bump `version` in `pyproject.toml` and `__version__` in `src/cellkit/__init__.py`, tag
   `vX.Y.Z`; the release workflow attaches the wheel. Never replace a published release.
4. Bump the pin in each service on its own schedule; a service is never forced to upgrade.

Semantic versioning: a change that alters generated SQL, routes or permissions for an existing
`cell.yaml` is a major version.
