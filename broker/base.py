from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class Order:
    symbol: str
    side: str          # "BUY" or "SELL"
    quantity: float
    price: Optional[float] = None
    order_id: Optional[str] = None
    status: str = "PENDING"
    reject_reason: Optional[str] = None


@dataclass
class Position:
    symbol: str
    quantity: float
    entry_price: float
    stop_loss: float
    take_profit: float
    side: str          # "LONG" or "SHORT"


class BaseBroker(ABC):
    @abstractmethod
    def get_balance(self, asset: str = "USDT") -> float: ...

    @abstractmethod
    def get_asset_quantity(self, symbol: str) -> float: ...

    @abstractmethod
    def get_average_entry_price(self, symbol: str) -> float | None: ...

    @abstractmethod
    def get_price(self, symbol: str) -> float: ...

    @abstractmethod
    def place_market_order(self, symbol: str, side: str, quantity: float) -> Order: ...

    @abstractmethod
    def get_candles(self, symbol: str, interval: str, limit: int) -> pd.DataFrame: ...
