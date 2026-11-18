"""Root conftest: the `--real-embedder` test tier.

Tests marked `real_embedder` build a real BGE-M3 index (about 2.3 GB of weights, loaded on CPU).
A plain `pytest` run skips them, so it needs no model; `pytest --real-embedder` runs them too.

`murshid` itself is importable because uv installs the project in editable mode.
"""

from __future__ import annotations

import pytest

REAL_EMBEDDER_OPTION = "--real-embedder"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        REAL_EMBEDDER_OPTION,
        action="store_true",
        default=False,
        help="also run the tests marked real_embedder, which build a real BGE-M3 index",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption(REAL_EMBEDDER_OPTION):
        return
    skip = pytest.mark.skip(
        reason="builds a real BGE-M3 index (about 2.3 GB of weights); run with --real-embedder"
    )
    for item in items:
        if item.get_closest_marker("real_embedder") is not None:
            item.add_marker(skip)
