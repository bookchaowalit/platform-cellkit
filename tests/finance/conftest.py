"""Finance-shaped fixture cells (money, currency, cross-cell references, outbox relay).

Run once per fixture with CELLKIT_ROOT set to ``tests/fixtures/finance-accounts`` (referenced by
other cells) or ``tests/fixtures/finance-transactions`` (points into other cells); see the CI job.
"""

import os
from pathlib import Path

import pytest

if not os.environ.get("CELLKIT_ROOT"):
    raise pytest.UsageError("set CELLKIT_ROOT to a tests/fixtures/<cell> directory")

from cellkit.testing import client, harness, owner, platform  # noqa: F401


@pytest.fixture(scope="session")
def cell_root() -> Path:
    return Path(os.environ["CELLKIT_ROOT"]).resolve()
