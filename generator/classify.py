"""Topic classification and relevance scoring.

An event is included only when it clears a relevance threshold. The scorer is
deliberately keyword-based rather than embedding-based: it must be explainable,
cheap enough to run nightly with no API key, and reviewable by the user.
"""
from __future__ import annotations

import re

# Phrases are matched against a lowercased haystack with word boundaries.
# Weight meaning: 6 = this event IS about streaming/data, 3 = strong adjacent
# signal, 1 = weak/ambiguous signal (never enough alone).

TOPIC_RULES: dict[str, list[tuple[str, int]]] = {
    "Streaming & Kafka": [
        ("apache kafka", 6), ("kafka", 6), ("ksqldb", 6), ("kafka connect", 6),
        ("apache flink", 6), ("flink", 6), ("debezium", 6), ("apache pulsar", 6),
        ("pulsar", 5), ("stream processing", 6), ("data streaming", 6),
        ("event streaming", 6), ("streaming data", 5), ("streaming analytics", 5),
        ("real-time data", 5), ("realtime data", 5), ("event-driven", 5),
        ("change data capture", 5), ("amazon kinesis", 5), ("kinesis", 5),
        ("redpanda", 5), ("materialize", 4), ("risingwave", 4), ("streaming", 3),
        ("kafka streams", 6), ("flink sql", 6), ("structured streaming", 5),
        ("event driven", 5), ("streaming platform", 5), ("confluent", 5),
    ],
    "Lakehouse & Table Formats": [
        ("apache iceberg", 6), ("iceberg", 5), ("apache hudi", 6), ("hudi", 5),
        ("delta lake", 6), ("lakehouse", 6), ("open table format", 6),
        ("data lake", 4), ("parquet", 3), ("polars", 3), ("duckdb", 3),
    ],
    "Data Engineering": [
        ("data engineering", 5), ("data engineer", 5), ("data platform", 5),
        ("data infrastructure", 5), ("data pipeline", 4), ("apache airflow", 5),
        ("airflow", 4), ("dbt", 4), ("dagster", 4), ("data orchestration", 4),
        ("etl", 3), ("elt", 3), ("data mesh", 5), ("data quality", 3),
        ("apache spark", 4), ("spark", 3), ("databricks", 5), ("snowflake", 4),
        ("big data", 4), ("dataops", 3), ("data ops", 3), ("data observability", 4),
        ("modern data stack", 5), ("data governance", 3), ("data architect", 4),
    ],
    "Analytics & Warehousing": [
        ("analytics", 3), ("data warehouse", 4), ("warehousing", 4), ("olap", 4),
        ("clickhouse", 4), ("apache druid", 4), ("apache pinot", 4),
        ("bigquery", 3), ("snowflake", 4), ("business intelligence", 3),
        ("data analytics", 4), ("real-time analytics", 5),
    ],
    "Data & AI": [
        ("data + ai", 4), ("data and ai", 4), ("ml platform", 3),
        ("feature store", 4), ("vector database", 3), ("rag", 2),
        ("machine learning platform", 3), ("generative ai", 2), ("llm", 2),
    ],
}

# Noise guard. A meetup search returns Japanese-language groups and yoga
# classes; those must never clear the threshold on a generic word like "data".
NEGATIVE_RULES: list[str] = [
    "japanese", "chinese language", "spanish", "french language", "language exchange",
    "yoga", "fitness", "running club", "hiking", "photography", "cooking",
    "real estate", "crypto trading", "forex", "insurance", "recruiting",
    "job fair", "career fair", "sales", "marketing", "seo", "startup pitch night",
    "book club", "board games", "wine", "beer tasting", "speed dating",
    "meditation", "mindfulness", "astrology", "tattoo", "hair", "makeup",
    "kids", "toddler", "pet ", "dog walking", "fantasy football",
    # course / job-hunting ads that dress up in data vocabulary
    "job ready", "job-ready", "in 10 weeks", "in 8 weeks", "in 12 weeks",
    "in 6 weeks", "bootcamp", "crash course", "training course", "get hired",
    "salary", "placements", "placement assistance", "interview prep",
    "certification course", "learn from scratch", "zero to hero",
]

# Words too generic to carry relevance on their own.
STOPWORD_ONLY = {"data", "ai", "cloud", "tech", "developer", "software", "engineering"}

WEIGHTS = {"name": 2.0, "tags": 1.5, "description": 0.6, "url": 0.5, "location": 0.0}

# A single strong hit in the name is enough; weaker signals must accumulate.
RELEVANCE_THRESHOLD = 6.0


def _haystacks(name: str, url: str, description: str, tags: list) -> dict:
    return {
        "name": (name or "").lower(),
        "url": (url or "").lower(),
        "description": (description or "").lower(),
        "tags": " ".join(str(t) for t in (tags or [])).lower(),
    }


def _hits(text: str, phrase: str) -> bool:
    """Word-boundary match tolerant of plurals and space/hyphen variants.

    A plain substring match silently drops recall: "open table format" must
    match "Open Table Formats", and "real time data" must match "real-time
    data". Both variants appear constantly in real event titles.
    """
    parts = [re.escape(p) for p in phrase.split()]
    if not parts:
        return False
    pattern = r"(?<![a-z0-9])" + r"[\s\-]+".join(parts) + r"s?(?![a-z0-9])"
    return re.search(pattern, text) is not None


def score_event(name: str, url: str, description: str, tags: list) -> tuple[float, list, list]:
    """Return (score, matched_keywords, topics)."""
    hay = _haystacks(name, url, description, tags)
    blob = " ".join(hay.values())

    for bad in NEGATIVE_RULES:
        if bad in blob:
            return 0.0, [], []

    score = 0.0
    matched: list[str] = []
    topics: list[str] = []

    for topic, rules in TOPIC_RULES.items():
        topic_best = 0.0
        for phrase, weight in rules:
            best_mult = 0.0
            for field, mult in WEIGHTS.items():
                if mult and _hits(hay[field], phrase):
                    best_mult = max(best_mult, mult)
            if best_mult:
                contribution = weight * best_mult
                topic_best = max(topic_best, contribution)
                if phrase not in matched:
                    matched.append(phrase)
        if topic_best > 0:
            topics.append(topic)
            score += topic_best

    # A lone weak signal ("analytics") must not qualify on its own.
    if score and not any(m not in STOPWORD_ONLY for m in matched):
        return 0.0, [], []
    if all(m in STOPWORD_ONLY for m in matched) and matched:
        return 0.0, [], []

    return round(score, 2), matched, topics


def is_relevant(score: float) -> bool:
    return score >= RELEVANCE_THRESHOLD
