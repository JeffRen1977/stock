from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..events import StockEvent


@dataclass(frozen=True)
class NarrativeState:
    narrative_id: str
    name: str
    direction: str
    strength: int
    related_symbols: tuple[str, ...]
    supporting_event_ids: tuple[str, ...]
    contradicting_event_ids: tuple[str, ...]
    updated_at: str

    @property
    def related_symbols_json(self) -> str:
        return json.dumps(list(self.related_symbols))

    @property
    def supporting_event_ids_json(self) -> str:
        return json.dumps(list(self.supporting_event_ids))

    @property
    def contradicting_event_ids_json(self) -> str:
        return json.dumps(list(self.contradicting_event_ids))


@dataclass(frozen=True)
class NarrativeDefinition:
    narrative_id: str
    name: str
    keywords: tuple[str, ...]
    symbols: tuple[str, ...]


NARRATIVE_DEFINITIONS = (
    NarrativeDefinition(
        narrative_id="ai_infrastructure",
        name="AI infrastructure",
        keywords=(
            "ai",
            "artificial intelligence",
            "gpu",
            "chip",
            "datacenter",
            "data center",
            "server",
            "accelerator",
        ),
        symbols=("NVDA", "AMD", "MSFT", "GOOGL", "AMZN", "META", "SMCI", "ANET", "VRT"),
    ),
    NarrativeDefinition(
        narrative_id="cloud_capex",
        name="cloud capex",
        keywords=(
            "cloud",
            "capex",
            "capital spending",
            "azure",
            "aws",
            "google cloud",
            "datacenter",
            "data center",
        ),
        symbols=("MSFT", "AMZN", "GOOGL", "META", "NVDA", "VRT", "ANET"),
    ),
    NarrativeDefinition(
        narrative_id="ev_margin_pressure",
        name="EV margin pressure",
        keywords=(
            "ev",
            "electric vehicle",
            "margin",
            "price cut",
            "deliveries",
            "competition",
        ),
        symbols=("TSLA",),
    ),
    NarrativeDefinition(
        narrative_id="rate_cut_expectations",
        name="rate-cut expectations",
        keywords=(
            "fed",
            "rate",
            "rates",
            "rate cut",
            "inflation",
            "cpi",
            "jobs report",
            "treasury",
        ),
        symbols=(),
    ),
    NarrativeDefinition(
        narrative_id="chip_export_controls",
        name="chip export controls",
        keywords=(
            "export control",
            "export controls",
            "china",
            "restriction",
            "ban",
        ),
        symbols=("NVDA", "AMD", "SMCI"),
    ),
    NarrativeDefinition(
        narrative_id="datacenter_power_demand",
        name="datacenter power demand",
        keywords=(
            "power",
            "electricity",
            "energy",
            "grid",
            "cooling",
        ),
        symbols=("VRT", "NVDA", "MSFT", "AMZN", "GOOGL", "ANET"),
    ),
)

POSITIVE_EVENT_TYPES = {"analyst_upgrade", "guidance", "partnership", "product_launch", "earnings"}
NEGATIVE_EVENT_TYPES = {"analyst_downgrade", "sec_or_legal"}


def track_narratives(
    database_path: Path,
    events_by_symbol: dict[str, list[StockEvent]],
    timezone: str,
) -> list[NarrativeState]:
    previous_states = load_narratives(database_path)
    updated_at = datetime.now(ZoneInfo(timezone)).isoformat()
    states = []

    for definition in NARRATIVE_DEFINITIONS:
        matching_events = _matching_events(definition, events_by_symbol)
        supporting_events = [
            event
            for event in matching_events
            if _event_direction(event) == "supporting"
        ]
        contradicting_events = [
            event
            for event in matching_events
            if _event_direction(event) == "contradicting"
        ]
        previous = previous_states.get(definition.narrative_id)
        previous_strength = previous.strength if previous else 0
        strength = max(
            0,
            min(10, previous_strength + len(supporting_events) - len(contradicting_events)),
        )
        direction = _direction(previous_strength, strength, supporting_events, contradicting_events)
        related_symbols = _related_symbols(definition, matching_events, previous)

        if strength == 0 and not matching_events and previous is None:
            continue

        states.append(
            NarrativeState(
                narrative_id=definition.narrative_id,
                name=definition.name,
                direction=direction,
                strength=strength,
                related_symbols=related_symbols,
                supporting_event_ids=tuple(
                    event.dedupe_hash for event in supporting_events
                ),
                contradicting_event_ids=tuple(
                    event.dedupe_hash for event in contradicting_events
                ),
                updated_at=updated_at,
            )
        )

    return states


def load_narratives(database_path: Path) -> dict[str, NarrativeState]:
    if not database_path.exists():
        return {}

    with sqlite3.connect(database_path) as connection:
        table_exists = connection.execute(
            "select name from sqlite_master where type = 'table' and name = 'narratives'"
        ).fetchone()
        if not table_exists:
            return {}

        rows = connection.execute(
            """
            select narrative_id, name, direction, strength, related_symbols,
                   supporting_event_ids, contradicting_event_ids, updated_at
            from narratives
            """
        ).fetchall()

    return {
        row[0]: NarrativeState(
            narrative_id=row[0],
            name=row[1],
            direction=row[2],
            strength=int(row[3] or 0),
            related_symbols=_json_tuple(row[4]),
            supporting_event_ids=_json_tuple(row[5]),
            contradicting_event_ids=_json_tuple(row[6]),
            updated_at=row[7],
        )
        for row in rows
    }


def narratives_by_symbol(narratives: list[NarrativeState]) -> dict[str, list[NarrativeState]]:
    by_symbol: dict[str, list[NarrativeState]] = {}
    for narrative in narratives:
        for symbol in narrative.related_symbols:
            by_symbol.setdefault(symbol, []).append(narrative)
    return by_symbol


def _matching_events(
    definition: NarrativeDefinition,
    events_by_symbol: dict[str, list[StockEvent]],
) -> list[StockEvent]:
    matches = []
    for events in events_by_symbol.values():
        for event in events:
            text = f"{event.headline} {event.summary}".lower()
            if any(_keyword_matches(text, keyword) for keyword in definition.keywords):
                matches.append(event)
    return matches


def _event_direction(event: StockEvent) -> str:
    if event.sentiment == "positive" or event.event_type in POSITIVE_EVENT_TYPES:
        return "supporting"
    if event.sentiment == "negative" or event.event_type in NEGATIVE_EVENT_TYPES:
        return "contradicting"
    return "neutral"


def _direction(
    previous_strength: int,
    strength: int,
    supporting_events: list[StockEvent],
    contradicting_events: list[StockEvent],
) -> str:
    if supporting_events and contradicting_events:
        return "mixed"
    if strength > previous_strength:
        return "strengthening"
    if strength < previous_strength:
        return "weakening"
    return "stable"


def _related_symbols(
    definition: NarrativeDefinition,
    events: list[StockEvent],
    previous: NarrativeState | None,
) -> tuple[str, ...]:
    symbols = set()
    if previous:
        symbols.update(previous.related_symbols)
    for event in events:
        symbols.add(event.symbol)
        symbols.update(event.related_symbols)
    if not symbols:
        symbols.update(definition.symbols)
    return tuple(sorted(symbols))


def _keyword_matches(text: str, keyword: str) -> bool:
    if " " in keyword or "-" in keyword:
        return keyword in text
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None


def _json_tuple(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return ()
    if not isinstance(payload, list):
        return ()
    return tuple(str(item) for item in payload)

