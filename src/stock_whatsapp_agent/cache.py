from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

from .providers import NewsItem


T = TypeVar("T")


class ResponseCache:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            create_cache_tables(connection)

    def get(self, cache_key: str) -> Any | None:
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                """
                select response_json from provider_cache
                where cache_key = ? and expires_at > ?
                """,
                (cache_key, now),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def set(
        self,
        cache_key: str,
        provider_name: str,
        operation: str,
        payload: Any,
        ttl_seconds: int,
    ) -> None:
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=ttl_seconds)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                insert or replace into provider_cache(
                    cache_key, provider_name, operation, response_json, created_at, expires_at
                )
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    cache_key,
                    provider_name,
                    operation,
                    json.dumps(payload),
                    now.isoformat(),
                    expires_at.isoformat(),
                ),
            )

    def record_news_seen(self, items: list[NewsItem]) -> None:
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.database_path) as connection:
            for item in items:
                news_hash = news_item_hash(item)
                existing = connection.execute(
                    "select seen_count from news_dedupe where news_hash = ?",
                    (news_hash,),
                ).fetchone()
                if existing:
                    connection.execute(
                        """
                        update news_dedupe
                        set last_seen_at = ?, seen_count = ?
                        where news_hash = ?
                        """,
                        (now, int(existing[0]) + 1, news_hash),
                    )
                else:
                    connection.execute(
                        """
                        insert into news_dedupe(
                            news_hash, symbol, headline, url, first_seen_at, last_seen_at, seen_count
                        )
                        values (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (news_hash, item.symbol, item.headline, item.url, now, now, 1),
                    )


def create_cache_tables(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        create table if not exists provider_cache (
            cache_key text primary key,
            provider_name text,
            operation text,
            response_json text,
            created_at text,
            expires_at text
        );

        create table if not exists news_dedupe (
            news_hash text primary key,
            symbol text,
            headline text,
            url text,
            first_seen_at text,
            last_seen_at text,
            seen_count integer
        );
        """
    )


def dataclass_to_payload(value: Any) -> Any:
    if isinstance(value, list):
        return [asdict(item) for item in value]
    return asdict(value)


def payload_to_dataclass_list(cls: type[T], payload: Any) -> list[T]:
    if not isinstance(payload, list):
        return []
    return [cls(**item) for item in payload]


def payload_to_dataclass(cls: type[T], payload: Any) -> T:
    return cls(**payload)


def make_cache_key(provider_name: str, operation: str) -> str:
    return f"{provider_name}:{operation}"


def news_item_hash(item: NewsItem) -> str:
    base = item.url or f"{item.source}:{item.headline}"
    normalized = " ".join(base.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def dedupe_news_items(items: list[NewsItem]) -> list[NewsItem]:
    seen = set()
    deduped = []
    for item in items:
        news_hash = news_item_hash(item)
        if news_hash in seen:
            continue
        seen.add(news_hash)
        deduped.append(item)
    return deduped
