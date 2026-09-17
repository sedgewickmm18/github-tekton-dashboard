"""
Storage backend selector.

On first use, tries to connect to FalkorDB.  If the connection succeeds,
FalkorDB is used for all subsequent calls.  Otherwise falls back to the
local SQLite file.

Set TEKTON_BACKEND=sqlite  to force SQLite without attempting FalkorDB.
Set TEKTON_BACKEND=falkordb to require FalkorDB (fail hard if unreachable).
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Literal

logger = logging.getLogger(__name__)

BackendType = Literal["falkordb", "sqlite"]

FALKORDB_HOST = os.environ.get("FALKORDB_HOST", "localhost")
FALKORDB_PORT = int(os.environ.get("FALKORDB_PORT", "6379"))
GRAPH_NAME = os.environ.get("FALKORDB_GRAPH", "tekton-dashboard")


def _try_falkordb() -> bool:
    """Return True if FalkorDB is reachable."""
    try:
        import socket
        s = socket.create_connection((FALKORDB_HOST, FALKORDB_PORT), timeout=1.5)
        s.close()
        return True
    except OSError:
        return False


@lru_cache(maxsize=1)
def active_backend() -> BackendType:
    forced = os.environ.get("TEKTON_BACKEND", "").lower()
    if forced == "sqlite":
        logger.info("Backend: SQLite (forced via TEKTON_BACKEND)")
        return "sqlite"
    if forced == "falkordb":
        logger.info("Backend: FalkorDB (forced via TEKTON_BACKEND)")
        return "falkordb"
    if _try_falkordb():
        logger.info("Backend: FalkorDB (auto-detected at %s:%s)", FALKORDB_HOST, FALKORDB_PORT)
        return "falkordb"
    logger.info(
        "Backend: SQLite (FalkorDB not reachable at %s:%s)", FALKORDB_HOST, FALKORDB_PORT
    )
    return "sqlite"


def get_graph():
    """Return the FalkorDB graph handle (only valid when backend == 'falkordb')."""
    from falkordb import FalkorDB
    db = FalkorDB(host=FALKORDB_HOST, port=FALKORDB_PORT)
    return db.select_graph(GRAPH_NAME)
