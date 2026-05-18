from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..events import StockEvent
from ..providers import StockQuote


@dataclass(frozen=True)
class StockRelationship:
    source_symbol: str
    related_symbol: str
    relationship: str


@dataclass(frozen=True)
class CrossStockObservation:
    observation_id: str
    source_symbol: str
    related_symbol: str
    relationship: str
    reasoning: str
    confidence: int
    direction: str


RELATIONSHIPS = (
    StockRelationship("NVDA", "AMD", "competitor"),
    StockRelationship("NVDA", "SMCI", "beneficiary"),
    StockRelationship("NVDA", "ANET", "beneficiary"),
    StockRelationship("NVDA", "VRT", "beneficiary"),
    StockRelationship("NVDA", "ETN", "beneficiary"),
    StockRelationship("TSLA", "RIVN", "competitor"),
    StockRelationship("TSLA", "GM", "competitor"),
    StockRelationship("TSLA", "F", "competitor"),
    StockRelationship("TSLA", "ALB", "supplier"),
    StockRelationship("MSFT", "AMZN", "competitor"),
    StockRelationship("MSFT", "GOOGL", "competitor"),
    StockRelationship("MSFT", "NVDA", "supplier"),
    StockRelationship("AAPL", "QCOM", "supplier"),
    StockRelationship("AAPL", "AVGO", "supplier"),
    StockRelationship("AAPL", "TSM", "supplier"),
)

HIGH_IMPACT_EVENT_TYPES = {
    "earnings",
    "guidance",
    "partnership",
    "product_launch",
    "sec_or_legal",
}
POSITIVE_RELATIONSHIPS = {"supplier", "beneficiary", "customer", "sector peer"}
NEGATIVE_RELATIONSHIPS = {"competitor", "constraint"}


def generate_cross_stock_observations(
    database_path: Path,
    quotes: list[StockQuote],
    events_by_symbol: dict[str, list[StockEvent]],
) -> list[CrossStockObservation]:
    existing_ids = _existing_observation_ids(database_path)
    observations = []

    for relationship in RELATIONSHIPS:
        source_events = events_by_symbol.get(relationship.source_symbol, [])
        for event in source_events:
            observation = _observation_from_event(relationship, event)
            if observation is not None and observation.observation_id not in existing_ids:
                observations.append(observation)

        quote = _quote_for(quotes, relationship.source_symbol)
        observation = _observation_from_price_move(relationship, quote)
        if observation is not None and observation.observation_id not in existing_ids:
            observations.append(observation)

    return observations


def observations_by_symbol(
    observations: list[CrossStockObservation],
) -> dict[str, list[CrossStockObservation]]:
    by_symbol: dict[str, list[CrossStockObservation]] = {}
    for observation in observations:
        by_symbol.setdefault(observation.related_symbol, []).append(observation)
    return by_symbol


def _observation_from_event(
    relationship: StockRelationship,
    event: StockEvent,
) -> CrossStockObservation | None:
    if event.impact_score < 70 and event.event_type not in HIGH_IMPACT_EVENT_TYPES:
        return None
    if event.sentiment == "neutral" and event.impact_score < 80:
        return None

    direction = _direction_for_relationship(relationship.relationship, event.sentiment)
    confidence = min(
        95,
        event.impact_score + _relationship_confidence_bonus(relationship.relationship),
    )
    reasoning = (
        f"{event.symbol} {event.event_type} event may have a {direction} read-through "
        f"for {relationship.related_symbol} as a {relationship.relationship}: {event.summary}"
    )

    return CrossStockObservation(
        observation_id=_observation_id(
            relationship.source_symbol,
            relationship.related_symbol,
            relationship.relationship,
            event.dedupe_hash,
        ),
        source_symbol=relationship.source_symbol,
        related_symbol=relationship.related_symbol,
        relationship=relationship.relationship,
        reasoning=reasoning,
        confidence=confidence,
        direction=direction,
    )


def _observation_from_price_move(
    relationship: StockRelationship,
    quote: StockQuote | None,
) -> CrossStockObservation | None:
    if quote is None or quote.change_percent is None or abs(quote.change_percent) < 5:
        return None

    source_direction = "positive" if quote.change_percent > 0 else "negative"
    direction = _direction_for_relationship(relationship.relationship, source_direction)
    confidence = min(85, 55 + int(abs(quote.change_percent) * 4))
    reasoning = (
        f"{quote.symbol} moved {quote.change_percent:+.2f}%, suggesting a {direction} "
        f"read-through for {relationship.related_symbol} as a {relationship.relationship}."
    )

    return CrossStockObservation(
        observation_id=_observation_id(
            relationship.source_symbol,
            relationship.related_symbol,
            relationship.relationship,
            f"price:{quote.change_percent:.2f}",
        ),
        source_symbol=relationship.source_symbol,
        related_symbol=relationship.related_symbol,
        relationship=relationship.relationship,
        reasoning=reasoning,
        confidence=confidence,
        direction=direction,
    )


def _direction_for_relationship(relationship: str, source_direction: str) -> str:
    if source_direction == "neutral":
        return "neutral"
    if relationship in POSITIVE_RELATIONSHIPS:
        return source_direction
    if relationship in NEGATIVE_RELATIONSHIPS:
        return "negative" if source_direction == "positive" else "positive"
    return "neutral"


def _relationship_confidence_bonus(relationship: str) -> int:
    if relationship in {"supplier", "beneficiary"}:
        return 8
    if relationship == "competitor":
        return 4
    return 0


def _quote_for(quotes: list[StockQuote], symbol: str) -> StockQuote | None:
    for quote in quotes:
        if quote.symbol == symbol:
            return quote
    return None


def _existing_observation_ids(database_path: Path) -> set[str]:
    if not database_path.exists():
        return set()
    with sqlite3.connect(database_path) as connection:
        table_exists = connection.execute(
            "select name from sqlite_master where type = 'table' and name = 'cross_stock_observations'"
        ).fetchone()
        if not table_exists:
            return set()
        rows = connection.execute(
            "select observation_id from cross_stock_observations"
        ).fetchall()
    return {row[0] for row in rows}


def _observation_id(
    source_symbol: str,
    related_symbol: str,
    relationship: str,
    trigger_id: str,
) -> str:
    base = f"{source_symbol}:{related_symbol}:{relationship}:{trigger_id}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]
