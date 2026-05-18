from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _optional_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _optional_float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


def _optional_bool(name: str, default: bool) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


@dataclass(frozen=True)
class Settings:
    stock_api_provider: str
    stock_api_key: str | None
    primary_market_provider: str
    fallback_market_providers: tuple[str, ...]
    provider_timeout_seconds: float
    quote_cache_ttl_seconds: int
    news_cache_ttl_seconds: int
    history_cache_ttl_seconds: int
    whatsapp_to: tuple[str, ...]
    watchlist: tuple[str, ...]
    top_gainers_limit: int
    news_items_per_stock: int
    api_request_delay_seconds: float
    save_daily_memory: bool
    memory_dir: Path
    database_path: Path
    dashboard_dir: Path
    chart_symbol: str
    generate_chart_widget: bool
    enable_sec_ingestion: bool
    enable_memory_retrieval: bool
    enable_vector_memory: bool
    vector_db_provider: str
    vector_memory_top_k: int
    sec_user_agent: str
    sec_filings_limit: int
    timezone: str
    send_time: str

    @classmethod
    def load(cls) -> "Settings":
        if load_dotenv is not None:
            load_dotenv()
        else:
            _load_env_file(Path(".env"))

        watchlist = tuple(symbol.upper() for symbol in _split_csv(_require("WATCHLIST")))
        recipients = tuple(_split_csv(_require("WHATSAPP_TO")))

        if not watchlist:
            raise ValueError("WATCHLIST must include at least one stock symbol")
        if not recipients:
            raise ValueError("WHATSAPP_TO must include at least one WhatsApp recipient")

        primary_market_provider = os.getenv(
            "PRIMARY_MARKET_PROVIDER",
            os.getenv("STOCK_API_PROVIDER", "yahoo"),
        ).strip().lower()

        return cls(
            stock_api_provider=primary_market_provider,
            stock_api_key=_provider_api_key(primary_market_provider),
            primary_market_provider=primary_market_provider,
            fallback_market_providers=tuple(
                provider.lower() for provider in _split_csv(os.getenv("FALLBACK_MARKET_PROVIDERS", "stooq,yahoo"))
            ),
            provider_timeout_seconds=_optional_float("PROVIDER_TIMEOUT_SECONDS", 8.0),
            quote_cache_ttl_seconds=_optional_int("QUOTE_CACHE_TTL_SECONDS", 300),
            news_cache_ttl_seconds=_optional_int("NEWS_CACHE_TTL_SECONDS", 21600),
            history_cache_ttl_seconds=_optional_int("HISTORY_CACHE_TTL_SECONDS", 86400),
            whatsapp_to=recipients,
            watchlist=watchlist,
            top_gainers_limit=_optional_int("TOP_GAINERS_LIMIT", 5),
            news_items_per_stock=_optional_int("NEWS_ITEMS_PER_STOCK", 2),
            api_request_delay_seconds=_optional_float("API_REQUEST_DELAY_SECONDS", 13.0),
            save_daily_memory=_optional_bool("SAVE_DAILY_MEMORY", True),
            memory_dir=Path(os.getenv("MEMORY_DIR", "memory/daily_stock").strip()),
            database_path=Path(os.getenv("DATABASE_PATH", "data/stock_agent.sqlite3").strip()),
            dashboard_dir=Path(os.getenv("DASHBOARD_DIR", "dashboard").strip()),
            chart_symbol=os.getenv("CHART_SYMBOL", "NVDA").strip().upper(),
            generate_chart_widget=_optional_bool("GENERATE_CHART_WIDGET", True),
            enable_sec_ingestion=_optional_bool("ENABLE_SEC_INGESTION", True),
            enable_memory_retrieval=_optional_bool("ENABLE_MEMORY_RETRIEVAL", False),
            enable_vector_memory=_optional_bool("ENABLE_VECTOR_MEMORY", False),
            vector_db_provider=os.getenv("VECTOR_DB_PROVIDER", "sqlite").strip().lower(),
            vector_memory_top_k=_optional_int("VECTOR_MEMORY_TOP_K", 3),
            sec_user_agent=os.getenv(
                "SEC_USER_AGENT",
                "OpenClawStockAgent/0.1 contact@example.com",
            ).strip(),
            sec_filings_limit=_optional_int("SEC_FILINGS_LIMIT", 5),
            timezone=os.getenv("TIMEZONE", "America/Los_Angeles").strip(),
            send_time=os.getenv("SEND_TIME", "13:30").strip(),
        )


def redact_recipients(recipients: Iterable[str]) -> list[str]:
    redacted = []
    for recipient in recipients:
        if len(recipient) <= 6:
            redacted.append("***")
        else:
            redacted.append(f"{recipient[:10]}***{recipient[-2:]}")
    return redacted


def _provider_api_key(provider_name: str) -> str | None:
    if provider_name == "finnhub":
        return (
            os.getenv("FINNHUB_API_KEY", "").strip()
            or os.getenv("STOCK_API_KEY", "").strip()
            or None
        )
    if provider_name == "alphavantage":
        return (
            os.getenv("ALPHAVANTAGE_API_KEY", "").strip()
            or os.getenv("STOCK_API_KEY", "").strip()
            or None
        )
    return os.getenv("STOCK_API_KEY", "").strip() or None


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(name, value)
