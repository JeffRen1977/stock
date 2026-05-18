from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime

from ..events import StockEvent


@dataclass(frozen=True)
class EventCluster:
    cluster_id: str
    title: str
    symbols: tuple[str, ...]
    event_type: str
    source_count: int
    first_seen_at: str
    last_seen_at: str
    summary: str
    confidence: int
    event_hashes: tuple[str, ...]

    @property
    def symbols_json(self) -> str:
        return json.dumps(list(self.symbols))

    @property
    def event_hashes_json(self) -> str:
        return json.dumps(list(self.event_hashes))


STOP_WORDS = {
    "about",
    "after",
    "against",
    "amid",
    "and",
    "are",
    "as",
    "for",
    "from",
    "has",
    "have",
    "into",
    "its",
    "more",
    "new",
    "not",
    "over",
    "says",
    "that",
    "the",
    "their",
    "this",
    "to",
    "with",
}

MAX_CLUSTER_SPAN_DAYS = 2
MIN_KEYWORD_OVERLAP = 0.3


def cluster_events(
    events_by_symbol: dict[str, list[StockEvent]],
) -> tuple[dict[str, list[StockEvent]], dict[str, list[EventCluster]]]:
    clustered_events_by_symbol: dict[str, list[StockEvent]] = {}
    clusters_by_symbol: dict[str, list[EventCluster]] = {}

    for symbol, events in events_by_symbol.items():
        groups: list[list[StockEvent]] = []
        group_keywords: list[set[str]] = []

        for event in sorted(events, key=_event_sort_key):
            keywords = _keywords(event)
            match_index = _matching_group_index(event, keywords, groups, group_keywords)
            if match_index is None:
                groups.append([event])
                group_keywords.append(set(keywords))
            else:
                groups[match_index].append(event)
                group_keywords[match_index].update(keywords)

        clusters = [
            _build_cluster(group, keywords)
            for group, keywords in zip(groups, group_keywords)
        ]
        clusters_by_symbol[symbol] = clusters

        clustered_events = []
        for cluster in clusters:
            clustered_events.extend(
                replace(event, cluster_id=cluster.cluster_id)
                for event in _events_for_cluster(events, cluster)
            )
        clustered_events_by_symbol[symbol] = clustered_events

    return clustered_events_by_symbol, clusters_by_symbol


def flatten_clusters(clusters_by_symbol: dict[str, list[EventCluster]]) -> list[EventCluster]:
    return [cluster for clusters in clusters_by_symbol.values() for cluster in clusters]


def _matching_group_index(
    event: StockEvent,
    keywords: set[str],
    groups: list[list[StockEvent]],
    group_keywords: list[set[str]],
) -> int | None:
    for index, group in enumerate(groups):
        representative = group[0]
        if representative.symbol != event.symbol or representative.event_type != event.event_type:
            continue
        if not _published_close_enough(representative.published_at, event.published_at):
            continue
        if _keyword_similarity(keywords, group_keywords[index]) >= MIN_KEYWORD_OVERLAP:
            return index
    return None


def _build_cluster(events: list[StockEvent], keywords: set[str]) -> EventCluster:
    first_event = events[0]
    sorted_events = sorted(events, key=_event_sort_key)
    sources = {event.source for event in events if event.source}
    symbols = tuple(
        sorted(
            {event.symbol for event in events}
            | {symbol for event in events for symbol in event.related_symbols}
        )
    )
    first_seen_at = sorted_events[0].published_at
    last_seen_at = sorted_events[-1].published_at
    confidence = min(
        95,
        round(sum(event.confidence for event in events) / len(events))
        + min(max(len(sources) - 1, 0), 3) * 3,
    )
    cluster_id = _cluster_id(first_event.symbol, first_event.event_type, first_seen_at, keywords)

    return EventCluster(
        cluster_id=cluster_id,
        title=first_event.headline,
        symbols=symbols or (first_event.symbol,),
        event_type=first_event.event_type,
        source_count=max(1, len(sources)),
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
        summary=_cluster_summary(first_event, events, max(1, len(sources))),
        confidence=confidence,
        event_hashes=tuple(event.dedupe_hash for event in events),
    )


def _events_for_cluster(events: list[StockEvent], cluster: EventCluster) -> list[StockEvent]:
    event_hashes = set(cluster.event_hashes)
    return [event for event in events if event.dedupe_hash in event_hashes]


def _cluster_summary(first_event: StockEvent, events: list[StockEvent], source_count: int) -> str:
    summary = first_event.summary or first_event.headline
    if len(events) == 1:
        return summary
    return f"{summary} Similar coverage appeared across {source_count} source(s)."


def _keywords(event: StockEvent) -> set[str]:
    text = f"{event.headline} {event.summary}".lower()
    words = re.findall(r"[a-z0-9]+", text)
    return {
        word
        for word in words
        if len(word) > 3 and word not in STOP_WORDS and not word.isdigit()
    }


def _keyword_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _published_close_enough(left: str, right: str) -> bool:
    left_dt = _parse_datetime(left)
    right_dt = _parse_datetime(right)
    if left_dt is None or right_dt is None:
        return left[:10] == right[:10] if left and right else True
    return abs((left_dt - right_dt).days) <= MAX_CLUSTER_SPAN_DAYS


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d")
        except ValueError:
            return None


def _event_sort_key(event: StockEvent) -> tuple[str, str]:
    return (event.published_at, event.dedupe_hash)


def _cluster_id(symbol: str, event_type: str, first_seen_at: str, keywords: set[str]) -> str:
    keyword_key = "-".join(sorted(keywords)[:8])
    base = f"{symbol}:{event_type}:{first_seen_at[:10]}:{keyword_key}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]
