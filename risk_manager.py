from config import RiskConfig
from broker.base import Position
from utils.logger import get_logger

logger = get_logger("RiskManager")


class RiskManager:
    def __init__(self, config: RiskConfig) -> None:
        self.config = config
        self._daily_start_balance: float | None = None

    # ------------------------------------------------------------------
    # Daily loss guard
    # ------------------------------------------------------------------

    def set_daily_start_balance(self, balance: float) -> None:
        self._daily_start_balance = balance
        logger.info(f"Daily start balance: {balance:.2f} USDT")

    def is_daily_loss_exceeded(self, current_balance: float) -> bool:
        if self._daily_start_balance is None or self._daily_start_balance == 0:
            return False
        loss_pct = (self._daily_start_balance - current_balance) / self._daily_start_balance
        if loss_pct >= self.config.max_daily_loss_pct:
            logger.warning(
                f"Daily loss limit hit: {loss_pct:.2%} >= {self.config.max_daily_loss_pct:.2%} — "
                "no new positions for today"
            )
            return True
        return False

    # ------------------------------------------------------------------
    # Position sizing
    # ------------------------------------------------------------------

    def calculate_quantity(self, balance: float, price: float) -> float:
        """Return how many units to buy, limited to max_position_pct of balance."""
        if price <= 0:
            return 0.0
        usdt_to_use = balance * self.config.max_position_pct
        return usdt_to_use / price

    # ------------------------------------------------------------------
    # Stop-loss / take-profit levels
    # ------------------------------------------------------------------

    def stop_loss_price(self, entry: float, side: str) -> float:
        if side == "LONG":
            return entry * (1.0 - self.config.stop_loss_pct)
        return entry * (1.0 + self.config.stop_loss_pct)

    def take_profit_price(self, entry: float, side: str) -> float:
        if side == "LONG":
            return entry * (1.0 + self.config.take_profit_pct)
        return entry * (1.0 - self.config.take_profit_pct)

    # ------------------------------------------------------------------
    # Exit check
    # ------------------------------------------------------------------

    def exit_reason(self, position: Position, current_price: float) -> str | None:
        """Return 'stop_loss', 'take_profit', or None."""
        if position.side == "LONG":
            if current_price <= position.stop_loss:
                logger.warning(
                    f"Stop-loss triggered: {position.symbol} @ {current_price:.4f} "
                    f"(SL={position.stop_loss:.4f})"
                )
                return "stop_loss"
            if current_price >= position.take_profit:
                logger.info(
                    f"Take-profit triggered: {position.symbol} @ {current_price:.4f} "
                    f"(TP={position.take_profit:.4f})"
                )
                return "take_profit"
        return None
