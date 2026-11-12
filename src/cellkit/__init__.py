"""platform-cellkit: builds a cell's API, database tool, publisher and MCP server from its ``cell.yaml``.

Each microservice keeps its own repository, ``cell.yaml``, service code, database and deploy, and
pins one release of this package. Nothing here is a running service.
"""

from ._sentry import init_sentry as _init_sentry

__version__ = "1.0.4"

_init_sentry()
