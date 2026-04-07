import pandas as pd
import ta

from .base import BaseStrategy, Signal


class MACDStrategy(BaseStrategy):
    """Buy on MACD/signal-line bullish crossover; sell on bearish crossover."""

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        super().__init__("MACD")
        self.fast = fast
        self.slow = slow
        self.signal_period = signal

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.slow + self.signal_period + 2:
            return Signal.HOLD

        indicator = ta.trend.MACD(df["close"], self.fast, self.slow, self.signal_period)
        macd_hist = indicator.macd_diff()

        curr_hist = float(macd_hist.iloc[-1])

        # State-based: MACD-Histogramm positiv = bullish
        if curr_hist > 0:
            return Signal.BUY
        if curr_hist < 0:
            return Signal.SELL
        return Signal.HOLD
