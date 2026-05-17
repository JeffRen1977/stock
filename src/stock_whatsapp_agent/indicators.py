from __future__ import annotations

from dataclasses import dataclass

from .providers import HistoricalBar


@dataclass(frozen=True)
class TechnicalIndicators:
    symbol: str
    latest_close: float | None
    latest_volume: int | None
    sma_5: float | None
    sma_20: float | None
    rsi_14: float | None
    momentum_5d_percent: float | None


def calculate_indicators(symbol: str, bars: list[HistoricalBar]) -> TechnicalIndicators:
    closes = [bar.close for bar in bars if bar.close is not None]
    latest = bars[-1] if bars else None

    return TechnicalIndicators(
        symbol=symbol,
        latest_close=closes[-1] if closes else None,
        latest_volume=latest.volume if latest else None,
        sma_5=_sma(closes, 5),
        sma_20=_sma(closes, 20),
        rsi_14=_rsi(closes, 14),
        momentum_5d_percent=_momentum(closes, 5),
    )


def _sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _momentum(values: list[float], days: int) -> float | None:
    if len(values) <= days or values[-days - 1] == 0:
        return None
    return ((values[-1] - values[-days - 1]) / values[-days - 1]) * 100


def _rsi(values: list[float], window: int) -> float | None:
    if len(values) <= window:
        return None

    gains = []
    losses = []
    for previous, current in zip(values[-window - 1 : -1], values[-window:]):
        change = current - previous
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))

    average_gain = sum(gains) / window
    average_loss = sum(losses) / window
    if average_loss == 0:
        return 100.0

    relative_strength = average_gain / average_loss
    return 100 - (100 / (1 + relative_strength))
