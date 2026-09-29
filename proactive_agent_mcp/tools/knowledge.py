"""
Grounded knowledge retrieval.

Ranks a small in-repository corpus with **sparse TF-IDF vectors and cosine
similarity**. Documents are tokenised once at import into IDF-weighted term
vectors; a query is projected into the same vector space and scored against
each document by cosine similarity.

This is a lexical method, and it is described as one. It matches on vocabulary
rather than meaning, so a query phrased in different words from the source text
will score poorly. Upgrading the ranking function to dense sentence embeddings
would improve paraphrase recall and is the obvious next step, but the interface
and the scoring contract below would not change.

Retrieval latency is measured with a monotonic clock, not reported as a
constant.
"""

from __future__ import annotations

import math
import re
import time
from collections import Counter
from typing import Any

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_CORPUS: list[dict[str, Any]] = [
    {
        "chunk_id": "kb-rag-001",
        "title": "Enterprise Asset Custody Standard Operating Procedure",
        "content": (
            "All hardware assets provisioned to personnel must include an active "
            "Entra ID primary user assignment, a valid BitLocker recovery key "
            "escrowed in Intune, and a signed physical or digital accountability "
            "form within 5 business days of issue."
        ),
        "keywords": [
            "asset",
            "custody",
            "handover",
            "entra",
            "intune",
            "hardware",
            "accountability",
        ],
        "metadata": {"source": "ITSM-SOP-V4", "section": "3.1"},
    },
    {
        "chunk_id": "kb-rag-002",
        "title": "Agent Autonomous Action Authorization Matrix",
        "content": (
            "Autonomous agents may read queues, validate document schemas, and "
            "pre-populate review forms without human intervention. Modifying "
            "production directory objects or initiating asset status wipe actions "
            "requires explicit human approval authorization."
        ),
        "keywords": [
            "agent",
            "autonomous",
            "human",
            "approval",
            "permission",
            "security",
            "authorization",
        ],
        "metadata": {"source": "SEC-AGENT-GOVERNANCE", "section": "2.4"},
    },
]


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _build_index(
    corpus: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    """
    Pre-compute one normalised TF-IDF vector per document.

    The title is weighted more heavily than the body, and curated keywords are
    weighted highest, so a query naming a concept in the keywords outranks one
    that merely happens to mention the phrase in passing.

    Returns the indexed documents and the corpus-wide IDF table.
    """
    tokenised: list[Counter] = []
    for doc in corpus:
        counts: Counter = Counter()
        for term in _tokenize(doc["title"]):
            counts[term] += 3
        for term in _tokenize(doc["content"]):
            counts[term] += 1
        for term in _tokenize(" ".join(doc["keywords"])):
            counts[term] += 2
        tokenised.append(counts)

    doc_count = len(corpus)

    # Document frequency: in how many documents does each term appear at all.
    document_frequency: Counter = Counter()
    for counts in tokenised:
        document_frequency.update(counts.keys())

    idf = {term: math.log(1.0 + doc_count / freq) for term, freq in document_frequency.items()}

    index: list[dict[str, Any]] = []
    for doc, counts in zip(corpus, tokenised, strict=True):
        total = sum(counts.values())
        vector = {term: (freq / total) * idf[term] for term, freq in counts.items()}
        norm = math.sqrt(sum(weight * weight for weight in vector.values())) or 1.0
        index.append({**doc, "vector": vector, "norm": norm})

    return index, idf


_INDEX, _IDF = _build_index(_CORPUS)


def _query_vector(query: str) -> dict[str, float]:
    """
    Project a query into the same TF-IDF space as the indexed documents.

    Terms absent from the corpus are dropped rather than smoothed in. They can
    never contribute to the dot product, so keeping them would only inflate the
    query norm and deflate every similarity score.
    """
    counts = Counter(term for term in _tokenize(query) if term in _IDF)
    if not counts:
        return {}
    total = sum(counts.values())
    return {term: (freq / total) * _IDF[term] for term, freq in counts.items()}


def _cosine(a: dict[str, float], a_norm: float, b: dict[str, float], b_norm: float) -> float:
    """Cosine similarity of two sparse vectors. Non-negative terms keep this in [0, 1]."""
    if not a or not b:
        return 0.0
    # Iterate the smaller vector; every shared term must exist in both.
    if len(a) > len(b):
        a, b = b, a
    dot = sum(weight * b.get(term, 0.0) for term, weight in a.items())
    if dot == 0.0:
        return 0.0
    return dot / (a_norm * b_norm)


def query_rag_knowledge(
    query: str,
    top_k: int = 3,
    min_score_threshold: float = 0.10,
) -> dict[str, Any]:
    """
    Rank the knowledge corpus against a query by cosine similarity.

    Returns the top ``top_k`` chunks scoring at or above ``min_score_threshold``,
    the measured retrieval latency, and an explicit grounding verdict so the
    caller can tell a confident answer from a weak one.
    """
    started = time.perf_counter()

    q_vector = _query_vector(query)
    q_norm = math.sqrt(sum(weight * weight for weight in q_vector.values())) or 1.0

    scored: list[dict[str, Any]] = []
    for doc in _INDEX:
        similarity = _cosine(q_vector, q_norm, doc["vector"], doc["norm"])
        if similarity >= min_score_threshold:
            scored.append(
                {
                    "chunk_id": doc["chunk_id"],
                    "title": doc["title"],
                    "content": doc["content"],
                    "similarity_score": round(similarity, 4),
                    "metadata": doc["metadata"],
                }
            )

    scored.sort(key=lambda item: item["similarity_score"], reverse=True)
    results = scored[:top_k]
    latency_ms = round((time.perf_counter() - started) * 1000, 4)

    top_score = results[0]["similarity_score"] if results else 0.0
    if not results:
        grounding = "NO_MATCH"
    elif top_score >= 0.35:
        grounding = "CONFIDENT"
    elif top_score >= 0.15:
        grounding = "PARTIAL"
    else:
        grounding = "WEAK"

    return {
        "query": query,
        "retrieval_method": "tf_idf_cosine",
        "corpus_size": len(_INDEX),
        "results_count": len(results),
        "results": results,
        "retrieval_latency_ms": latency_ms,
        "top_score": top_score,
        "min_score_threshold": min_score_threshold,
        "grounding_status": grounding,
        "caveat": (
            "Lexical TF-IDF ranking over a small corpus. Matches vocabulary, not "
            "meaning, so paraphrase recall is limited."
        ),
    }
