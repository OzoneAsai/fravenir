"""Read-only local snapshot evaluation. See docs/operations/search-relevance.md.

The cache contains real query embeddings (never synthetic replacements). No memory
or access data is written. Baseline is loaded from git, not from production imports.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import subprocess
import time
import types
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np

from fravenir.core import search
from fravenir.embedding import Embedder
from fravenir.schemas.config import AppConfig, CharacterConfig
from fravenir.storage import paths
from fravenir.storage.vector import l2_to_cosine, search_episodes_by_vector

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 15, 15, 0, tzinfo=UTC)


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


def metrics(ids, judgments):
    grades = [int(judgments.get(str(i), 0)) for i in ids[:5]]
    # Hit/MRR require a direct answer/topic (grade >=2); context alone is insufficient.
    ranks = [i + 1 for i, grade in enumerate(grades) if grade >= 2]
    ideal = sorted(judgments.values(), reverse=True)[:5]

    def dcg(values):
        return sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(values))

    return {
        "hit1": float(bool(ranks) and ranks[0] == 1),
        "hit5": float(bool(ranks)),
        "answer_hit1": float(bool(grades) and grades[0] == 3),
        "mrr5": 1 / ranks[0] if ranks else 0.0,
        "ndcg5": dcg(grades) / dcg(ideal),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--build-cache", action="store_true", help="Encode real queries once")
    parser.add_argument("--baseline", help="Git commit containing old search implementation")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lexical-weight", type=float)
    parser.add_argument("--no-graph", action="store_true")
    args = parser.parse_args()
    data = args.data.resolve()
    if data == Path("C:/ProgramData/Fravenir/app/data/main").resolve():
        parser.error("Use an isolated snapshot, not the live production directory")
    files = list(data.glob("*.sqlite")) + list(data.glob("*.db"))

    def digest():
        return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files}

    before = digest()
    connect = sqlite3.connect

    def readonly(database, *a, **kw):
        database = str(database)
        if database == ":memory:":
            return connect(database, *a, **kw)
        if database.startswith("file:"):
            if "mode=ro" not in database:
                raise ValueError("Only read-only database connections permitted")
        else:
            database = Path(database).resolve().as_uri() + "?mode=ro"
        kw["uri"] = True
        return connect(database, *a, **kw)

    module = search
    if args.baseline:
        source = subprocess.check_output(
            ["git", "show", f"{args.baseline}:src/fravenir/core/search.py"], cwd=ROOT
        ).decode("utf-8")
        module = types.ModuleType("baseline_search")
        exec(compile(source, "<git-baseline-search>", "exec"), module.__dict__)
    cases = json.loads((ROOT / "tests/golden/search_relevance.json").read_text(encoding="utf-8"))[
        "cases"
    ]
    config = AppConfig(character=CharacterConfig(id="main"))
    config.embedding.device = "cpu"
    queries = [case["query"] for case in cases]
    if args.build_cache:
        import torch

        torch.set_num_threads(4)
        encoder = Embedder(config.embedding)
        args.cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez(
            args.cache,
            document=np.stack([encoder.encode_query(q) for q in queries]),
            topic=np.stack([encoder.encode_topic(q) for q in queries]),
            queries=np.array(queries),
            embedding_config=np.array(config.embedding.model_dump_json()),
        )
    vectors = np.load(args.cache, allow_pickle=False)
    if vectors["queries"].tolist() != queries:
        parser.error("Cached query order/content differs from relevance fixture")
    if str(vectors["embedding_config"]) != config.embedding.model_dump_json():
        parser.error("Cached embedding configuration differs from evaluation configuration")
    if args.lexical_weight is not None:
        config.search.lexical_weight = args.lexical_weight
    if args.no_graph:
        config.search.graph_max_candidates = 0
    results = []
    with (
        patch.object(paths, "data_dir", return_value=data),
        patch.object(sqlite3, "connect", side_effect=readonly),
        patch.object(module, "datetime", Clock),
    ):
        if args.baseline:
            module._record_access = lambda *a: None
        for i, case in enumerate(cases):
            embedder = types.SimpleNamespace(
                encode_query=lambda q, i=i: vectors["document"][i],
                encode_topic=lambda q, i=i: vectors["topic"][i],
            )
            started = time.perf_counter()
            ranked = module.memory_search(
                case["query"], limit=5, character_id="main", config=config, embedder=embedder
            )
            elapsed = time.perf_counter() - started
            conn = module._open_vdb(str(data / "vdb_memories.db"))
            direct = search_episodes_by_vector(conn, vectors["document"][i], 20)
            conn.close()
            ids = [r["episode_id"] for r in ranked]
            results.append(
                {
                    "query": case["query"],
                    "ids": ids,
                    "retrieval_ms": elapsed * 1000,
                    "metrics": metrics(ids, case["relevance"]),
                    "vector_candidates": [
                        {"id": ep, "cosine": l2_to_cosine(d)} for ep, d in direct
                    ],
                    "ranking": [
                        {
                            k: v
                            for k, v in row.items()
                            if k
                            not in {"content", "valid_from", "valid_to", "created_at", "supersedes"}
                        }
                        for row in ranked
                    ],
                }
            )
    assert digest() == before, "Snapshot changed during evaluation"
    aggregate = {
        key: sum(r["metrics"][key] for r in results) / len(results) for key in results[0]["metrics"]
    }
    report = {
        "baseline": args.baseline,
        "now": NOW.isoformat(),
        "snapshot_sha256": before,
        "config": config.model_dump(),
        "embedding_cache_sha256": hashlib.sha256(args.cache.read_bytes()).hexdigest(),
        "metrics": aggregate,
        "cases": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(aggregate))
    for r in results:
        print(r["query"], r["ids"], r["metrics"])


if __name__ == "__main__":
    main()
