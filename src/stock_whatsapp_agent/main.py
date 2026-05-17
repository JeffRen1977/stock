from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Callable
from typing import TypeVar

from .config import Settings, redact_recipients
from .dashboard import render_chart_widget
from .formatter import format_daily_message
from .health import ProviderHealthRecord, make_provider_health_record
from .indicators import calculate_indicators
from .memory import save_daily_memory
from .providers import HistoricalBar, NewsItem, StockQuote, TopGainer, build_provider
from .reasoning import analyze_stock
from .storage import save_run_to_sqlite
from .whatsapp import build_whatsapp_sender


logger = logging.getLogger(__name__)
T = TypeVar("T")


def run(dry_run: bool = False) -> int:
    settings = Settings.load()
    provider = build_provider(
        settings.stock_api_provider,
        settings.stock_api_key,
        settings.provider_timeout_seconds,
    )
    provider_health: list[ProviderHealthRecord] = []

    logger.info("Fetching quotes for watchlist: %s", ", ".join(settings.watchlist))
    quotes = _fetch_quotes(
        provider,
        settings.watchlist,
        settings.api_request_delay_seconds,
        provider_health,
    )

    logger.info("Fetching latest news for each watchlist stock")
    news_by_symbol = _fetch_news(
        provider,
        settings.watchlist,
        settings.news_items_per_stock,
        settings.api_request_delay_seconds,
        provider_health,
    )

    logger.info("Fetching top gainers")
    top_gainers = _fetch_top_gainers(provider, settings.top_gainers_limit, provider_health)

    logger.info("Fetching historical prices for technical indicators")
    history_by_symbol = _fetch_history(
        provider,
        settings.watchlist,
        settings.api_request_delay_seconds,
        provider_health,
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
        )
        for quote in quotes
    ]

    message = format_daily_message(
        quotes=quotes,
        news_by_symbol=news_by_symbol,
        top_gainers=top_gainers,
        indicators_by_symbol=indicators_by_symbol,
        analyses=analyses,
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
        provider_health=provider_health,
    )
    logger.info("Saved structured stock data to %s", settings.database_path)

    if settings.generate_chart_widget:
        chart_path = render_chart_widget(
            settings.chart_symbol,
            history_by_symbol.get(settings.chart_symbol, []),
            settings.dashboard_dir,
        )
        if chart_path:
            logger.info("Saved chart widget to %s", chart_path)

    if settings.save_daily_memory:
        memory_path = save_daily_memory(
            quotes=quotes,
            news_by_symbol=news_by_symbol,
            top_gainers=top_gainers,
            history_by_symbol=history_by_symbol,
            indicators_by_symbol=indicators_by_symbol,
            analyses=analyses,
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


def _fetch_quotes(
    provider,
    watchlist: tuple[str, ...],
    request_delay_seconds: float,
    provider_health: list[ProviderHealthRecord],
) -> list[StockQuote]:
    quotes = []
    for symbol in watchlist:
        try:
            quotes.append(
                _track_provider_call(
                    provider,
                    f"get_quote:{symbol}",
                    lambda symbol=symbol: provider.get_quote(symbol),
                    provider_health,
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
) -> dict[str, list[NewsItem]]:
    news_by_symbol = {}
    for symbol in watchlist:
        try:
            news_by_symbol[symbol] = _track_provider_call(
                provider,
                f"get_news:{symbol}",
                lambda symbol=symbol: provider.get_news(symbol, limit),
                provider_health,
            )
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
) -> list[TopGainer]:
    try:
        return _track_provider_call(
            provider,
            "get_top_gainers",
            lambda: provider.get_top_gainers(limit),
            provider_health,
        )
    except Exception as exc:
        logger.warning("Failed to fetch top gainers: %s", exc)
        return []


def _fetch_history(
    provider,
    watchlist: tuple[str, ...],
    request_delay_seconds: float,
    provider_health: list[ProviderHealthRecord],
) -> dict[str, list[HistoricalBar]]:
    history_by_symbol = {}
    for symbol in watchlist:
        try:
            history_by_symbol[symbol] = _track_provider_call(
                provider,
                f"get_history:{symbol}",
                lambda symbol=symbol: provider.get_history(symbol),
                provider_health,
            )
        except Exception as exc:
            logger.warning("Failed to fetch price history for %s: %s", symbol, exc)
            history_by_symbol[symbol] = []
        finally:
            _sleep_between_api_calls(request_delay_seconds)
    return history_by_symbol


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
        raise SystemExit(run(dry_run=args.dry_run))
    except Exception as exc:
        logger.error("Stock WhatsApp agent failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
