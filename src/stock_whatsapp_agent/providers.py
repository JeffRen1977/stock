from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from io import StringIO
from typing import Protocol

import requests


@dataclass(frozen=True)
class StockQuote:
    symbol: str
    price: float | None
    change: float | None
    change_percent: float | None
    volume: int | None = None


@dataclass(frozen=True)
class NewsItem:
    symbol: str
    headline: str
    source: str
    published_at: str
    summary: str
    url: str | None = None


@dataclass(frozen=True)
class TopGainer:
    symbol: str
    price: float | None
    change_percent: float | None
    volume: int | None = None


@dataclass(frozen=True)
class HistoricalBar:
    symbol: str
    date: str
    close: float | None
    volume: int | None


class StockDataProvider(Protocol):
    def get_quote(self, symbol: str) -> StockQuote:
        ...

    def get_news(self, symbol: str, limit: int) -> list[NewsItem]:
        ...

    def get_top_gainers(self, limit: int) -> list[TopGainer]:
        ...

    def get_history(self, symbol: str, period: str = "1mo", interval: str = "1d") -> list[HistoricalBar]:
        ...


class YahooFinanceProvider:
    search_url = "https://query2.finance.yahoo.com/v1/finance/search"
    screener_url = "https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved"
    chart_url = "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
    stooq_quote_url = "https://stooq.com/q/l/"

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0 Safari/537.36"
                )
            }
        )

    def _get(self, url: str, params: dict[str, str | int]) -> dict:
        try:
            response = self.session.get(url, params=params, timeout=8)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(str(exc)) from None

        payload = response.json()
        if isinstance(payload, dict) and payload.get("finance", {}).get("error"):
            raise RuntimeError(str(payload["finance"]["error"]))
        return payload

    def get_quote(self, symbol: str) -> StockQuote:
        try:
            payload = self._get(
                self.chart_url.format(symbol=symbol),
                {
                    "range": "5d",
                    "interval": "1d",
                },
            )
        except RuntimeError:
            return self._get_stooq_quote(symbol)

        results = payload.get("chart", {}).get("result", [])
        if not results:
            return self._get_stooq_quote(symbol)

        result = results[0]
        meta = result.get("meta", {})
        quote = result.get("indicators", {}).get("quote", [{}])[0]
        closes = [close for close in quote.get("close", []) if close is not None]
        latest = _to_float(meta.get("regularMarketPrice")) or (closes[-1] if closes else None)
        previous = _to_float(meta.get("chartPreviousClose")) or (
            closes[-2] if len(closes) >= 2 else None
        )
        change = latest - previous if latest is not None and previous is not None else None
        change_percent = (
            (change / previous) * 100
            if change is not None and previous not in (None, 0)
            else None
        )
        return StockQuote(
            symbol=symbol,
            price=latest,
            change=change,
            change_percent=change_percent,
            volume=_to_int(meta.get("regularMarketVolume")),
        )

    def _get_stooq_quote(self, symbol: str) -> StockQuote:
        stooq_symbol = f"{symbol.lower()}.us"
        try:
            response = self.session.get(
                self.stooq_quote_url,
                params={"s": stooq_symbol, "f": "sd2t2ohlcv", "h": "", "e": "csv"},
                timeout=8,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(str(exc)) from None

        rows = list(csv.DictReader(StringIO(response.text)))
        if not rows:
            return StockQuote(symbol=symbol, price=None, change=None, change_percent=None)

        row = rows[0]
        close = _to_float(row.get("Close"))
        open_price = _to_float(row.get("Open"))
        change = close - open_price if close is not None and open_price is not None else None
        change_percent = (
            (change / open_price) * 100
            if change is not None and open_price not in (None, 0)
            else None
        )
        return StockQuote(
            symbol=symbol,
            price=close,
            change=change,
            change_percent=change_percent,
            volume=_to_int(row.get("Volume")),
        )

    def get_news(self, symbol: str, limit: int) -> list[NewsItem]:
        payload = self._get(
            self.search_url,
            {
                "q": symbol,
                "quotesCount": 0,
                "newsCount": max(limit, 1),
            },
        )
        items = []
        for article in payload.get("news", [])[:limit]:
            headline = str(article.get("title", "")).strip() or "Untitled news item"
            items.append(
                NewsItem(
                    symbol=symbol,
                    headline=headline,
                    source=str(article.get("publisher", "")).strip() or "Yahoo Finance",
                    published_at=_format_unix_time(article.get("providerPublishTime")),
                    summary=headline,
                    url=article.get("link"),
                )
            )
        return items

    def get_top_gainers(self, limit: int) -> list[TopGainer]:
        payload = self._get(
            self.screener_url,
            {
                "scrIds": "day_gainers",
                "count": max(limit, 1),
                "formatted": "false",
            },
        )
        quotes = (
            payload.get("finance", {})
            .get("result", [{}])[0]
            .get("quotes", [])
        )
        gainers = []
        for quote in quotes[:limit]:
            symbol = str(quote.get("symbol", "")).strip()
            if not symbol:
                continue
            gainers.append(
                TopGainer(
                    symbol=symbol,
                    price=_to_float(quote.get("regularMarketPrice")),
                    change_percent=_to_float(quote.get("regularMarketChangePercent")),
                    volume=_to_int(quote.get("regularMarketVolume")),
                )
            )
        return gainers

    def get_history(self, symbol: str, period: str = "1mo", interval: str = "1d") -> list[HistoricalBar]:
        payload = self._get(
            self.chart_url.format(symbol=symbol),
            {
                "range": period,
                "interval": interval,
            },
        )
        results = payload.get("chart", {}).get("result", [])
        if not results:
            return []

        result = results[0]
        timestamps = result.get("timestamp", [])
        quote = result.get("indicators", {}).get("quote", [{}])[0]
        closes = quote.get("close", [])
        volumes = quote.get("volume", [])

        bars = []
        for idx, timestamp in enumerate(timestamps):
            bars.append(
                HistoricalBar(
                    symbol=symbol,
                    date=_format_unix_time(timestamp),
                    close=_to_float(closes[idx]) if idx < len(closes) else None,
                    volume=_to_int(volumes[idx]) if idx < len(volumes) else None,
                )
            )
        return bars


class AlphaVantageProvider:
    base_url = "https://www.alphavantage.co/query"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.session = requests.Session()

    def _get(self, params: dict[str, str | int]) -> dict:
        try:
            response = self.session.get(
                self.base_url,
                params={**params, "apikey": self.api_key},
                timeout=20,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(_redact_secret(str(exc), self.api_key)) from None

        payload = response.json()
        if "Error Message" in payload:
            raise RuntimeError(payload["Error Message"])
        if "Note" in payload:
            raise RuntimeError(payload["Note"])
        if "Information" in payload:
            raise RuntimeError(payload["Information"])
        return payload

    def get_quote(self, symbol: str) -> StockQuote:
        payload = self._get({"function": "GLOBAL_QUOTE", "symbol": symbol})
        quote = payload.get("Global Quote", {})
        if not quote:
            return StockQuote(symbol=symbol, price=None, change=None, change_percent=None)

        return StockQuote(
            symbol=symbol,
            price=_to_float(quote.get("05. price")),
            change=_to_float(quote.get("09. change")),
            change_percent=_percent_to_float(quote.get("10. change percent")),
            volume=_to_int(quote.get("06. volume")),
        )

    def get_news(self, symbol: str, limit: int) -> list[NewsItem]:
        payload = self._get(
            {
                "function": "NEWS_SENTIMENT",
                "tickers": symbol,
                "limit": max(limit, 1),
                "sort": "LATEST",
            }
        )
        items = []
        for article in payload.get("feed", [])[:limit]:
            items.append(
                NewsItem(
                    symbol=symbol,
                    headline=article.get("title", "").strip() or "Untitled news item",
                    source=article.get("source", "").strip() or "Unknown source",
                    published_at=_format_alpha_vantage_time(article.get("time_published", "")),
                    summary=article.get("summary", "").strip() or article.get("title", "").strip(),
                    url=article.get("url"),
                )
            )
        return items

    def get_top_gainers(self, limit: int) -> list[TopGainer]:
        payload = self._get({"function": "TOP_GAINERS_LOSERS"})
        gainers = []
        for item in payload.get("top_gainers", [])[:limit]:
            gainers.append(
                TopGainer(
                    symbol=item.get("ticker", "").strip(),
                    price=_to_float(item.get("price")),
                    change_percent=_percent_to_float(item.get("change_percentage")),
                    volume=_to_int(item.get("volume")),
                )
            )
        return [gainer for gainer in gainers if gainer.symbol]

    def get_history(self, symbol: str, period: str = "1mo", interval: str = "1d") -> list[HistoricalBar]:
        return []


class FinnhubProvider:
    base_url = "https://finnhub.io/api/v1"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.session = requests.Session()

    def _get(self, path: str, params: dict[str, str | int]) -> dict | list:
        try:
            response = self.session.get(
                f"{self.base_url}/{path}",
                params={**params, "token": self.api_key},
                timeout=20,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(_redact_secret(str(exc), self.api_key)) from None

        payload = response.json()
        if isinstance(payload, dict) and payload.get("error"):
            raise RuntimeError(payload["error"])
        if isinstance(payload, dict) and payload.get("message"):
            raise RuntimeError(payload["message"])
        return payload

    def get_quote(self, symbol: str) -> StockQuote:
        payload = self._get("quote", {"symbol": symbol})
        if not isinstance(payload, dict):
            return StockQuote(symbol=symbol, price=None, change=None, change_percent=None)

        return StockQuote(
            symbol=symbol,
            price=_to_float(payload.get("c")),
            change=_to_float(payload.get("d")),
            change_percent=_to_float(payload.get("dp")),
        )

    def get_news(self, symbol: str, limit: int) -> list[NewsItem]:
        today = date.today()
        payload = self._get(
            "company-news",
            {
                "symbol": symbol,
                "from": (today - timedelta(days=7)).isoformat(),
                "to": today.isoformat(),
            },
        )
        if not isinstance(payload, list):
            return []

        items = []
        for article in payload[:limit]:
            items.append(
                NewsItem(
                    symbol=symbol,
                    headline=str(article.get("headline", "")).strip() or "Untitled news item",
                    source=str(article.get("source", "")).strip() or "Unknown source",
                    published_at=str(article.get("datetime", "")).strip() or "recently",
                    summary=str(article.get("summary", "")).strip()
                    or str(article.get("headline", "")).strip(),
                    url=article.get("url"),
                )
            )
        return items

    def get_top_gainers(self, limit: int) -> list[TopGainer]:
        raise NotImplementedError(
            "Finnhub does not provide top gainers in this implementation. "
            "Use STOCK_API_PROVIDER=alphavantage for top gainers."
        )

    def get_history(self, symbol: str, period: str = "1mo", interval: str = "1d") -> list[HistoricalBar]:
        return []


def build_provider(provider_name: str, api_key: str | None) -> StockDataProvider:
    if provider_name == "yahoo":
        return YahooFinanceProvider()
    if provider_name == "alphavantage":
        if not api_key:
            raise ValueError("STOCK_API_KEY is required when STOCK_API_PROVIDER=alphavantage")
        return AlphaVantageProvider(api_key)
    if provider_name == "finnhub":
        if not api_key:
            raise ValueError("STOCK_API_KEY is required when STOCK_API_PROVIDER=finnhub")
        return FinnhubProvider(api_key)
    raise ValueError("Unsupported STOCK_API_PROVIDER. Use 'yahoo', 'alphavantage', or 'finnhub'.")


def _to_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace("%", ""))
    except ValueError:
        return None


def _to_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except ValueError:
        return None


def _percent_to_float(value: object) -> float | None:
    return _to_float(value)


def _redact_secret(message: str, secret: str) -> str:
    return message.replace(secret, "***") if secret else message


def _format_unix_time(value: object) -> str:
    if value is None or value == "":
        return "recently"
    try:
        return datetime.fromtimestamp(int(value)).date().isoformat()
    except (OSError, TypeError, ValueError):
        return "recently"


def _format_alpha_vantage_time(value: str) -> str:
    if len(value) == 15 and "T" in value:
        return f"{value[:4]}-{value[4:6]}-{value[6:8]} {value[9:11]}:{value[11:13]}"
    return value or "recently"
