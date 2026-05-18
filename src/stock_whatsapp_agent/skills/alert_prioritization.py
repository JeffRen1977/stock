from __future__ import annotations

from dataclasses import dataclass

from ..events import StockEvent
from ..indicators import TechnicalIndicators
from ..memory_retrieval import MemoryContext
from ..providers import StockQuote
from ..sec import SecFiling
from .cross_stock_reasoning import CrossStockObservation
from .news_clustering import EventCluster


@dataclass(frozen=True)
class AlertPriority:
    level: str
    score: int
    reason: str


def prioritize_alert(
    quote: StockQuote,
    indicators: TechnicalIndicators | None,
    events: list[StockEvent],
    event_clusters: list[EventCluster],
    filings: list[SecFiling],
    memory_context: MemoryContext | None,
    cross_stock_observations: list[CrossStockObservation],
) -> AlertPriority:
    score = 0
    reasons = []

    price_move = abs(quote.change_percent or 0)
    if price_move >= 8:
        score += 35
        reasons.append(f"{price_move:.1f}% price move")
    elif price_move >= 5:
        score += 25
        reasons.append(f"{price_move:.1f}% price move")
    elif price_move >= 3:
        score += 12
        reasons.append(f"{price_move:.1f}% price move")

    volume_score = _volume_score(quote, indicators)
    if volume_score:
        score += volume_score
        reasons.append("elevated volume")

    max_event_impact = max((event.impact_score for event in events), default=0)
    if max_event_impact >= 85:
        score += 30
        reasons.append(f"event impact {max_event_impact}")
    elif max_event_impact >= 75:
        score += 20
        reasons.append(f"event impact {max_event_impact}")
    elif max_event_impact >= 65:
        score += 10
        reasons.append(f"event impact {max_event_impact}")

    cluster_score = _cluster_score(event_clusters)
    if cluster_score:
        score += cluster_score
        reasons.append("clustered news confirmation")

    filing_score = _filing_score(filings, events)
    if filing_score:
        score += filing_score
        reasons.append("SEC/company source confidence")

    cross_stock_score = _cross_stock_score(cross_stock_observations)
    if cross_stock_score:
        score += cross_stock_score
        reasons.append("high-confidence cross-stock read-through")

    novelty_penalty = _novelty_penalty(memory_context)
    if novelty_penalty:
        score -= novelty_penalty
        reasons.append("repeated memory signal penalty")

    score = max(0, min(score, 100))
    level = _level_for_score(score)
    reason = "; ".join(reasons) if reasons else "no high-priority alert signal"
    return AlertPriority(level=level, score=score, reason=reason)


def _volume_score(quote: StockQuote, indicators: TechnicalIndicators | None) -> int:
    if quote.volume is None or indicators is None or indicators.latest_volume is None:
        return 0
    baseline = indicators.latest_volume
    if baseline <= 0:
        return 0
    ratio = quote.volume / baseline
    if ratio >= 2:
        return 15
    if ratio >= 1.5:
        return 8
    return 0


def _cluster_score(clusters: list[EventCluster]) -> int:
    if not clusters:
        return 0
    strongest = max(clusters, key=lambda cluster: (cluster.source_count, cluster.confidence))
    if strongest.source_count >= 3 and strongest.confidence >= 75:
        return 15
    if strongest.source_count >= 2:
        return 8
    return 0


def _filing_score(filings: list[SecFiling], events: list[StockEvent]) -> int:
    if any(filing.form_type in {"8-K", "10-Q", "10-K", "S-1"} for filing in filings):
        return 15
    if any(event.source == "SEC EDGAR" and event.impact_score >= 75 for event in events):
        return 12
    return 0


def _cross_stock_score(observations: list[CrossStockObservation]) -> int:
    if any(observation.confidence >= 85 for observation in observations):
        return 10
    if any(observation.confidence >= 75 for observation in observations):
        return 6
    return 0


def _novelty_penalty(memory_context: MemoryContext | None) -> int:
    if memory_context is None:
        return 0
    penalty = min(memory_context.repeated_event_count * 8, 24)
    penalty += min(memory_context.recent_alert_count * 4, 12)
    return penalty


def _level_for_score(score: int) -> str:
    if score >= 75:
        return "urgent"
    if score >= 50:
        return "important"
    if score >= 25:
        return "watch"
    return "none"
