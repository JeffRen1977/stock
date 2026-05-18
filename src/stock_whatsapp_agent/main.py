from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Callable
from typing import TypeVar

from .cache import (
    ResponseCache,
    dataclass_to_payload,
    dedupe_news_items,
    make_cache_key,
    payload_to_dataclass,
    payload_to_dataclass_list,
)
from .config import Settings, redact_recipients
from .dashboard import render_chart_widget, render_dashboard
from .events import extract_events_from_filings, extract_events_from_news, merge_events
from .formatter import format_daily_message
from .health import ProviderHealthRecord, make_provider_health_record
from .indicators import calculate_indicators
from .memory import save_daily_memory
from .memory_retrieval import build_memory_contexts, flatten_retrievals
from .providers import (
    EarningsEvent,
    HistoricalBar,
    NewsItem,
    RecommendationTrend,
    StockQuote,
    TopGainer,
    build_provider,
)
from .reasoning import analyze_stock
from .sec import SecEdgarClient, SecFiling
from .skills.cross_stock_reasoning import generate_cross_stock_observations, observations_by_symbol
from .skills.news_clustering import cluster_events, flatten_clusters
from .skills.narrative_tracking import narratives_by_symbol, track_narratives
from .storage import save_memory_retrievals, save_run_to_sqlite
from .vector_memory import (
    retrieve_vector_memories,
    save_vector_memories,
    semantic_query_for_symbol,
)
from .whatsapp import build_whatsapp_sender


logger = logging.getLogger(__name__)
T = TypeVar("T")


def run(dry_run: bool = False, skip_fetch: bool = False) -> int:
    settings = Settings.load()
    if skip_fetch:
        if not settings.enable_memory_retrieval:
            print("Memory retrieval is disabled. Set ENABLE_MEMORY_RETRIEVAL=true to validate retrieval.")
            return 0
        memory_contexts = build_memory_contexts(settings.database_path, settings.watchlist, {})
        retrievals = flatten_retrievals(memory_contexts)
        save_memory_retrievals(settings.database_path, retrievals)
        print("Memory retrieval validation")
        for symbol, context in memory_contexts.items():
            print(f"{symbol}: {context.changed_since_previous}; retrievals={len(context.retrievals)}")
        print(f"saved_memory_retrievals={len(retrievals)}")
        return 0

    provider = _build_provider_with_fallback(settings)
    provider_health: list[ProviderHealthRecord] = []
    response_cache = ResponseCache(settings.database_path)

    logger.info("Fetching quotes for watchlist: %s", ", ".join(settings.watchlist))
    quotes = _fetch_quotes(
        provider,
        settings.watchlist,
        settings.api_request_delay_seconds,
        provider_health,
        response_cache,
        settings.quote_cache_ttl_seconds,
    )

    logger.info("Fetching latest news for each watchlist stock")
    news_by_symbol = _fetch_news(
        provider,
        settings.watchlist,
        settings.news_items_per_stock,
        settings.api_request_delay_seconds,
        provider_health,
        response_cache,
        settings.news_cache_ttl_seconds,
    )
    news_events_by_symbol = extract_events_from_news(news_by_symbol)
    filings_by_symbol = _fetch_sec_filings(settings)
    filing_events_by_symbol = extract_events_from_filings(filings_by_symbol)
    events_by_symbol = merge_events(news_events_by_symbol, filing_events_by_symbol)
    events_by_symbol, event_clusters_by_symbol = cluster_events(events_by_symbol)
    narratives = track_narratives(settings.database_path, events_by_symbol, settings.timezone)
    narratives_by_symbol_map = narratives_by_symbol(narratives)
    memory_contexts = (
        build_memory_contexts(settings.database_path, settings.watchlist, events_by_symbol)
        if settings.enable_memory_retrieval
        else {}
    )

    cross_stock_observations = generate_cross_stock_observations(
        settings.database_path,
        quotes,
        events_by_symbol,
    )
    cross_stock_observations_by_symbol = observations_by_symbol(cross_stock_observations)
    semantic_memories_by_symbol = _retrieve_semantic_memories(
        settings=settings,
        quotes=quotes,
        news_by_symbol=news_by_symbol,
        events_by_symbol=events_by_symbol,
        narratives_by_symbol_map=narratives_by_symbol_map,
    )

    logger.info("Fetching top gainers")
    top_gainers = _fetch_top_gainers(
        provider,
        settings.top_gainers_limit,
        provider_health,
        response_cache,
        settings.quote_cache_ttl_seconds,
    )

    logger.info("Fetching historical prices for technical indicators")
    history_by_symbol = _fetch_history(
        provider,
        settings.watchlist,
        settings.api_request_delay_seconds,
        provider_health,
        response_cache,
        settings.history_cache_ttl_seconds,
    )
    indicators_by_symbol = {
        symbol: calculate_indicators(symbol, bars)
        for symbol, bars in history_by_symbol.items()
    }
    analyses = [
        analyze_stock(
            quote,
            indicators_by_symbol.get(quote.symbol),
            news_by_symbol.get(quote.symbol, []),
            events_by_symbol.get(quote.symbol, []),
            memory_contexts.get(quote.symbol),
            narratives_by_symbol_map.get(quote.symbol, []),
            cross_stock_observations_by_symbol.get(quote.symbol, []),
            event_clusters_by_symbol.get(quote.symbol, []),
            filings_by_symbol.get(quote.symbol, []),
            semantic_memories_by_symbol.get(quote.symbol, []),
        )
        for quote in quotes
    ]

    logger.info("Fetching recommendation trends")
    recommendations_by_symbol = _fetch_recommendations(
        provider,
        settings.watchlist,
        settings.api_request_delay_seconds,
        provider_health,
        response_cache,
        settings.news_cache_ttl_seconds,
    )

    logger.info("Fetching earnings calendar")
    earnings_by_symbol = _fetch_earnings(
        provider,
        settings.watchlist,
        settings.api_request_delay_seconds,
        provider_health,
        response_cache,
        settings.news_cache_ttl_seconds,
    )

    message = format_daily_message(
        quotes=quotes,
        news_by_symbol=news_by_symbol,
        top_gainers=top_gainers,
        indicators_by_symbol=indicators_by_symbol,
        analyses=analyses,
        events_by_symbol=events_by_symbol,
        event_clusters_by_symbol=event_clusters_by_symbol,
        narratives=narratives,
        cross_stock_observations=cross_stock_observations,
        filings_by_symbol=filings_by_symbol,
        memory_contexts=memory_contexts,
        recommendations_by_symbol=recommendations_by_symbol,
        earnings_by_symbol=earnings_by_symbol,
        timezone=settings.timezone,
    )

    save_run_to_sqlite(
        database_path=settings.database_path,
        timezone=settings.timezone,
        quotes=quotes,
        news_by_symbol=news_by_symbol,
        top_gainers=top_gainers,
        history_by_symbol=history_by_symbol,
        indicators_by_symbol=indicators_by_symbol,
        analyses=analyses,
        events_by_symbol=events_by_symbol,
        event_clusters=flatten_clusters(event_clusters_by_symbol),
        narratives=narratives,
        cross_stock_observations=cross_stock_observations,
        filings_by_symbol=filings_by_symbol,
        memory_retrievals=flatten_retrievals(memory_contexts),
        provider_health=provider_health,
        recommendations_by_symbol=recommendations_by_symbol,
        earnings_by_symbol=earnings_by_symbol,
    )
    logger.info("Saved structured stock data to %s", settings.database_path)

    if settings.enable_vector_memory:
        try:
            saved_count = save_vector_memories(
                database_path=settings.database_path,
                provider=settings.vector_db_provider,
                timezone=settings.timezone,
                news_by_symbol=news_by_symbol,
                events_by_symbol=events_by_symbol,
                filings_by_symbol=filings_by_symbol,
                analyses=analyses,
                narratives=narratives,
            )
            logger.info("Saved %s compact semantic memory item(s)", saved_count)
        except Exception as exc:
            logger.warning("Vector memory save failed: %s", exc)

    if settings.generate_chart_widget:
        chart_path = render_chart_widget(
            settings.chart_symbol,
            history_by_symbol.get(settings.chart_symbol, []),
            settings.dashboard_dir,
        )
        if chart_path:
            logger.info("Saved chart widget to %s", chart_path)
        dashboard_path = render_dashboard(settings.database_path, settings.dashboard_dir, chart_path)
        logger.info("Saved dashboard to %s", dashboard_path)

    if settings.save_daily_memory:
        memory_path = save_daily_memory(
            quotes=quotes,
            news_by_symbol=news_by_symbol,
            top_gainers=top_gainers,
            history_by_symbol=history_by_symbol,
            indicators_by_symbol=indicators_by_symbol,
            analyses=analyses,
            events_by_symbol=events_by_symbol,
            event_clusters_by_symbol=event_clusters_by_symbol,
            narratives=narratives,
            cross_stock_observations=cross_stock_observations,
            filings_by_symbol=filings_by_symbol,
            memory_contexts=memory_contexts,
            recommendations_by_symbol=recommendations_by_symbol,
            earnings_by_symbol=earnings_by_symbol,
            message=message,
            timezone=settings.timezone,
            memory_dir=settings.memory_dir,
        )
        logger.info("Saved daily stock memory to %s", memory_path)

    if dry_run:
        print(message)
        return 0

    sender = build_whatsapp_sender()
    logger.info("Sending WhatsApp message to %s", redact_recipients(settings.whatsapp_to))
    results = sender.send_to_many(settings.whatsapp_to, message)

    for result in results:
        safe_recipient = redact_recipients([result.recipient])[0]
        if result.success:
            logger.info("Sent WhatsApp message to %s: %s", safe_recipient, result.message_sid)
        else:
            logger.error("Failed to send WhatsApp message to %s: %s", safe_recipient, result.error)

    return 0 if any(result.success for result in results) else 1


def _retrieve_semantic_memories(
    settings: Settings,
    quotes: list[StockQuote],
    news_by_symbol: dict[str, list[NewsItem]],
    events_by_symbol: dict[str, list],
    narratives_by_symbol_map: dict[str, list],
) -> dict[str, list]:
    if not settings.enable_vector_memory:
        return {}

    memories_by_symbol = {}
    for quote in quotes:
        query = semantic_query_for_symbol(
            quote.symbol,
            news_by_symbol.get(quote.symbol, []),
            events_by_symbol.get(quote.symbol, []),
            narratives_by_symbol_map.get(quote.symbol, []),
        )
        try:
            memories_by_symbol[quote.symbol] = retrieve_vector_memories(
                database_path=settings.database_path,
                provider=settings.vector_db_provider,
                symbol=quote.symbol,
                query=query,
                limit=settings.vector_memory_top_k,
            )
        except Exception as exc:
            logger.warning("Vector memory retrieval failed for %s: %s", quote.symbol, exc)
            memories_by_symbol[quote.symbol] = []
    return memories_by_symbol


def _build_provider_with_fallback(settings: Settings):
    try:
        return build_provider(
            settings.stock_api_provider,
            settings.stock_api_key,
            settings.provider_timeout_seconds,
        )
    except ValueError as exc:
        if settings.stock_api_provider == "finnhub":
            logger.warning("Finnhub is configured but unavailable: %s. Falling back to Yahoo.", exc)
            return build_provider("yahoo", None, settings.provider_timeout_seconds)
        raise


def _fetch_quotes(
    provider,
    watchlist: tuple[str, ...],
    request_delay_seconds: float,
    provider_health: list[ProviderHealthRecord],
    response_cache: ResponseCache,
    cache_ttl_seconds: int,
) -> list[StockQuote]:
    quotes = []
    for symbol in watchlist:
        try:
            quotes.append(
                _cached_provider_call(
                    provider,
                    f"get_quote:{symbol}",
                    lambda symbol=symbol: provider.get_quote(symbol),
                    provider_health,
                    response_cache,
                    cache_ttl_seconds,
                    dataclass_to_payload,
                    lambda payload: payload_to_dataclass(StockQuote, payload),
                )
            )
        except Exception as exc:
            logger.warning("Failed to fetch quote for %s: %s", symbol, exc)
            quotes.append(StockQuote(symbol=symbol, price=None, change=None, change_percent=None))
        finally:
            _sleep_between_api_calls(request_delay_seconds)
    return quotes


def _fetch_news(
    provider,
    watchlist: tuple[str, ...],
    limit: int,
    request_delay_seconds: float,
    provider_health: list[ProviderHealthRecord],
    response_cache: ResponseCache,
    cache_ttl_seconds: int,
) -> dict[str, list[NewsItem]]:
    news_by_symbol = {}
    for symbol in watchlist:
        try:
            items = _cached_provider_call(
                provider,
                f"get_news:{symbol}",
                lambda symbol=symbol: provider.get_news(symbol, limit),
                provider_health,
                response_cache,
                cache_ttl_seconds,
                dataclass_to_payload,
                lambda payload: payload_to_dataclass_list(NewsItem, payload),
            )
            items = dedupe_news_items(items)
            response_cache.record_news_seen(items)
            news_by_symbol[symbol] = items
        except Exception as exc:
            logger.warning("Failed to fetch news for %s: %s", symbol, exc)
            news_by_symbol[symbol] = []
        finally:
            _sleep_between_api_calls(request_delay_seconds)
    return news_by_symbol


def _fetch_top_gainers(
    provider,
    limit: int,
    provider_health: list[ProviderHealthRecord],
    response_cache: ResponseCache,
    cache_ttl_seconds: int,
) -> list[TopGainer]:
    try:
        return _cached_provider_call(
            provider,
            "get_top_gainers",
            lambda: provider.get_top_gainers(limit),
            provider_health,
            response_cache,
            cache_ttl_seconds,
            dataclass_to_payload,
            lambda payload: payload_to_dataclass_list(TopGainer, payload),
        )
    except Exception as exc:
        logger.warning("Failed to fetch top gainers: %s", exc)
        return []


def _fetch_history(
    provider,
    watchlist: tuple[str, ...],
    request_delay_seconds: float,
    provider_health: list[ProviderHealthRecord],
    response_cache: ResponseCache,
    cache_ttl_seconds: int,
) -> dict[str, list[HistoricalBar]]:
    history_by_symbol = {}
    for symbol in watchlist:
        try:
            history_by_symbol[symbol] = _cached_provider_call(
                provider,
                f"get_history:{symbol}",
                lambda symbol=symbol: provider.get_history(symbol),
                provider_health,
                response_cache,
                cache_ttl_seconds,
                dataclass_to_payload,
                lambda payload: payload_to_dataclass_list(HistoricalBar, payload),
            )
        except Exception as exc:
            logger.warning("Failed to fetch price history for %s: %s", symbol, exc)
            history_by_symbol[symbol] = []
        finally:
            _sleep_between_api_calls(request_delay_seconds)
    return history_by_symbol


def _fetch_recommendations(
    provider,
    watchlist: tuple[str, ...],
    request_delay_seconds: float,
    provider_health: list[ProviderHealthRecord],
    response_cache: ResponseCache,
    cache_ttl_seconds: int,
) -> dict[str, list[RecommendationTrend]]:
    recommendations_by_symbol = {}
    for symbol in watchlist:
        try:
            recommendations_by_symbol[symbol] = _cached_provider_call(
                provider,
                f"get_recommendation_trends:{symbol}",
                lambda symbol=symbol: provider.get_recommendation_trends(symbol),
                provider_health,
                response_cache,
                cache_ttl_seconds,
                dataclass_to_payload,
                lambda payload: payload_to_dataclass_list(RecommendationTrend, payload),
            )
        except Exception as exc:
            logger.warning("Failed to fetch recommendation trends for %s: %s", symbol, exc)
            recommendations_by_symbol[symbol] = []
        finally:
            _sleep_between_api_calls(request_delay_seconds)
    return recommendations_by_symbol


def _fetch_earnings(
    provider,
    watchlist: tuple[str, ...],
    request_delay_seconds: float,
    provider_health: list[ProviderHealthRecord],
    response_cache: ResponseCache,
    cache_ttl_seconds: int,
) -> dict[str, list[EarningsEvent]]:
    earnings_by_symbol = {}
    for symbol in watchlist:
        try:
            earnings_by_symbol[symbol] = _cached_provider_call(
                provider,
                f"get_earnings_events:{symbol}",
                lambda symbol=symbol: provider.get_earnings_events(symbol),
                provider_health,
                response_cache,
                cache_ttl_seconds,
                dataclass_to_payload,
                lambda payload: payload_to_dataclass_list(EarningsEvent, payload),
            )
        except Exception as exc:
            logger.warning("Failed to fetch earnings events for %s: %s", symbol, exc)
            earnings_by_symbol[symbol] = []
        finally:
            _sleep_between_api_calls(request_delay_seconds)
    return earnings_by_symbol


def _fetch_sec_filings(settings: Settings) -> dict[str, list[SecFiling]]:
    if not settings.enable_sec_ingestion:
        return {symbol: [] for symbol in settings.watchlist}

    client = SecEdgarClient(
        user_agent=settings.sec_user_agent,
        timeout_seconds=settings.provider_timeout_seconds,
    )
    filings_by_symbol = {}
    for symbol in settings.watchlist:
        try:
            filings_by_symbol[symbol] = client.get_recent_filings(symbol, settings.sec_filings_limit)
        except Exception as exc:
            logger.warning("Failed to fetch SEC filings for %s: %s", symbol, exc)
            filings_by_symbol[symbol] = []
        finally:
            _sleep_between_api_calls(settings.api_request_delay_seconds)
    return filings_by_symbol


def _cached_provider_call(
    provider,
    operation: str,
    call: Callable[[], T],
    provider_health: list[ProviderHealthRecord],
    response_cache: ResponseCache,
    cache_ttl_seconds: int,
    serialize: Callable[[T], object],
    deserialize: Callable[[object], T],
) -> T:
    provider_name = getattr(provider, "provider_name", provider.__class__.__name__)
    cache_key = make_cache_key(provider_name, operation)
    cached_payload = response_cache.get(cache_key)
    if cached_payload is not None:
        provider_health.append(
            make_provider_health_record(
                provider_name=provider_name,
                operation=operation,
                success=True,
                error=None,
                latency_ms=0,
                stale=True,
            )
        )
        return deserialize(cached_payload)

    result = _track_provider_call(provider, operation, call, provider_health)
    response_cache.set(
        cache_key=cache_key,
        provider_name=provider_name,
        operation=operation,
        payload=serialize(result),
        ttl_seconds=cache_ttl_seconds,
    )
    return result


def _track_provider_call(
    provider,
    operation: str,
    call: Callable[[], T],
    provider_health: list[ProviderHealthRecord],
) -> T:
    provider_name = getattr(provider, "provider_name", provider.__class__.__name__)
    started_at = time.perf_counter()
    try:
        result = call()
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        provider_health.append(
            make_provider_health_record(
                provider_name=provider_name,
                operation=operation,
                success=False,
                error=str(exc),
                latency_ms=latency_ms,
            )
        )
        raise

    latency_ms = int((time.perf_counter() - started_at) * 1000)
    provider_health.append(
        make_provider_health_record(
            provider_name=provider_name,
            operation=operation,
            success=True,
            error=None,
            latency_ms=latency_ms,
        )
    )
    return result


def _sleep_between_api_calls(request_delay_seconds: float) -> None:
    if request_delay_seconds <= 0:
        return
    logger.info("Waiting %.1f seconds to respect stock API rate limits", request_delay_seconds)
    time.sleep(request_delay_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Send daily US stock updates to WhatsApp.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the message instead of sending it to WhatsApp.",
    )
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Validate memory retrieval from existing SQLite data without network calls.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Logging verbosity.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        raise SystemExit(run(dry_run=args.dry_run, skip_fetch=args.skip_fetch))
    except Exception as exc:
        logger.error("Stock WhatsApp agent failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
