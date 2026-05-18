from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .events import StockEvent


@dataclass(frozen=True)
class MemoryRetrieval:
    symbol: str
    memory_type: str
    retrieved_id: str
    reason: str


@dataclass(frozen=True)
class MemoryContext:
    symbol: str
    prior_stance: str | None
    prior_confidence: int | None
    recent_alert_count: int
    recent_event_count: int
    repeated_event_count: int
    changed_since_previous: str
    retrievals: tuple[MemoryRetrieval, ...]


def build_memory_contexts(
    database_path: Path,
    symbols: tuple[str, ...],
    events_by_symbol: dict[str, list[StockEvent]],
) -> dict[str, MemoryContext]:
    if not database_path.exists():
        return {symbol: _empty_context(symbol) for symbol in symbols}

    contexts = {}
    with sqlite3.connect(database_path) as connection:
        for symbol in symbols:
            contexts[symbol] = _build_memory_context(connection, symbol, events_by_symbol.get(symbol, []))
    return contexts


def _build_memory_context(
    connection: sqlite3.Connection,
    symbol: str,
    current_events: list[StockEvent],
) -> MemoryContext:
    retrievals: list[MemoryRetrieval] = []

    prior_analysis = get_recent_analyses(connection, symbol, days=7, limit=1)
    prior_stance = prior_analysis[0]["stance"] if prior_analysis else None
    prior_confidence = prior_analysis[0]["confidence"] if prior_analysis else None
    if prior_analysis:
        retrievals.append(
            MemoryRetrieval(
                symbol=symbol,
                memory_type="analysis",
                retrieved_id=str(prior_analysis[0]["run_id"]),
                reason="latest prior analysis within 7 days",
            )
        )

    recent_events = get_recent_events(connection, symbol, days=14)
    if recent_events:
        retrievals.append(
            MemoryRetrieval(
                symbol=symbol,
                memory_type="events",
                retrieved_id=str(len(recent_events)),
                reason="recent events within 14 days",
            )
        )

    open_alerts = get_open_alerts(connection, symbol, days=7)
    if open_alerts:
        retrievals.append(
            MemoryRetrieval(
                symbol=symbol,
                memory_type="alerts",
                retrieved_id=str(len(open_alerts)),
                reason="recent alert decisions within 7 days",
            )
        )

    active_narratives = get_active_narratives(connection, symbol)
    if active_narratives:
        retrievals.append(
            MemoryRetrieval(
                symbol=symbol,
                memory_type="narratives",
                retrieved_id=str(len(active_narratives)),
                reason="active narrative placeholders",
            )
        )

    previous_hashes = {event["dedupe_hash"] for event in recent_events if event["dedupe_hash"]}
    repeated_event_count = sum(1 for event in current_events if event.dedupe_hash in previous_hashes)
    changed_since_previous = _changed_since_previous(
        prior_analysis=prior_analysis,
        current_events=current_events,
        repeated_event_count=repeated_event_count,
    )

    return MemoryContext(
        symbol=symbol,
        prior_stance=prior_stance,
        prior_confidence=prior_confidence,
        recent_alert_count=len(open_alerts),
        recent_event_count=len(recent_events),
        repeated_event_count=repeated_event_count,
        changed_since_previous=changed_since_previous,
        retrievals=tuple(retrievals),
    )


def get_recent_analyses(
    connection: sqlite3.Connection,
    symbol: str,
    days: int,
    limit: int = 5,
) -> list[dict]:
    cutoff = _cutoff(days)
    rows = connection.execute(
        """
        select a.run_id, a.symbol, a.stance, a.confidence, a.alert, a.rationale, r.generated_at
        from analyses a
        join runs r on r.id = a.run_id
        where a.symbol = ? and r.generated_at >= ?
        order by r.generated_at desc
        limit ?
        """,
        (symbol, cutoff, limit),
    ).fetchall()
    return [_row_dict(row, ("run_id", "symbol", "stance", "confidence", "alert", "rationale", "generated_at")) for row in rows]


def get_recent_events(connection: sqlite3.Connection, symbol: str, days: int) -> list[dict]:
    cutoff = _cutoff(days)
    rows = connection.execute(
        """
        select e.run_id, e.symbol, e.event_type, e.dedupe_hash, e.impact_score, r.generated_at
        from events e
        join runs r on r.id = e.run_id
        where e.symbol = ? and r.generated_at >= ?
        order by r.generated_at desc
        """,
        (symbol, cutoff),
    ).fetchall()
    return [_row_dict(row, ("run_id", "symbol", "event_type", "dedupe_hash", "impact_score", "generated_at")) for row in rows]


def get_open_alerts(connection: sqlite3.Connection, symbol: str, days: int) -> list[dict]:
    cutoff = _cutoff(days)
    rows = connection.execute(
        """
        select a.run_id, a.symbol, a.alert, a.action, r.generated_at
        from analyses a
        join runs r on r.id = a.run_id
        where a.symbol = ? and a.alert = 'yes' and r.generated_at >= ?
        order by r.generated_at desc
        """,
        (symbol, cutoff),
    ).fetchall()
    return [_row_dict(row, ("run_id", "symbol", "alert", "action", "generated_at")) for row in rows]


def get_active_narratives(connection: sqlite3.Connection, symbol: str) -> list[dict]:
    table_exists = connection.execute(
        "select name from sqlite_master where type = 'table' and name = 'narratives'"
    ).fetchone()
    if not table_exists:
        return []
    rows = connection.execute(
        """
        select narrative_id, name, direction, strength
        from narratives
        where related_symbols like ?
        """,
        (f"%{symbol}%",),
    ).fetchall()
    return [_row_dict(row, ("narrative_id", "name", "direction", "strength")) for row in rows]


def flatten_retrievals(contexts: dict[str, MemoryContext]) -> list[MemoryRetrieval]:
    retrievals = []
    for context in contexts.values():
        retrievals.extend(context.retrievals)
    return retrievals


def _changed_since_previous(
    prior_analysis: list[dict],
    current_events: list[StockEvent],
    repeated_event_count: int,
) -> str:
    if not prior_analysis and current_events:
        return "new events with no prior analysis"
    if current_events and repeated_event_count == len(current_events):
        return "continuing from prior runs"
    if current_events:
        return "new event information"
    if prior_analysis:
        return "no new structured events since prior run"
    return "no prior memory"


def _cutoff(days: int) -> str:
    return (datetime.utcnow() - timedelta(days=days)).isoformat()


def _empty_context(symbol: str) -> MemoryContext:
    return MemoryContext(
        symbol=symbol,
        prior_stance=None,
        prior_confidence=None,
        recent_alert_count=0,
        recent_event_count=0,
        repeated_event_count=0,
        changed_since_previous="no prior memory",
        retrievals=(),
    )


def _row_dict(row: tuple, keys: tuple[str, ...]) -> dict:
    return dict(zip(keys, row))
