from __future__ import annotations

import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .health import ProviderHealthRecord
from .indicators import TechnicalIndicators
from .providers import HistoricalBar, NewsItem, StockQuote, TopGainer
from .reasoning import StockAnalysis


def save_run_to_sqlite(
    database_path: Path,
    timezone: str,
    quotes: list[StockQuote],
    news_by_symbol: dict[str, list[NewsItem]],
    top_gainers: list[TopGainer],
    history_by_symbol: dict[str, list[HistoricalBar]],
    indicators_by_symbol: dict[str, TechnicalIndicators],
    analyses: list[StockAnalysis],
    provider_health: list[ProviderHealthRecord],
) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(ZoneInfo(timezone)).isoformat()

    with sqlite3.connect(database_path) as connection:
        _create_tables(connection)
        connection.execute("insert into runs(generated_at) values (?)", (generated_at,))
        run_id = connection.execute("select last_insert_rowid()").fetchone()[0]

        for quote in quotes:
            connection.execute(
                """
                insert into quotes(run_id, symbol, price, change, change_percent, volume)
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    quote.symbol,
                    quote.price,
                    quote.change,
                    quote.change_percent,
                    quote.volume,
                ),
            )

        for symbol, items in news_by_symbol.items():
            for item in items:
                connection.execute(
                    """
                    insert into news(run_id, symbol, headline, source, published_at, summary, url)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        symbol,
                        item.headline,
                        item.source,
                        item.published_at,
                        item.summary,
                        item.url,
                    ),
                )

        for gainer in top_gainers:
            connection.execute(
                """
                insert into top_gainers(run_id, symbol, price, change_percent, volume)
                values (?, ?, ?, ?, ?)
                """,
                (run_id, gainer.symbol, gainer.price, gainer.change_percent, gainer.volume),
            )

        for symbol, bars in history_by_symbol.items():
            for bar in bars:
                connection.execute(
                    """
                    insert into price_history(run_id, symbol, date, close, volume)
                    values (?, ?, ?, ?, ?)
                    """,
                    (run_id, symbol, bar.date, bar.close, bar.volume),
                )

        for indicator in indicators_by_symbol.values():
            values = asdict(indicator)
            connection.execute(
                """
                insert into technical_indicators(
                    run_id, symbol, latest_close, latest_volume, sma_5, sma_20, rsi_14, momentum_5d_percent
                )
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    values["symbol"],
                    values["latest_close"],
                    values["latest_volume"],
                    values["sma_5"],
                    values["sma_20"],
                    values["rsi_14"],
                    values["momentum_5d_percent"],
                ),
            )

        for analysis in analyses:
            connection.execute(
                """
                insert into analyses(run_id, symbol, stance, confidence, alert, rationale, action)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    analysis.symbol,
                    analysis.stance,
                    analysis.confidence,
                    analysis.alert,
                    analysis.rationale,
                    analysis.action,
                ),
            )

        for record in provider_health:
            connection.execute(
                """
                insert into provider_health(
                    run_id, provider_name, operation, success, error, latency_ms, created_at, stale
                )
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    record.provider_name,
                    record.operation,
                    int(record.success),
                    record.error,
                    record.latency_ms,
                    record.created_at,
                    int(record.stale),
                ),
            )


def _create_tables(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        create table if not exists runs (
            id integer primary key autoincrement,
            generated_at text not null
        );

        create table if not exists quotes (
            run_id integer,
            symbol text,
            price real,
            change real,
            change_percent real,
            volume integer
        );

        create table if not exists news (
            run_id integer,
            symbol text,
            headline text,
            source text,
            published_at text,
            summary text,
            url text
        );

        create table if not exists top_gainers (
            run_id integer,
            symbol text,
            price real,
            change_percent real,
            volume integer
        );

        create table if not exists price_history (
            run_id integer,
            symbol text,
            date text,
            close real,
            volume integer
        );

        create table if not exists technical_indicators (
            run_id integer,
            symbol text,
            latest_close real,
            latest_volume integer,
            sma_5 real,
            sma_20 real,
            rsi_14 real,
            momentum_5d_percent real
        );

        create table if not exists analyses (
            run_id integer,
            symbol text,
            stance text,
            confidence integer,
            alert text,
            rationale text,
            action text
        );

        create table if not exists provider_health (
            run_id integer,
            provider_name text,
            operation text,
            success integer,
            error text,
            latency_ms integer,
            created_at text,
            stale integer
        );
        """
    )
