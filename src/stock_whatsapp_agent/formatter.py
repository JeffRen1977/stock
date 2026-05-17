from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .events import StockEvent
from .indicators import TechnicalIndicators
from .providers import EarningsEvent, NewsItem, RecommendationTrend, StockQuote, TopGainer
from .reasoning import StockAnalysis
from .sec import SecFiling


def format_daily_message(
    quotes: list[StockQuote],
    news_by_symbol: dict[str, list[NewsItem]],
    top_gainers: list[TopGainer],
    indicators_by_symbol: dict[str, TechnicalIndicators] | None,
    analyses: list[StockAnalysis] | None,
    events_by_symbol: dict[str, list[StockEvent]] | None,
    filings_by_symbol: dict[str, list[SecFiling]] | None,
    recommendations_by_symbol: dict[str, list[RecommendationTrend]] | None,
    earnings_by_symbol: dict[str, list[EarningsEvent]] | None,
    timezone: str,
) -> str:
    now = datetime.now(ZoneInfo(timezone))
    lines = [
        f"US Stock Daily Update - {now:%Y-%m-%d %H:%M %Z}",
        "",
        "Watchlist",
    ]

    for quote in quotes:
        lines.append(
            f"{quote.symbol} {_money(quote.price)} {_signed_percent(quote.change_percent)}"
        )

    if indicators_by_symbol:
        lines.extend(["", "Technical Signals"])
        for quote in quotes:
            indicator = indicators_by_symbol.get(quote.symbol)
            if indicator is None:
                continue
            lines.append(
                f"{quote.symbol} RSI {_number(indicator.rsi_14)} | "
                f"SMA5 {_money(indicator.sma_5)} | "
                f"5D {_signed_percent(indicator.momentum_5d_percent)}"
            )

    lines.extend(["", "Latest News By Stock"])
    for quote in quotes:
        lines.append(quote.symbol)
        items = news_by_symbol.get(quote.symbol, [])
        if not items:
            lines.append("- No major recent news found.")
            lines.append("")
            continue

        for item in items:
            summary = _shorten(item.summary or item.headline, 180)
            line = f"- {item.source}, {item.published_at}: {summary}"
            if item.url:
                line = f"{line} {item.url}"
            lines.append(line)
        lines.append("")

    lines.append("Top Gainers")
    if top_gainers:
        for gainer in top_gainers:
            lines.append(
                f"{gainer.symbol} {_signed_percent(gainer.change_percent)} {_money(gainer.price)}"
            )
    else:
        lines.append("Top gainers were not available from the configured provider.")

    if _has_any_items(events_by_symbol):
        lines.extend(["", "Important Events"])
        for quote in quotes:
            events = (events_by_symbol or {}).get(quote.symbol, [])
            for event in events[:2]:
                lines.append(
                    f"{event.symbol}: {event.event_type}, {event.sentiment}, "
                    f"impact {event.impact_score} - {_shorten(event.summary, 120)}"
                )

    if _has_any_items(filings_by_symbol):
        lines.extend(["", "Recent SEC Filings"])
        for quote in quotes:
            filings = (filings_by_symbol or {}).get(quote.symbol, [])
            for filing in filings[:2]:
                lines.append(f"{quote.symbol}: {filing.form_type} filed {filing.filing_date} - {filing.title}")

    if _has_any_items(recommendations_by_symbol) or _has_any_items(earnings_by_symbol):
        lines.extend(["", "Analyst And Earnings Signals"])
        for quote in quotes:
            recommendation = _latest_recommendation(
                (recommendations_by_symbol or {}).get(quote.symbol, [])
            )
            earnings = (earnings_by_symbol or {}).get(quote.symbol, [])
            if recommendation is None and not earnings:
                continue

            parts = []
            if recommendation:
                buy_count = (recommendation.strong_buy or 0) + (recommendation.buy or 0)
                parts.append(
                    f"analysts {buy_count} buy/strong-buy, "
                    f"{recommendation.hold or 0} hold"
                )
            if earnings:
                parts.append(f"next earnings {earnings[0].date}")
            lines.append(f"{quote.symbol}: {'; '.join(parts)}")

    if analyses:
        lines.extend(["", "Agent Actions"])
        for analysis in analyses:
            lines.append(
                f"{analysis.symbol}: {analysis.stance}, confidence {analysis.confidence}%, "
                f"alert {analysis.alert} - {analysis.action}"
            )

    lines.extend(
        [
            "",
            "Summary",
            _build_summary(quotes, top_gainers),
            "",
            "Note: This is informational only, not financial advice.",
        ]
    )

    return "\n".join(lines).strip()


def _build_summary(quotes: list[StockQuote], top_gainers: list[TopGainer]) -> str:
    positive = [quote for quote in quotes if quote.change_percent is not None and quote.change_percent > 0]
    negative = [quote for quote in quotes if quote.change_percent is not None and quote.change_percent < 0]

    parts = []
    if positive:
        symbols = ", ".join(quote.symbol for quote in positive[:3])
        parts.append(f"Watchlist strength was led by {symbols}.")
    if negative:
        symbols = ", ".join(quote.symbol for quote in negative[:3])
        parts.append(f"Weaker watchlist names included {symbols}.")
    if top_gainers:
        parts.append(f"The largest listed gainer was {top_gainers[0].symbol}.")

    return " ".join(parts) if parts else "No clear watchlist movement summary was available."


def _money(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"${value:,.2f}"


def _signed_percent(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:+.2f}%"


def _number(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.1f}"


def _latest_recommendation(items: list[RecommendationTrend]) -> RecommendationTrend | None:
    return items[0] if items else None


def _has_any_items(values_by_symbol: dict[str, list[Any]] | None) -> bool:
    return any(values_by_symbol.values()) if values_by_symbol else False


def _shorten(value: str, max_length: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max_length - 3].rstrip()}..."
