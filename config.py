import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv

load_dotenv()


@dataclass
class RiskConfig:
    """Risk management parameters loaded from environment variables."""
    max_position_pct: float = float(os.getenv("MAX_POSITION_PCT", "0.08"))
    stop_loss_pct: float = float(os.getenv("STOP_LOSS_PCT", "0.025"))
    take_profit_pct: float = float(os.getenv("TAKE_PROFIT_PCT", "0.05"))
    max_daily_loss_pct: float = float(os.getenv("MAX_DAILY_LOSS_PCT", "0.10"))
    max_open_positions: int = int(os.getenv("MAX_OPEN_POSITIONS", "5"))


@dataclass
class Config:
    """Main application configuration. All sensitive values come from environment variables."""
    api_key: str = field(default_factory=lambda: os.getenv("BINANCE_API_KEY", ""))
    api_secret: str = field(default_factory=lambda: os.getenv("BINANCE_API_SECRET", ""))
    private_key_path: str = field(default_factory=lambda: os.getenv("BINANCE_PRIVATE_KEY_PATH", "").strip())
    private_key_pass: str = field(default_factory=lambda: os.getenv("BINANCE_PRIVATE_KEY_PASS", "").strip())
    testnet: bool = field(default_factory=lambda: os.getenv("BINANCE_TESTNET", "true").lower() == "true")
    ca_bundle: str = field(default_factory=lambda: os.getenv("BINANCE_CA_BUNDLE", "").strip())

    symbols: List[str] = field(
        default_factory=lambda: os.getenv("TRADING_SYMBOLS", "BTCUSDT,ETHUSDT").split(",")
    )
    timeframe: str = field(default_factory=lambda: os.getenv("TIMEFRAME", "15m"))
    lookback_candles: int = field(default_factory=lambda: int(os.getenv("LOOKBACK_CANDLES", "100")))
    min_signal_consensus: int = field(default_factory=lambda: int(os.getenv("MIN_SIGNAL_CONSENSUS", "2")))
    check_interval: int = field(default_factory=lambda: int(os.getenv("CHECK_INTERVAL", "60")))

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
