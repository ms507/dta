from typing import Dict, Optional

from broker.base import Position
from utils.logger import get_logger

logger = get_logger("Portfolio")


class Portfolio:
    def __init__(self) -> None:
        self.positions: Dict[str, Position] = {}

    def open(self, position: Position) -> None:
        self.positions[position.symbol] = position
        logger.info(
            f"Position opened: {position.side} {position.quantity:.6f} {position.symbol} "
            f"@ {position.entry_price:.4f} | SL={position.stop_loss:.4f} TP={position.take_profit:.4f}"
        )

    def close(self, symbol: str) -> Optional[Position]:
        pos = self.positions.pop(symbol, None)
        if pos:
            logger.info(f"Position closed: {symbol}")
        return pos

    def has(self, symbol: str) -> bool:
        return symbol in self.positions

    def get(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)

    def count(self) -> int:
        return len(self.positions)

    def summary(self, get_price_fn) -> str:
        if not self.positions:
            return "No open positions"
        lines = ["Open positions:"]
        for symbol, pos in self.positions.items():
            current = get_price_fn(symbol)
            if pos.side == "LONG":
                pnl_pct = (current - pos.entry_price) / pos.entry_price * 100
            else:
                pnl_pct = (pos.entry_price - current) / pos.entry_price * 100
            lines.append(
                f"  {symbol:<12} {pos.side}  qty={pos.quantity:.6f}  "
                f"entry={pos.entry_price:.4f}  now={current:.4f}  "
                f"P&L={pnl_pct:+.2f}%"
            )
        return "\n".join(lines)
