"""Opt-in regressions against a private, read-only snapshot and real embeddings.

Set FRAVENIR_SEARCH_SNAPSHOT and FRAVENIR_QUERY_CACHE explicitly. No runtime
directory is selected automatically; ordinary pytest uses only synthetic DBs.
"""

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from fravenir.core import search
from fravenir.schemas.config import AppConfig, CharacterConfig
from fravenir.storage import paths

CASES = json.loads(Path(__file__).with_name("search_relevance.json").read_text(encoding="utf-8"))[
    "cases"
]


@pytest.mark.parametrize("case_index", range(len(CASES)), ids=[c["query"] for c in CASES])
def test_snapshot_retrieves_direct_topic_at_one(case_index, monkeypatch):
    snapshot = os.environ.get("FRAVENIR_SEARCH_SNAPSHOT")
    cache = os.environ.get("FRAVENIR_QUERY_CACHE")
    if not snapshot or not cache:
        pytest.skip("Set explicit private snapshot and real embedding cache paths")
    data = Path(snapshot).resolve()
    assert data != Path("C:/ProgramData/Fravenir/app/data/main").resolve()
    assert data.is_dir()
    files = sorted(data.glob("*.db")) + sorted(data.glob("*.sqlite"))
    before = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    vectors = np.load(cache, allow_pickle=False)
    assert vectors["queries"].tolist() == [c["query"] for c in CASES]
    config = AppConfig(character=CharacterConfig(id="main"))
    config.embedding.device = "cpu"
    assert str(vectors["embedding_config"]) == config.embedding.model_dump_json()
    embedder = SimpleNamespace(
        encode_query=lambda q: vectors["document"][case_index],
        encode_topic=lambda q: vectors["topic"][case_index],
    )

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 15, 15, tzinfo=UTC)

    monkeypatch.setattr(search, "datetime", Clock)
    monkeypatch.setattr(paths, "data_dir", lambda _: data)
    results = search.memory_search(
        CASES[case_index]["query"], character_id="main", config=config, embedder=embedder
    )
    grades = [CASES[case_index]["relevance"].get(str(r["episode_id"]), 0) for r in results]
    assert grades and grades[0] >= 2
    assert any(g == 3 for g in grades[:5])
    assert {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files} == before
