import pandas as pd
import ta

from .base import BaseStrategy, Signal


class BollingerStrategy(BaseStrategy):
    """Buy on lower-band touch; sell on upper-band breakout."""

    def __init__(self, period: int = 20, std_dev: float = 2.0) -> None:
        super().__init__("Bollinger")
        self.period = period
        self.std_dev = std_dev

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.period + 2:
            return Signal.HOLD

        bbands = ta.volatility.BollingerBands(df["close"], window=self.period, window_dev=self.std_dev)
        lower = bbands.bollinger_lband()
        upper = bbands.bollinger_hband()

        prev_close, curr_close = df["close"].iloc[-2], df["close"].iloc[-1]
        curr_lower, curr_upper = lower.iloc[-1], upper.iloc[-1]

        if prev_close >= curr_lower and curr_close < curr_lower:
            return Signal.BUY   # Price dipped below lower band → mean reversion buy
        if prev_close <= curr_upper and curr_close > curr_upper:
            return Signal.SELL  # Price broke above upper band → mean reversion sell
        return Signal.HOLD
