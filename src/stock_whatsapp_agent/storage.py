from __future__ import annotations

import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .cache import create_cache_tables
from .events import StockEvent
from .health import ProviderHealthRecord
from .indicators import TechnicalIndicators
from .memory_retrieval import MemoryRetrieval
from .providers import EarningsEvent, HistoricalBar, NewsItem, RecommendationTrend, StockQuote, TopGainer
from .reasoning import StockAnalysis
from .sec import SecFiling
from .skills.news_clustering import EventCluster
from .skills.narrative_tracking import NarrativeState


def save_run_to_sqlite(
    database_path: Path,
    timezone: str,
    quotes: list[StockQuote],
    news_by_symbol: dict[str, list[NewsItem]],
    top_gainers: list[TopGainer],
    history_by_symbol: dict[str, list[HistoricalBar]],
    indicators_by_symbol: dict[str, TechnicalIndicators],
    analyses: list[StockAnalysis],
    events_by_symbol: dict[str, list[StockEvent]],
    event_clusters: list[EventCluster],
    narratives: list[NarrativeState],
    filings_by_symbol: dict[str, list[SecFiling]],
    memory_retrievals: list[MemoryRetrieval],
    provider_health: list[ProviderHealthRecord],
    recommendations_by_symbol: dict[str, list[RecommendationTrend]] | None = None,
    earnings_by_symbol: dict[str, list[EarningsEvent]] | None = None,
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

        for symbol, events in events_by_symbol.items():
            for event in events:
                connection.execute(
                    """
                    insert into events(
                        run_id, symbol, event_type, headline, summary, source, published_at,
                        sentiment, confidence, impact_score, related_symbols_json, dedupe_hash, cluster_id
                    )
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        symbol,
                        event.event_type,
                        event.headline,
                        event.summary,
                        event.source,
                        event.published_at,
                        event.sentiment,
                        event.confidence,
                        event.impact_score,
                        event.related_symbols_json,
                        event.dedupe_hash,
                        event.cluster_id,
                    ),
                )

        for cluster in event_clusters:
            connection.execute(
                """
                insert into event_clusters(
                    run_id, cluster_id, title, symbols_json, event_type, source_count,
                    first_seen_at, last_seen_at, summary, confidence, event_hashes_json
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    cluster.cluster_id,
                    cluster.title,
                    cluster.symbols_json,
                    cluster.event_type,
                    cluster.source_count,
                    cluster.first_seen_at,
                    cluster.last_seen_at,
                    cluster.summary,
                    cluster.confidence,
                    cluster.event_hashes_json,
                ),
            )

        for narrative in narratives:
            connection.execute(
                "delete from narratives where narrative_id = ?",
                (narrative.narrative_id,),
            )
            connection.execute(
                """
                insert into narratives(
                    narrative_id, name, direction, strength, related_symbols,
                    supporting_event_ids, contradicting_event_ids, updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    narrative.narrative_id,
                    narrative.name,
                    narrative.direction,
                    narrative.strength,
                    narrative.related_symbols_json,
                    narrative.supporting_event_ids_json,
                    narrative.contradicting_event_ids_json,
                    narrative.updated_at,
                ),
            )

        for symbol, filings in filings_by_symbol.items():
            for filing in filings:
                connection.execute(
                    """
                    insert or ignore into filings(
                        symbol, cik, form_type, filing_date, accession_number, filing_url, title
                    )
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        symbol,
                        filing.cik,
                        filing.form_type,
                        filing.filing_date,
                        filing.accession_number,
                        filing.filing_url,
                        filing.title,
                    ),
                )

        for retrieval in memory_retrievals:
            connection.execute(
                """
                insert into memory_retrievals(run_id, symbol, memory_type, retrieved_id, reason)
                values (?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    retrieval.symbol,
                    retrieval.memory_type,
                    retrieval.retrieved_id,
                    retrieval.reason,
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

        for symbol, trends in (recommendations_by_symbol or {}).items():
            for trend in trends:
                connection.execute(
                    """
                    insert into recommendation_trends(
                        run_id, symbol, period, strong_buy, buy, hold, sell, strong_sell
                    )
                    values (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        symbol,
                        trend.period,
                        trend.strong_buy,
                        trend.buy,
                        trend.hold,
                        trend.sell,
                        trend.strong_sell,
                    ),
                )

        for symbol, events in (earnings_by_symbol or {}).items():
            for event in events:
                connection.execute(
                    """
                    insert into earnings_events(
                        run_id, symbol, date, eps_estimate, revenue_estimate
                    )
                    values (?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        symbol,
                        event.date,
                        event.eps_estimate,
                        event.revenue_estimate,
                    ),
                )


def _create_tables(connection: sqlite3.Connection) -> None:
    create_cache_tables(connection)
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

        create table if not exists events (
            run_id integer,
            symbol text,
            event_type text,
            headline text,
            summary text,
            source text,
            published_at text,
            sentiment text,
            confidence integer,
            impact_score integer,
            related_symbols_json text,
            dedupe_hash text,
            cluster_id text
        );

        create table if not exists event_clusters (
            run_id integer,
            cluster_id text,
            title text,
            symbols_json text,
            event_type text,
            source_count integer,
            first_seen_at text,
            last_seen_at text,
            summary text,
            confidence integer,
            event_hashes_json text
        );

        create table if not exists narratives (
            narrative_id text primary key,
            name text,
            direction text,
            strength integer,
            related_symbols text,
            supporting_event_ids text,
            contradicting_event_ids text,
            updated_at text
        );

        create table if not exists filings (
            symbol text,
            cik text,
            form_type text,
            filing_date text,
            accession_number text primary key,
            filing_url text,
            title text
        );

        create table if not exists memory_retrievals (
            run_id integer,
            symbol text,
            memory_type text,
            retrieved_id text,
            reason text
        );

        create table if not exists recommendation_trends (
            run_id integer,
            symbol text,
            period text,
            strong_buy integer,
            buy integer,
            hold integer,
            sell integer,
            strong_sell integer
        );

        create table if not exists earnings_events (
            run_id integer,
            symbol text,
            date text,
            eps_estimate real,
            revenue_estimate real
        );
        """
    )
    _ensure_column(connection, "events", "cluster_id", "text")


def _ensure_column(connection: sqlite3.Connection, table_name: str, column_name: str, column_type: str) -> None:
    existing_columns = {
        row[1]
        for row in connection.execute(f"pragma table_info({table_name})").fetchall()
    }
    if column_name not in existing_columns:
        connection.execute(f"alter table {table_name} add column {column_name} {column_type}")


def ensure_schema(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        _create_tables(connection)


def save_memory_retrievals(
    database_path: Path,
    retrievals: list[MemoryRetrieval],
) -> None:
    ensure_schema(database_path)
    with sqlite3.connect(database_path) as connection:
        row = connection.execute("select id from runs order by id desc limit 1").fetchone()
        if row is None:
            return
        run_id = row[0]
        for retrieval in retrievals:
            connection.execute(
                """
                insert into memory_retrievals(run_id, symbol, memory_type, retrieved_id, reason)
                values (?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    retrieval.symbol,
                    retrieval.memory_type,
                    retrieval.retrieved_id,
                    retrieval.reason,
                ),
            )
