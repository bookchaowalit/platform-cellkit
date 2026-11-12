"""The kit's own tests run against the mini cell in ``tests/cellkit_fixture`` (no real service).

The mini cell is written once per run into a temporary root with its generated roles and
migration SQL, and both ``cell_root`` (cellkit.testing.harness) and ``CELLKIT_ROOT``
(cellkit.contract parametrization) point at it.
"""

import os
import shutil
import tempfile
from pathlib import Path

import pytest
from cellkit_support import write_mini_cell

_ROOT = Path(tempfile.mkdtemp(prefix="ck-kit-"))
write_mini_cell(_ROOT)
os.environ.setdefault("CELLKIT_ROOT", str(_ROOT))

from cellkit.testing import client, harness, owner, platform  # noqa: E402, F401


@pytest.fixture(scope="session")
def cell_root() -> Path:
    return _ROOT


def pytest_unconfigure(config: pytest.Config) -> None:
    shutil.rmtree(_ROOT, ignore_errors=True)
