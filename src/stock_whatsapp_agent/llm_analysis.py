from __future__ import annotations

import shutil
import subprocess
from textwrap import dedent

from .events import StockEvent
from .providers import NewsItem, StockQuote, TopGainer
from .reasoning import StockAnalysis
from .skills.cross_stock_reasoning import CrossStockObservation
from .skills.narrative_tracking import NarrativeState


class LlmAnalysisError(RuntimeError):
    pass


def generate_openclaw_analysis(
    openclaw_agent_id: str,
    deterministic_message: str,
    quotes: list[StockQuote],
    news_by_symbol: dict[str, list[NewsItem]],
    top_gainers: list[TopGainer],
    analyses: list[StockAnalysis],
    events_by_symbol: dict[str, list[StockEvent]],
    narratives: list[NarrativeState],
    cross_stock_observations: list[CrossStockObservation],
    timeout_seconds: int,
) -> str:
    if shutil.which("openclaw") is None:
        raise LlmAnalysisError("openclaw command was not found in PATH")

    prompt = _build_prompt(
        deterministic_message=deterministic_message,
        quotes=quotes,
        news_by_symbol=news_by_symbol,
        top_gainers=top_gainers,
        analyses=analyses,
        events_by_symbol=events_by_symbol,
        narratives=narratives,
        cross_stock_observations=cross_stock_observations,
    )
    completed = subprocess.run(
        [
            "openclaw",
            "agent",
            "--agent",
            openclaw_agent_id,
            "--message",
            prompt,
            "--timeout",
            str(timeout_seconds),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds + 30,
    )
    if completed.returncode != 0:
        error = (completed.stderr or completed.stdout).strip()
        raise LlmAnalysisError(error or "OpenClaw LLM analysis failed")

    message = completed.stdout.strip()
    if not message:
        raise LlmAnalysisError("OpenClaw returned an empty final analysis")
    return message


def _build_prompt(
    deterministic_message: str,
    quotes: list[StockQuote],
    news_by_symbol: dict[str, list[NewsItem]],
    top_gainers: list[TopGainer],
    analyses: list[StockAnalysis],
    events_by_symbol: dict[str, list[StockEvent]],
    narratives: list[NarrativeState],
    cross_stock_observations: list[CrossStockObservation],
) -> str:
    return dedent(
        f"""
        You are the final writing layer for a US stock WhatsApp agent.

        Use ONLY the structured facts below. Do not invent prices, news, ratings,
        filings, predictions, or recommendations. Preserve the meaning of the
        deterministic analysis. Keep it concise enough for WhatsApp. Include
        "informational only, not financial advice." Return only the final message.

        Deterministic baseline message:
        {_clip(deterministic_message, 5000)}

        Compact structured facts:
        Watchlist:
        {_quote_lines(quotes)}

        Agent analyses:
        {_analysis_lines(analyses)}

        Events:
        {_event_lines(events_by_symbol)}

        Narratives:
        {_narrative_lines(narratives)}

        Cross-stock observations:
        {_cross_stock_lines(cross_stock_observations)}

        Top gainers:
        {_top_gainer_lines(top_gainers)}

        News headlines:
        {_news_lines(news_by_symbol)}
        """
    ).strip()


def _quote_lines(quotes: list[StockQuote]) -> str:
    return "\n".join(
        f"- {quote.symbol}: price={quote.price}, change_percent={quote.change_percent}, volume={quote.volume}"
        for quote in quotes
    ) or "- none"


def _analysis_lines(analyses: list[StockAnalysis]) -> str:
    return "\n".join(
        "- "
        f"{analysis.symbol}: stance={analysis.stance}, confidence={analysis.confidence}, "
        f"alert={analysis.alert}, priority={analysis.alert_level}/{analysis.alert_score}, "
        f"reason={_clip(analysis.alert_reason, 240)}"
        for analysis in analyses
    ) or "- none"


def _event_lines(events_by_symbol: dict[str, list[StockEvent]]) -> str:
    lines = []
    for symbol, events in events_by_symbol.items():
        for event in events[:3]:
            lines.append(
                f"- {symbol}: {event.event_type}, {event.sentiment}, impact={event.impact_score}, "
                f"summary={_clip(event.summary, 220)}"
            )
    return "\n".join(lines) or "- none"


def _narrative_lines(narratives: list[NarrativeState]) -> str:
    return "\n".join(
        f"- {narrative.name}: {narrative.direction}, strength={narrative.strength}, "
        f"symbols={', '.join(narrative.related_symbols[:6])}"
        for narrative in narratives[:5]
    ) or "- none"


def _cross_stock_lines(observations: list[CrossStockObservation]) -> str:
    return "\n".join(
        f"- {observation.source_symbol}->{observation.related_symbol}: {observation.relationship}, "
        f"direction={observation.direction}, confidence={observation.confidence}, "
        f"reason={_clip(observation.reasoning, 220)}"
        for observation in sorted(observations, key=lambda item: item.confidence, reverse=True)[:5]
    ) or "- none"


def _top_gainer_lines(top_gainers: list[TopGainer]) -> str:
    return "\n".join(
        f"- {gainer.symbol}: change_percent={gainer.change_percent}, price={gainer.price}"
        for gainer in top_gainers[:5]
    ) or "- none"


def _news_lines(news_by_symbol: dict[str, list[NewsItem]]) -> str:
    lines = []
    for symbol, items in news_by_symbol.items():
        for item in items[:2]:
            lines.append(f"- {symbol}: {_clip(item.headline, 180)} ({item.source})")
    return "\n".join(lines) or "- none"


def _clip(value: str, max_length: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max_length - 3].rstrip()}..."
