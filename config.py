import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv

load_dotenv()


def _env_str(key: str, default: str = "") -> str:
    value = os.getenv(key)
    if value is None:
        return default
    value = value.strip()
    return value if value != "" else default


def _env_int(key: str, default: int) -> int:
    raw = _env_str(key, str(default))
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    raw = _env_str(key, str(default))
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass
class RiskConfig:
    """Risk management parameters loaded from environment variables."""
    max_position_pct: float = _env_float("MAX_POSITION_PCT", 0.08)
    stop_loss_pct: float = _env_float("STOP_LOSS_PCT", 0.025)
    take_profit_pct: float = _env_float("TAKE_PROFIT_PCT", 0.05)
    max_daily_loss_pct: float = _env_float("MAX_DAILY_LOSS_PCT", 0.10)
    max_open_positions: int = _env_int("MAX_OPEN_POSITIONS", 5)
    min_entry_quote: float = _env_float("MIN_ENTRY_QUOTE", 10.0)
    max_entry_quote: float = _env_float("MAX_ENTRY_QUOTE", 15.0)


@dataclass
class Config:
    """Main application configuration. All sensitive values come from environment variables."""
    api_key: str = field(default_factory=lambda: _env_str("BINANCE_API_KEY", ""))
    api_secret: str = field(default_factory=lambda: _env_str("BINANCE_API_SECRET", ""))
    private_key_path: str = field(default_factory=lambda: _env_str("BINANCE_PRIVATE_KEY_PATH", ""))
    private_key_pass: str = field(default_factory=lambda: _env_str("BINANCE_PRIVATE_KEY_PASS", ""))
    testnet: bool = field(default_factory=lambda: _env_str("BINANCE_TESTNET", "true").lower() == "true")
    ca_bundle: str = field(default_factory=lambda: _env_str("BINANCE_CA_BUNDLE", ""))
    binance_request_timeout: int = field(default_factory=lambda: _env_int("BINANCE_REQUEST_TIMEOUT", 20))
    binance_max_retries: int = field(default_factory=lambda: _env_int("BINANCE_MAX_RETRIES", 3))
    binance_retry_backoff_sec: float = field(default_factory=lambda: _env_float("BINANCE_RETRY_BACKOFF_SEC", 1.0))

    symbols: List[str] = field(
        default_factory=lambda: _env_str("TRADING_SYMBOLS", "BTCUSDT,ETHUSDT").split(",")
    )
    timeframe: str = field(default_factory=lambda: _env_str("TIMEFRAME", "15m"))
    lookback_candles: int = field(default_factory=lambda: _env_int("LOOKBACK_CANDLES", 100))
    min_signal_consensus: int = field(default_factory=lambda: _env_int("MIN_SIGNAL_CONSENSUS", 2))
    check_interval: int = field(default_factory=lambda: _env_int("CHECK_INTERVAL", 60))
    trading_cooldown_sec: int = field(default_factory=lambda: _env_int("TRADING_COOLDOWN_SEC", 900))
    min_hold_sec: int = field(default_factory=lambda: _env_int("MIN_HOLD_SEC", 600))
    min_signal_exit_pnl_pct: float = field(default_factory=lambda: _env_float("MIN_SIGNAL_EXIT_PNL_PCT", 0.0035))
    min_ai_buy_score: float = field(default_factory=lambda: _env_float("MIN_AI_BUY_SCORE", 0.08))
    max_ai_sell_score: float = field(default_factory=lambda: _env_float("MAX_AI_SELL_SCORE", -0.08))

    risk: RiskConfig = field(default_factory=RiskConfig)

    def validate(self) -> None:
        """Raise ValueError if required credentials are missing."""
        if not self.api_key:
            raise ValueError(
                "BINANCE_API_KEY must be set in the .env file."
            )
        if not self.api_secret and not self.private_key_path:
            raise ValueError(
                "Set either BINANCE_API_SECRET (classic HMAC key) or BINANCE_PRIVATE_KEY_PATH (Ed25519/RSA key)."
            )
        if self.private_key_path and not Path(self.private_key_path).exists():
            raise ValueError(
                f"BINANCE_PRIVATE_KEY_PATH does not exist: {self.private_key_path}"
            )
        if self.risk.max_position_pct > 0.10:
            raise ValueError("MAX_POSITION_PCT > 10% is too high. Please lower the risk.")
        if self.risk.max_daily_loss_pct > 0.20:
            raise ValueError("MAX_DAILY_LOSS_PCT > 20% is too high. Please lower the risk.")
        if self.risk.min_entry_quote < 0:
            raise ValueError("MIN_ENTRY_QUOTE must be >= 0.")
        if self.risk.max_entry_quote < 0:
            raise ValueError("MAX_ENTRY_QUOTE must be >= 0.")
        if self.risk.max_entry_quote and self.risk.min_entry_quote > self.risk.max_entry_quote:
            raise ValueError("MIN_ENTRY_QUOTE must be <= MAX_ENTRY_QUOTE.")
        if self.binance_request_timeout < 1:
            raise ValueError("BINANCE_REQUEST_TIMEOUT must be >= 1 second.")
        if self.binance_max_retries < 0:
            raise ValueError("BINANCE_MAX_RETRIES must be >= 0.")
        if self.binance_retry_backoff_sec < 0:
            raise ValueError("BINANCE_RETRY_BACKOFF_SEC must be >= 0.")
        if self.trading_cooldown_sec < 0:
            raise ValueError("TRADING_COOLDOWN_SEC must be >= 0.")
        if self.min_hold_sec < 0:
            raise ValueError("MIN_HOLD_SEC must be >= 0.")
        if self.min_signal_exit_pnl_pct < 0:
            raise ValueError("MIN_SIGNAL_EXIT_PNL_PCT must be >= 0.")
        if self.min_ai_buy_score < -1.0 or self.min_ai_buy_score > 1.0:
            raise ValueError("MIN_AI_BUY_SCORE must be between -1.0 and 1.0.")
        if self.max_ai_sell_score < -1.0 or self.max_ai_sell_score > 1.0:
            raise ValueError("MAX_AI_SELL_SCORE must be between -1.0 and 1.0.")
