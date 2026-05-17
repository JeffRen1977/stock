from __future__ import annotations

from dataclasses import dataclass

from .indicators import TechnicalIndicators
from .providers import NewsItem, StockQuote


@dataclass(frozen=True)
class StockAnalysis:
    symbol: str
    stance: str
    confidence: int
    alert: str
    rationale: str
    action: str


def analyze_stock(
    quote: StockQuote,
    indicators: TechnicalIndicators | None,
    news_items: list[NewsItem],
) -> StockAnalysis:
    score = 0
    reasons = []

    if quote.change_percent is not None:
        if quote.change_percent >= 3:
            score += 2
            reasons.append(f"strong daily move of {quote.change_percent:+.2f}%")
        elif quote.change_percent <= -3:
            score -= 2
            reasons.append(f"sharp daily move of {quote.change_percent:+.2f}%")
        elif quote.change_percent > 0:
            score += 1
            reasons.append("positive daily move")
        elif quote.change_percent < 0:
            score -= 1
            reasons.append("negative daily move")

    if indicators:
        if indicators.momentum_5d_percent is not None:
            if indicators.momentum_5d_percent >= 5:
                score += 1
                reasons.append(f"5-day momentum is {indicators.momentum_5d_percent:+.2f}%")
            elif indicators.momentum_5d_percent <= -5:
                score -= 1
                reasons.append(f"5-day momentum is {indicators.momentum_5d_percent:+.2f}%")

        if indicators.rsi_14 is not None:
            if indicators.rsi_14 >= 70:
                score -= 1
                reasons.append(f"RSI is elevated at {indicators.rsi_14:.1f}")
            elif indicators.rsi_14 <= 30:
                score += 1
                reasons.append(f"RSI is depressed at {indicators.rsi_14:.1f}")

    if news_items:
        reasons.append(f"{len(news_items)} recent news item(s) found")

    if score >= 2:
        stance = "bullish watch"
    elif score <= -2:
        stance = "bearish watch"
    else:
        stance = "neutral watch"

    confidence = min(90, max(35, 55 + abs(score) * 10 + min(len(news_items), 3) * 3))
    alert = "yes" if abs(score) >= 3 or abs(quote.change_percent or 0) >= 5 else "no"
    action = _action_for(stance, alert)
    rationale = "; ".join(reasons) if reasons else "insufficient fresh signals"

    return StockAnalysis(
        symbol=quote.symbol,
        stance=stance,
        confidence=confidence,
        alert=alert,
        rationale=rationale,
        action=action,
    )


def _action_for(stance: str, alert: str) -> str:
    if alert == "yes":
        return "alert and review news before market open"
    if stance == "bullish watch":
        return "watch for continuation"
    if stance == "bearish watch":
        return "watch risk and support levels"
    return "monitor"
