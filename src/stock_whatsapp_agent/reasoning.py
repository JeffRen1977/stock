from __future__ import annotations

from dataclasses import dataclass

from .events import StockEvent
from .indicators import TechnicalIndicators
from .memory_retrieval import MemoryContext
from .providers import NewsItem, StockQuote
from .skills.cross_stock_reasoning import CrossStockObservation
from .skills.narrative_tracking import NarrativeState


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
    events: list[StockEvent] | None = None,
    memory_context: MemoryContext | None = None,
    narratives: list[NarrativeState] | None = None,
    cross_stock_observations: list[CrossStockObservation] | None = None,
) -> StockAnalysis:
    score = 0
    reasons = []
    events = events or []
    narratives = narratives or []
    cross_stock_observations = cross_stock_observations or []

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

    for event in events:
        if event.sentiment == "positive":
            score += 1
        elif event.sentiment == "negative":
            score -= 1
        if event.impact_score >= 75:
            reasons.append(f"high-impact {event.event_type} event")

    if events:
        reasons.append(f"{len(events)} structured event(s) extracted")

    for narrative in narratives:
        if narrative.strength < 2 and narrative.direction == "stable":
            continue
        if narrative.direction == "strengthening":
            score += 1
            reasons.append(f"{narrative.name} narrative is strengthening")
        elif narrative.direction == "weakening":
            score -= 1
            reasons.append(f"{narrative.name} narrative is weakening")
        elif narrative.direction == "mixed":
            reasons.append(f"{narrative.name} narrative is mixed")

    for observation in cross_stock_observations:
        if observation.confidence < 75:
            continue
        if observation.direction == "positive":
            score += 1
            reasons.append(f"positive {observation.source_symbol} read-through")
        elif observation.direction == "negative":
            score -= 1
            reasons.append(f"negative {observation.source_symbol} read-through")

    if memory_context:
        if memory_context.prior_stance:
            reasons.append(f"prior stance was {memory_context.prior_stance}")
        if memory_context.repeated_event_count:
            score -= min(memory_context.repeated_event_count, 2)
            reasons.append(f"{memory_context.repeated_event_count} repeated event(s) from memory")
        if memory_context.recent_alert_count:
            confidence_penalty = min(memory_context.recent_alert_count * 3, 9)
        else:
            confidence_penalty = 0
        reasons.append(memory_context.changed_since_previous)
    else:
        confidence_penalty = 0

    if score >= 2:
        stance = "bullish watch"
    elif score <= -2:
        stance = "bearish watch"
    else:
        stance = "neutral watch"

    max_event_impact = max((event.impact_score for event in events), default=0)
    confidence = min(90, max(35, 55 + abs(score) * 10 + min(len(news_items), 3) * 3 - confidence_penalty))
    alert = "yes" if abs(score) >= 3 or abs(quote.change_percent or 0) >= 5 or max_event_impact >= 80 else "no"
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
