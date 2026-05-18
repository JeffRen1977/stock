from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from .events import StockEvent
from .providers import NewsItem
from .sec import SecFiling
from .skills.narrative_tracking import NarrativeState

if TYPE_CHECKING:
    from .reasoning import StockAnalysis


VECTOR_DIMENSIONS = 64
MAX_SUMMARY_LENGTH = 320


@dataclass(frozen=True)
class VectorMemoryRecord:
    memory_id: str
    symbol: str
    memory_type: str
    summary: str
    metadata: dict[str, str]
    created_at: str


@dataclass(frozen=True)
class RetrievedVectorMemory:
    symbol: str
    memory_type: str
    summary: str
    similarity: float
    created_at: str


def retrieve_vector_memories(
    database_path: Path,
    provider: str,
    symbol: str,
    query: str,
    limit: int,
) -> list[RetrievedVectorMemory]:
    _ensure_supported_provider(provider)
    if limit <= 0 or not database_path.exists():
        return []

    query_vector = _embed(query)
    with sqlite3.connect(database_path) as connection:
        _create_vector_tables(connection)
        rows = connection.execute(
            """
            select symbol, memory_type, summary, vector_json, created_at
            from semantic_memories
            where symbol = ? or symbol = '*'
            """,
            (symbol,),
        ).fetchall()

    scored = []
    for row in rows:
        vector = _json_vector(row[3])
        similarity = _cosine_similarity(query_vector, vector)
        if similarity <= 0:
            continue
        scored.append(
            RetrievedVectorMemory(
                symbol=row[0],
                memory_type=row[1],
                summary=row[2],
                similarity=similarity,
                created_at=row[4],
            )
        )

    return sorted(scored, key=lambda item: item.similarity, reverse=True)[:limit]


def save_vector_memories(
    database_path: Path,
    provider: str,
    timezone: str,
    news_by_symbol: dict[str, list[NewsItem]],
    events_by_symbol: dict[str, list[StockEvent]],
    filings_by_symbol: dict[str, list[SecFiling]],
    analyses: list[StockAnalysis],
    narratives: list[NarrativeState],
) -> int:
    _ensure_supported_provider(provider)
    records = build_vector_memory_records(
        timezone=timezone,
        news_by_symbol=news_by_symbol,
        events_by_symbol=events_by_symbol,
        filings_by_symbol=filings_by_symbol,
        analyses=analyses,
        narratives=narratives,
    )
    if not records:
        return 0

    database_path.parent.mkdir(parents=True, exist_ok=True)
    inserted_count = 0
    with sqlite3.connect(database_path) as connection:
        _create_vector_tables(connection)
        for record in records:
            cursor = connection.execute(
                """
                insert or ignore into semantic_memories(
                    memory_id, symbol, memory_type, summary, metadata_json, vector_json, created_at
                )
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.memory_id,
                    record.symbol,
                    record.memory_type,
                    record.summary,
                    json.dumps(record.metadata, sort_keys=True),
                    json.dumps(_embed(record.summary)),
                    record.created_at,
                ),
            )
            inserted_count += max(cursor.rowcount, 0)
    return inserted_count


def build_vector_memory_records(
    timezone: str,
    news_by_symbol: dict[str, list[NewsItem]],
    events_by_symbol: dict[str, list[StockEvent]],
    filings_by_symbol: dict[str, list[SecFiling]],
    analyses: list[StockAnalysis],
    narratives: list[NarrativeState],
) -> list[VectorMemoryRecord]:
    created_at = datetime.now(ZoneInfo(timezone)).isoformat()
    records = []

    for symbol, events in events_by_symbol.items():
        for event in events:
            records.append(
                _record(
                    symbol=symbol,
                    memory_type="event",
                    summary=f"{event.symbol} {event.event_type}: {event.summary}",
                    metadata={"dedupe_hash": event.dedupe_hash, "source": event.source},
                    created_at=created_at,
                )
            )

    for symbol, filings in filings_by_symbol.items():
        for filing in filings:
            records.append(
                _record(
                    symbol=symbol,
                    memory_type="filing",
                    summary=f"{filing.symbol} filed {filing.form_type}: {filing.title}",
                    metadata={"accession_number": filing.accession_number},
                    created_at=created_at,
                )
            )

    for analysis in analyses:
        records.append(
            _record(
                symbol=analysis.symbol,
                memory_type="daily_analysis",
                summary=(
                    f"{analysis.symbol} {analysis.stance}, alert {analysis.alert_level} "
                    f"score {analysis.alert_score}: {analysis.rationale}"
                ),
                metadata={"alert_level": analysis.alert_level},
                created_at=created_at,
            )
        )

    for narrative in narratives:
        symbol = narrative.related_symbols[0] if narrative.related_symbols else "*"
        records.append(
            _record(
                symbol=symbol,
                memory_type="narrative",
                summary=(
                    f"{narrative.name} narrative is {narrative.direction} "
                    f"with strength {narrative.strength}/10"
                ),
                metadata={"narrative_id": narrative.narrative_id},
                created_at=created_at,
            )
        )

    return records


def semantic_query_for_symbol(
    symbol: str,
    news_items: list[NewsItem],
    events: list[StockEvent],
    narratives: list[NarrativeState],
) -> str:
    parts = [symbol]
    parts.extend(item.headline for item in news_items[:3])
    parts.extend(event.summary for event in events[:3])
    parts.extend(narrative.name for narrative in narratives[:3])
    return " ".join(parts)


def _record(
    symbol: str,
    memory_type: str,
    summary: str,
    metadata: dict[str, str],
    created_at: str,
) -> VectorMemoryRecord:
    compact_summary = _compact(summary)
    memory_id = _memory_id(symbol, memory_type, compact_summary)
    return VectorMemoryRecord(
        memory_id=memory_id,
        symbol=symbol,
        memory_type=memory_type,
        summary=compact_summary,
        metadata=metadata,
        created_at=created_at,
    )


def _create_vector_tables(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        create table if not exists semantic_memories (
            memory_id text primary key,
            symbol text,
            memory_type text,
            summary text,
            metadata_json text,
            vector_json text,
            created_at text
        )
        """
    )


def _ensure_supported_provider(provider: str) -> None:
    if provider.lower() not in {"sqlite", "local"}:
        raise ValueError("Only sqlite vector memory is currently supported")


def _compact(value: str) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= MAX_SUMMARY_LENGTH:
        return normalized
    return f"{normalized[: MAX_SUMMARY_LENGTH - 3].rstrip()}..."


def _embed(text: str) -> list[float]:
    vector = [0.0] * VECTOR_DIMENSIONS
    for token in _tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:2], "big") % VECTOR_DIMENSIONS
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vector[index] += sign
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return vector
    return [value / magnitude for value in vector]


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2 and not token.isdigit()
    ]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(left_value * right_value for left_value, right_value in zip(left, right))


def _json_vector(value: str) -> list[float]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [float(item) for item in payload]


def _memory_id(symbol: str, memory_type: str, summary: str) -> str:
    base = f"{symbol}:{memory_type}:{summary}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:24]
