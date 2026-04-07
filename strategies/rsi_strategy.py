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

        # State-based: BUY wenn RSI in gesunder Bullzone, SELL wenn überkauft
        if curr < self.overbought:
            return Signal.BUY
        if curr >= self.overbought:
            return Signal.SELL
        return Signal.HOLD
