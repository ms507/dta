import pandas as pd
import ta

from .base import BaseStrategy, Signal


def _clip(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


class AIDecisionStrategy(BaseStrategy):
    """Weighted indicator model that behaves like a simple local AI vote.

    It does not need an external API or training pipeline. Instead it continuously
    scores market state from multiple indicators and emits BUY/SELL when the
    combined confidence is strong enough.
    """

    def __init__(self, buy_threshold: float = 0.10, sell_threshold: float = -0.10) -> None:
        super().__init__("AI_Decision", vote_weight=2.0)
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self._last_score: float = 0.0

    def last_score(self) -> float:
        return self._last_score

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        if len(df) < 35:
            return Signal.HOLD

        close = df["close"]
        volume = df["volume"]
        price = float(close.iloc[-1])
        if price <= 0:
            return Signal.HOLD

        rsi = float(ta.momentum.RSIIndicator(close, window=14).rsi().iloc[-1])

        macd = ta.trend.MACD(close, window_fast=12, window_slow=26, window_sign=9)
        macd_hist = float(macd.macd_diff().iloc[-1])

        ema_fast = float(ta.trend.EMAIndicator(close, window=9).ema_indicator().iloc[-1])
        ema_slow = float(ta.trend.EMAIndicator(close, window=21).ema_indicator().iloc[-1])
        sma_trend = float(ta.trend.SMAIndicator(close, window=50).sma_indicator().iloc[-1])

        bands = ta.volatility.BollingerBands(close, window=20, window_dev=2.0)
        lower_band = float(bands.bollinger_lband().iloc[-1])
        upper_band = float(bands.bollinger_hband().iloc[-1])
        middle_band = float(bands.bollinger_mavg().iloc[-1])

        roc = float(ta.momentum.ROCIndicator(close, window=14).roc().iloc[-1])
        avg_volume = float(volume.iloc[-20:].mean())
        current_volume = float(volume.iloc[-1])
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0

        # RSI: 30-65 bullish zone (positiv), >70 overbought (negativ)
        if rsi < 30:
            rsi_score = 0.8
        elif rsi < 50:
            rsi_score = 0.3
        elif rsi < 65:
            rsi_score = 0.2
        elif rsi < 75:
            rsi_score = -0.4
        else:
            rsi_score = -0.9

        macd_score = _clip((macd_hist / price) * 5000.0)
        ema_score = _clip(((ema_fast - ema_slow) / price) * 400.0)
        trend_score = _clip(((price - sma_trend) / price) * 250.0)

        band_width = max(upper_band - lower_band, price * 0.001)
        bollinger_score = _clip((middle_band - price) / band_width * 2.0)

        # Momentum ohne Volumen-Pflicht
        momentum_score = _clip(roc / 2.0)

        score = (
            0.25 * macd_score
            + 0.22 * ema_score
            + 0.18 * trend_score
            + 0.15 * rsi_score
            + 0.08 * bollinger_score
            + 0.12 * momentum_score
        )

        self._last_score = round(score, 4)

        import logging as _log
        _log.getLogger("AI_Decision").info(
            f"score={score:+.4f}  rsi={rsi:.1f}({rsi_score:+.2f})  "
            f"macd={macd_score:+.4f}  ema={ema_score:+.4f}  "
            f"trend={trend_score:+.4f}  boll={bollinger_score:+.4f}  "
            f"mom={momentum_score:+.4f}  threshold={self.buy_threshold}"
        )

        if score >= self.buy_threshold:
            return Signal.BUY
        if score <= self.sell_threshold:
            return Signal.SELL
        return Signal.HOLD