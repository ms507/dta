import pandas as pd
import ta

from .base import BaseStrategy, Signal


class MACrossoverStrategy(BaseStrategy):
    """Golden/Death cross of two EMAs."""

    def __init__(self, fast_period: int = 9, slow_period: int = 21) -> None:
        super().__init__("MA_Crossover")
        self.fast_period = fast_period
        self.slow_period = slow_period

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.slow_period + 2:
            return Signal.HOLD

        fast_ema = ta.trend.EMAIndicator(df["close"], window=self.fast_period).ema_indicator()
        slow_ema = ta.trend.EMAIndicator(df["close"], window=self.slow_period).ema_indicator()

        curr_fast = float(fast_ema.iloc[-1])
        curr_slow = float(slow_ema.iloc[-1])

        # State-based: schnelle EMA über langsamer = bullish
        if curr_fast > curr_slow:
            return Signal.BUY
        if curr_fast < curr_slow:
            return Signal.SELL
        return Signal.HOLD
