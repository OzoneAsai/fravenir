"""Transient BM25 retrieval for identifiers and Japanese without whitespace.

One normalized Latin identifier is one token; CJK runs use overlapping bigrams.
BM25 is evaluated over eligible episode contents, so no persistent index, schema
migration, tokenizer extension, or stale-index synchronization is required.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

_RUN = re.compile(r"[a-z0-9_]+|[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]+")
_IDENTIFIER = re.compile(r"[a-z0-9_]+\Z")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for run in _RUN.findall(unicodedata.normalize("NFKC", text).casefold()):
        if _IDENTIFIER.fullmatch(run) or len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


def lexical_scores(query: str, documents: dict[int, str]) -> dict[int, float]:
    """BM25/(BM25 + sum(query IDF)) maps scores to [0,1) across queries.

    k1=1.2 and b=.75 are standard BM25 saturation/length-normalization parameters.
    Distinct query tokens avoid boosting repeated query text.
    """
    terms = set(tokenize(query))
    if not terms or not documents:
        return {}
    counts = {ep: Counter(tokenize(text)) for ep, text in documents.items()}
    lengths = {ep: sum(count.values()) for ep, count in counts.items()}
    average = max(sum(lengths.values()) / len(documents), 1.0)
    idf = {
        term: math.log1p((len(counts) - df + 0.5) / (df + 0.5))
        for term in terms
        for df in [sum(term in count for count in counts.values())]
    }
    normalizer = sum(idf.values())
    scores: dict[int, float] = {}
    for ep, count in counts.items():
        norm = 1.2 * (0.25 + 0.75 * lengths[ep] / average)
        score = sum(idf[t] * count[t] * 2.2 / (count[t] + norm) for t in terms if count[t])
        if score:
            scores[ep] = score / (score + normalizer)
    return scores
