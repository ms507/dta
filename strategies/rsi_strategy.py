import pandas as pd
import ta

from .base import BaseStrategy, Signal


class RSIStrategy(BaseStrategy):
    """Buy when RSI crosses above oversold level; sell when it crosses below overbought."""

    def __init__(self, period: int = 14, oversold: float = 30.0, overbought: float = 70.0) -> None:
        super().__init__("RSI")
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.period + 2:
            return Signal.HOLD

        rsi = ta.momentum.RSIIndicator(df["close"], window=self.period).rsi()
        curr = float(rsi.iloc[-1])
        prev = float(rsi.iloc[-2])

        # Crossover-based: BUY wenn RSI aus der überverkauften Zone herauskommt,
        # SELL wenn RSI aus der überkauften Zone herauskommt.
        # Zwischen den Schwellen (30–70): HOLD — kein klares Signal.
        if prev <= self.oversold and curr > self.oversold:
            return Signal.BUY
        if curr <= self.oversold:
            return Signal.BUY
        if prev >= self.overbought and curr < self.overbought:
            return Signal.SELL
        if curr >= self.overbought:
            return Signal.SELL
        return Signal.HOLD
