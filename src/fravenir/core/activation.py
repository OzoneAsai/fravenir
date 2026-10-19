"""ACT-R base activation and final score calculation."""

import math
import sqlite3
from datetime import datetime
from typing import Literal


def base_activation(
    conn: sqlite3.Connection,
    node_type: Literal["episode", "entity"],
    node_id: int,
    decay: float,
    now: datetime,
    limit: int = 100,
    *,
    include_search_results: bool = True,
) -> float:
    """Compute B_i = ln(Σ t_k^{-decay}) over access history.

    Returns 0.0 when there is no access history so that new records
    can still surface via cosine similarity and importance weighting.

    Search can exclude legacy result-display sources without rewriting history.
    The default retains compact/explore semantics and existing callers. Filtering
    happens before LIMIT so impressions cannot evict deliberate accesses.
    """
    rows: list[tuple[str]] = conn.execute(
        """
        SELECT accessed_at FROM access_history
        WHERE node_type = ? AND node_id = ?
          AND (? OR source NOT IN ('direct', 'associative', 'self_boost', 'search_impression'))
        ORDER BY accessed_at DESC
        LIMIT ?
        """,
        (node_type, node_id, include_search_results, limit),
    ).fetchall()
    if not rows:
        return 0.0
    total = 0.0
    for (ts_val,) in rows:
        ts = datetime.fromisoformat(ts_val) if isinstance(ts_val, str) else ts_val
        seconds = max((now - ts).total_seconds(), 1.0)
        total += seconds ** (-decay)
    return math.log(total)


def final_score(
    activation: float,
    cosine_sim: float,
    importance: int,
    alpha_sim: float,
    alpha_imp: float,
) -> float:
    """Compute score_i = A_i + α_sim·cosine + α_imp·importance."""
    return activation + alpha_sim * cosine_sim + alpha_imp * importance
