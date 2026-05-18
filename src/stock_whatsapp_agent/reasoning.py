from __future__ import annotations

from dataclasses import dataclass

from .events import StockEvent
from .indicators import TechnicalIndicators
from .memory_retrieval import MemoryContext
from .providers import NewsItem, StockQuote
from .sec import SecFiling
from .skills.alert_prioritization import prioritize_alert
from .skills.cross_stock_reasoning import CrossStockObservation
from .skills.news_clustering import EventCluster
from .skills.narrative_tracking import NarrativeState
from .vector_memory import RetrievedVectorMemory


@dataclass(frozen=True)
class StockAnalysis:
    symbol: str
    stance: str
    confidence: int
    alert: str
    rationale: str
    action: str
    alert_level: str
    alert_score: int
    alert_reason: str


def analyze_stock(
    quote: StockQuote,
    indicators: TechnicalIndicators | None,
    news_items: list[NewsItem],
    events: list[StockEvent] | None = None,
    memory_context: MemoryContext | None = None,
    narratives: list[NarrativeState] | None = None,
    cross_stock_observations: list[CrossStockObservation] | None = None,
    event_clusters: list[EventCluster] | None = None,
    filings: list[SecFiling] | None = None,
    semantic_memories: list[RetrievedVectorMemory] | None = None,
) -> StockAnalysis:
    score = 0
    reasons = []
    events = events or []
    narratives = narratives or []
    cross_stock_observations = cross_stock_observations or []
    event_clusters = event_clusters or []
    filings = filings or []
    semantic_memories = semantic_memories or []

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

    if semantic_memories:
        strongest_memory = semantic_memories[0]
        reasons.append(
            f"semantic memory found {strongest_memory.memory_type} context "
            f"({strongest_memory.similarity:.2f} similarity)"
        )

    if score >= 2:
        stance = "bullish watch"
    elif score <= -2:
        stance = "bearish watch"
    else:
        stance = "neutral watch"

    confidence = min(90, max(35, 55 + abs(score) * 10 + min(len(news_items), 3) * 3 - confidence_penalty))
    alert_priority = prioritize_alert(
        quote=quote,
        indicators=indicators,
        events=events,
        event_clusters=event_clusters,
        filings=filings,
        memory_context=memory_context,
        cross_stock_observations=cross_stock_observations,
    )
    alert = "yes" if alert_priority.level in {"important", "urgent"} else "no"
    action = _action_for(stance, alert)
    rationale_parts = reasons + [f"alert priority {alert_priority.level}: {alert_priority.reason}"]
    rationale = "; ".join(rationale_parts) if rationale_parts else "insufficient fresh signals"

    return StockAnalysis(
        symbol=quote.symbol,
        stance=stance,
        confidence=confidence,
        alert=alert,
        rationale=rationale,
        action=action,
        alert_level=alert_priority.level,
        alert_score=alert_priority.score,
        alert_reason=alert_priority.reason,
    )


def _action_for(stance: str, alert: str) -> str:
    if alert == "yes":
        return "alert and review news before market open"
    if stance == "bullish watch":
        return "watch for continuation"
    if stance == "bearish watch":
        return "watch risk and support levels"
    return "monitor"
