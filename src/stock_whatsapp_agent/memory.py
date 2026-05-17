from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .events import StockEvent
from .indicators import TechnicalIndicators
from .providers import EarningsEvent, HistoricalBar, NewsItem, RecommendationTrend, StockQuote, TopGainer
from .reasoning import StockAnalysis


def save_daily_memory(
    quotes: list[StockQuote],
    news_by_symbol: dict[str, list[NewsItem]],
    top_gainers: list[TopGainer],
    history_by_symbol: dict[str, list[HistoricalBar]],
    indicators_by_symbol: dict[str, TechnicalIndicators],
    analyses: list[StockAnalysis],
    events_by_symbol: dict[str, list[StockEvent]],
    recommendations_by_symbol: dict[str, list[RecommendationTrend]] | None,
    earnings_by_symbol: dict[str, list[EarningsEvent]] | None,
    message: str,
    timezone: str,
    memory_dir: Path,
) -> Path:
    now = datetime.now(ZoneInfo(timezone))
    day_dir = memory_dir / f"{now:%Y-%m-%d}"
    day_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "generated_at": now.isoformat(),
        "quotes": [asdict(quote) for quote in quotes],
        "news_by_symbol": {
            symbol: [asdict(item) for item in items]
            for symbol, items in news_by_symbol.items()
        },
        "top_gainers": [asdict(gainer) for gainer in top_gainers],
        "history_by_symbol": {
            symbol: [asdict(bar) for bar in bars]
            for symbol, bars in history_by_symbol.items()
        },
        "technical_indicators": {
            symbol: asdict(indicator)
            for symbol, indicator in indicators_by_symbol.items()
        },
        "analyses": [asdict(analysis) for analysis in analyses],
        "events_by_symbol": {
            symbol: [asdict(event) for event in events]
            for symbol, events in events_by_symbol.items()
        },
        "recommendations_by_symbol": {
            symbol: [asdict(item) for item in items]
            for symbol, items in (recommendations_by_symbol or {}).items()
        },
        "earnings_by_symbol": {
            symbol: [asdict(item) for item in items]
            for symbol, items in (earnings_by_symbol or {}).items()
        },
        "message": message,
    }

    json_path = day_dir / "stock_update.json"
    md_path = day_dir / "stock_update.md"

    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(f"# Stock Update - {now:%Y-%m-%d}\n\n```text\n{message}\n```\n", encoding="utf-8")

    return md_path
