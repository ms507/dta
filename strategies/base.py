from abc import ABC, abstractmethod
from enum import Enum

import pandas as pd


class Signal(Enum):
    BUY = 1
    SELL = -1
    HOLD = 0


class BaseStrategy(ABC):
    def __init__(self, name: str, vote_weight: float = 1.0) -> None:
        self.name = name
        self.vote_weight = vote_weight

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame) -> Signal:
        """Return a trading signal given an OHLCV DataFrame."""
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name})"
