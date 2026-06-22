import pandas as pd
import ta

from .base import BaseStrategy, Signal


class MomentumStrategy(BaseStrategy):
    """Rate-of-Change breakout confirmed by an above-average volume spike."""

    def __init__(self, roc_period: int = 14, volume_factor: float = 1.5) -> None:
        super().__init__("Momentum")
        self.roc_period = roc_period
        self.volume_factor = volume_factor

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.roc_period + 2:
            return Signal.HOLD

        roc = ta.momentum.ROCIndicator(df["close"], window=self.roc_period).roc()
        current_roc = float(roc.iloc[-1])

        # Volumen-Bestätigung: Signal nur wenn aktuelles Volumen überdurchschnittlich ist.
        # Ohne Volumen-Filter feuert ROC > 0.2 zu häufig und liefert Rauschen.
        avg_volume = float(df["volume"].iloc[-20:].mean())
        current_volume = float(df["volume"].iloc[-1])
        volume_confirmed = avg_volume > 0 and current_volume >= avg_volume * self.volume_factor

        if current_roc > 0.5 and volume_confirmed:
            return Signal.BUY
        if current_roc < -0.5 and volume_confirmed:
            return Signal.SELL
        return Signal.HOLD
