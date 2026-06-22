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
        prev_fast = float(fast_ema.iloc[-2])
        prev_slow = float(slow_ema.iloc[-2])

        # Crossover-based mit Mindestabstand (0.05%) um False-Signals im Seitwärtsmarkt
        # zu vermeiden. BUY nur bei echtem Kreuz nach oben, SELL bei Kreuz nach unten.
        min_gap = curr_slow * 0.0005
        crossed_up = prev_fast <= prev_slow and curr_fast > curr_slow + min_gap
        crossed_down = prev_fast >= prev_slow and curr_fast < curr_slow - min_gap

        if crossed_up:
            return Signal.BUY
        if crossed_down:
            return Signal.SELL
        return Signal.HOLD
