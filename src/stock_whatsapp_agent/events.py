from __future__ import annotations

import json
from dataclasses import dataclass

from .cache import news_item_hash
from .providers import NewsItem


@dataclass(frozen=True)
class StockEvent:
    symbol: str
    event_type: str
    headline: str
    summary: str
    source: str
    published_at: str
    sentiment: str
    confidence: int
    impact_score: int
    related_symbols: tuple[str, ...]
    dedupe_hash: str

    @property
    def related_symbols_json(self) -> str:
        return json.dumps(list(self.related_symbols))


EVENT_RULES = (
    ("analyst_upgrade", ("upgrade", "upgraded", "raises price target", "price target raised")),
    ("analyst_downgrade", ("downgrade", "downgraded", "cuts price target", "price target cut")),
    ("earnings", ("earnings", "eps", "revenue", "profit", "quarterly results")),
    ("guidance", ("guidance", "forecast", "outlook", "raises forecast", "cuts forecast")),
    ("acquisition", ("acquire", "acquisition", "merger", "takeover")),
    ("partnership", ("partnership", "partners with", "collaboration")),
    ("sec_or_legal", ("sec", "investigation", "lawsuit", "probe", "settlement")),
    ("insider_activity", ("insider", "form 4", "director bought", "ceo sold")),
    ("product_launch", ("launch", "unveils", "announces new", "product")),
    ("macro", ("fed", "rate", "cpi", "inflation", "jobs report", "unemployment")),
)

POSITIVE_WORDS = ("beat", "beats", "surge", "jumps", "upgrade", "raises", "growth", "record")
NEGATIVE_WORDS = ("miss", "falls", "drops", "downgrade", "cuts", "weak", "probe", "lawsuit")


def extract_events_from_news(news_by_symbol: dict[str, list[NewsItem]]) -> dict[str, list[StockEvent]]:
    events_by_symbol = {}
    for symbol, items in news_by_symbol.items():
        events = []
        for item in items:
            event = extract_event(item)
            if event is not None:
                events.append(event)
        events_by_symbol[symbol] = events
    return events_by_symbol


def extract_event(item: NewsItem) -> StockEvent | None:
    text = f"{item.headline} {item.summary}".lower()
    event_type = _event_type(text)
    if event_type is None:
        return None

    sentiment = _sentiment(text)
    confidence = _confidence(event_type, sentiment)
    impact_score = _impact_score(event_type, sentiment)
    related_symbols = _related_symbols(text, item.symbol)

    return StockEvent(
        symbol=item.symbol,
        event_type=event_type,
        headline=item.headline,
        summary=item.summary or item.headline,
        source=item.source,
        published_at=item.published_at,
        sentiment=sentiment,
        confidence=confidence,
        impact_score=impact_score,
        related_symbols=related_symbols,
        dedupe_hash=news_item_hash(item),
    )


def _event_type(text: str) -> str | None:
    for event_type, keywords in EVENT_RULES:
        if any(keyword in text for keyword in keywords):
            return event_type
    return None


def _sentiment(text: str) -> str:
    positive = sum(1 for word in POSITIVE_WORDS if word in text)
    negative = sum(1 for word in NEGATIVE_WORDS if word in text)
    if positive > negative:
        return "positive"
    if negative > positive:
        return "negative"
    return "neutral"


def _confidence(event_type: str, sentiment: str) -> int:
    base = 70 if event_type in {"earnings", "sec_or_legal", "insider_activity"} else 60
    if sentiment != "neutral":
        base += 5
    return min(base, 90)


def _impact_score(event_type: str, sentiment: str) -> int:
    impact_by_type = {
        "earnings": 75,
        "guidance": 80,
        "sec_or_legal": 80,
        "insider_activity": 65,
        "analyst_upgrade": 55,
        "analyst_downgrade": 55,
        "acquisition": 70,
        "partnership": 55,
        "product_launch": 50,
        "macro": 65,
    }
    impact = impact_by_type.get(event_type, 45)
    if sentiment in {"positive", "negative"}:
        impact += 5
    return min(impact, 95)


def _related_symbols(text: str, own_symbol: str) -> tuple[str, ...]:
    candidates = ("NVDA", "AMD", "MSFT", "AAPL", "TSLA", "GOOGL", "AMZN", "META", "SMCI", "ANET", "VRT")
    found = [symbol for symbol in candidates if symbol != own_symbol and symbol.lower() in text]
    return tuple(found)
