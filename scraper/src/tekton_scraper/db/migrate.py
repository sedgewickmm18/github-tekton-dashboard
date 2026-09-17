"""
Run schema migration for whichever backend is active.
"""
from __future__ import annotations

import logging

from tekton_scraper.db.client import active_backend, get_graph
from tekton_scraper.db.schema import INDEXES

logger = logging.getLogger(__name__)


def migrate() -> None:
    if active_backend() == "falkordb":
        graph = get_graph()
        for idx_query in INDEXES:
            try:
                graph.query(idx_query)
                logger.info("FalkorDB index applied: %s", idx_query)
            except Exception as exc:
                logger.debug("Skipped (already exists?): %s — %s", idx_query, exc)
        logger.info("FalkorDB migration complete.")
    else:
        from tekton_scraper.db.sqlite_backend import migrate as sqlite_migrate
        sqlite_migrate()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    migrate()
