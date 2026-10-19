"""sqlite-vec wrapper for episode vector storage and KNN search."""

import sqlite3

import numpy as np
import sqlite_vec
from numpy.typing import NDArray


def upsert_episode_vector(
    vdb_conn: sqlite3.Connection,
    episode_id: int,
    vector: NDArray[np.float32],
) -> None:
    """Insert or replace an episode embedding in vdb_memories."""
    blob = sqlite_vec.serialize_float32(vector.tolist())
    # sqlite-vec virtual tables do not support INSERT OR REPLACE; use DELETE + INSERT
    vdb_conn.execute("DELETE FROM vdb_memories WHERE episode_id = ?", (episode_id,))
    vdb_conn.execute(
        "INSERT INTO vdb_memories(episode_id, embedding) VALUES (?, ?)",
        (episode_id, blob),
    )
    vdb_conn.commit()


def upsert_entity_vector(
    vdb_conn: sqlite3.Connection,
    entity_id: int,
    vector: NDArray[np.float32],
) -> None:
    """Insert or replace an entity embedding in vdb_entities."""
    blob = sqlite_vec.serialize_float32(vector.tolist())
    vdb_conn.execute("DELETE FROM vdb_entities WHERE entity_id = ?", (entity_id,))
    vdb_conn.execute(
        "INSERT INTO vdb_entities(entity_id, embedding) VALUES (?, ?)",
        (entity_id, blob),
    )
    vdb_conn.commit()


def upsert_relation_vector(
    vdb_conn: sqlite3.Connection,
    relation_id: int,
    vector: NDArray[np.float32],
) -> None:
    """Insert or replace a relation embedding in vdb_relations."""
    blob = sqlite_vec.serialize_float32(vector.tolist())
    vdb_conn.execute("DELETE FROM vdb_relations WHERE relation_id = ?", (relation_id,))
    vdb_conn.execute(
        "INSERT INTO vdb_relations(relation_id, embedding) VALUES (?, ?)",
        (relation_id, blob),
    )
    vdb_conn.commit()


def search_episodes_by_vector(
    vdb_conn: sqlite3.Connection,
    query_vector: NDArray[np.float32],
    top_k: int,
) -> list[tuple[int, float]]:
    """Return [(episode_id, l2_distance)] ordered by ascending L2 distance."""
    blob = sqlite_vec.serialize_float32(query_vector.tolist())
    rows: list[tuple[int, float]] = vdb_conn.execute(
        """
        SELECT episode_id, distance
        FROM vdb_memories
        WHERE embedding MATCH ?
          AND k = ?
        ORDER BY distance
        """,
        (blob, top_k),
    ).fetchall()
    return rows


def search_entities_by_vector(
    vdb_conn: sqlite3.Connection,
    query_vector: NDArray[np.float32],
    top_k: int,
) -> list[tuple[int, float]]:
    """Return [(entity_id, l2_distance)] ordered by ascending L2 distance."""
    blob = sqlite_vec.serialize_float32(query_vector.tolist())
    rows: list[tuple[int, float]] = vdb_conn.execute(
        """
        SELECT entity_id, distance
        FROM vdb_entities
        WHERE embedding MATCH ?
          AND k = ?
        ORDER BY distance
        """,
        (blob, top_k),
    ).fetchall()
    return rows


def l2_to_cosine(l2_distance: float) -> float:
    """Convert L2 distance of L2-normalised vectors to cosine similarity.

    For unit vectors: cosine_sim = 1 - l2^2 / 2
    Clamped to [0, 1] to guard against floating-point rounding.
    """
    return float(np.clip(1.0 - (l2_distance**2) / 2.0, 0.0, 1.0))


def episode_cosines(
    conn: sqlite3.Connection,
    query: NDArray[np.float32],
    episode_ids: set[int],
) -> dict[int, float]:
    """Score lexical/graph candidates against their own stored vectors.

    These nodes need not be in the initial KNN window. Missing vectors remain
    missing (callers must not substitute a seed's similarity).
    """
    result: dict[int, float] = {}
    ids = sorted(episode_ids)
    query_norm = float(np.linalg.norm(query))
    for offset in range(0, len(ids), 400):
        batch = ids[offset : offset + 400]
        marks = ",".join("?" for _ in batch)
        rows = conn.execute(
            f"SELECT episode_id, embedding FROM vdb_memories WHERE episode_id IN ({marks})",
            batch,
        ).fetchall()
        for ep_id, blob in rows:
            vec = np.frombuffer(blob, dtype=np.float32)
            norm = float(np.linalg.norm(vec)) * query_norm
            result[ep_id] = float(np.clip(np.dot(query, vec) / norm, 0.0, 1.0)) if norm else 0.0
    return result
