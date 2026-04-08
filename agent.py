import time
from datetime import date

import pandas as pd

from config import Config
from broker.binance_broker import BinanceBroker
from broker.base import Position
from strategies import (
    AIDecisionStrategy,
    RSIStrategy,
    MACDStrategy,
    MACrossoverStrategy,
    BollingerStrategy,
    MomentumStrategy,
    Signal,
)
from risk_manager import RiskManager
from portfolio import Portfolio
from utils.logger import get_logger

logger = get_logger("TradingAgent")


class TradingAgent:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.broker = BinanceBroker(
            config.api_key,
            config.api_secret,
            config.testnet,
            config.ca_bundle or None,
            config.private_key_path or None,
            config.private_key_pass or None,
            config.binance_request_timeout,
            config.binance_max_retries,
            config.binance_retry_backoff_sec,
        )
        self.risk = RiskManager(config.risk)
        self.portfolio = Portfolio()
        self._ai_strategy = AIDecisionStrategy()
        self.strategies = [
            self._ai_strategy,
            RSIStrategy(),
            MACDStrategy(),
            MACrossoverStrategy(),
            BollingerStrategy(),
            MomentumStrategy(),
        ]
        self._running = False
        self._last_reset_date: date | None = None
        self._quote_asset: str = self._detect_quote_asset()
        self._last_ai_scores: dict[str, float] = {}
        self._min_ai_buy_score = self.config.min_ai_buy_score
        self._max_ai_sell_score = self.config.max_ai_sell_score
        self._trading_cooldown_sec = max(0, int(self.config.trading_cooldown_sec))
        self._min_hold_sec = max(0, int(self.config.min_hold_sec))
        self._min_signal_exit_pnl_pct = max(0.0, float(self.config.min_signal_exit_pnl_pct))
        self._position_opened_at: dict[str, float] = {}
        self._last_exit_at: dict[str, float] = {}

    def _record_position_opened(self, symbol: str) -> None:
        self._position_opened_at[symbol] = time.time()

    def _record_position_closed(self, symbol: str) -> None:
        self._last_exit_at[symbol] = time.time()
        self._position_opened_at.pop(symbol, None)

    def _position_age_seconds(self, symbol: str) -> float:
        opened_at = self._position_opened_at.get(symbol)
        if opened_at is None:
            return 0.0
        return max(0.0, time.time() - opened_at)

    def _is_reentry_cooldown_active(self, symbol: str) -> bool:
        if self._trading_cooldown_sec <= 0:
            return False
        last_exit = self._last_exit_at.get(symbol)
        if last_exit is None:
            return False
        return (time.time() - last_exit) < self._trading_cooldown_sec

    def _detect_quote_asset(self) -> str:
        """Infer quote currency from the first configured symbol."""
        suffixes = ("USDC", "USDT", "BUSD", "FDUSD", "EUR", "BTC", "ETH")
        first = self.config.symbols[0].upper() if self.config.symbols else "BTCUSDT"
        for suffix in suffixes:
            if first.endswith(suffix):
                logger.info(f"Quote asset detected: {suffix}")
                return suffix
        logger.warning(f"Could not detect quote asset from {first}, falling back to USDT")
        return "USDT"

    # ------------------------------------------------------------------
    # Daily reset
    # ------------------------------------------------------------------

    def _portfolio_equity(self) -> float:
        """Estimate current account equity in quote currency for configured symbols."""
        equity = self.broker.get_balance(self._quote_asset)
        seen_assets: set[str] = set()

        for symbol in self.config.symbols:
            symbol = symbol.upper().strip()
            base_asset = symbol
            if symbol.endswith(self._quote_asset):
                base_asset = symbol[: -len(self._quote_asset)]

            if base_asset in seen_assets:
                continue
            seen_assets.add(base_asset)

            quantity = self.broker.get_asset_quantity(symbol)
            if quantity <= 0:
                continue

            price = self.broker.get_price(symbol)
            if price <= 0:
                continue

            equity += quantity * price

        return equity

    def _maybe_reset_daily(self) -> None:
        today = date.today()
        if self._last_reset_date != today:
            equity = self._portfolio_equity()
            self.risk.set_daily_start_balance(equity)
            self._last_reset_date = today

    # ------------------------------------------------------------------
    # Consensus signal
    # ------------------------------------------------------------------

    def _trend_filter_buy(self, symbol: str) -> tuple[bool, str]:
        """Allow BUY only when short-term trend aligns with higher-timeframe bias."""
        df = self.broker.get_candles(symbol, self.config.timeframe, max(80, self.config.lookback_candles))
        if df.empty or len(df) < 55:
            return False, "insufficient_candles"

        close = pd.to_numeric(df["close"], errors="coerce")
        close = close.dropna()
        if len(close) < 55:
            return False, "invalid_close_series"

        ema_fast = close.ewm(span=9, adjust=False).mean().iloc[-1]
        ema_slow = close.ewm(span=21, adjust=False).mean().iloc[-1]
        sma50 = close.rolling(50).mean().iloc[-1]
        sma200 = close.rolling(200).mean().iloc[-1]
        price = close.iloc[-1]

        if pd.isna(ema_fast) or pd.isna(ema_slow) or pd.isna(sma50):
            return False, "trend_nan"

        # More lenient: allow trades when price is near SMA50 or above
        if sma200 > 0 and price < sma200 * 0.95:
            return False, "price_below_sma200"
        if ema_fast <= ema_slow * 0.99:  # Allow small deviation
            return False, "ema9_below_ema21"
        return True, "ok"

    def _consensus_signal(self, symbol: str) -> Signal:
        df = self.broker.get_candles(symbol, self.config.timeframe, self.config.lookback_candles)
        if df.empty:
            logger.warning(f"No candle data for {symbol}")
            return Signal.HOLD

        votes: dict[Signal, float] = {Signal.BUY: 0.0, Signal.SELL: 0.0, Signal.HOLD: 0.0}
        raw_votes: dict[Signal, int] = {Signal.BUY: 0, Signal.SELL: 0, Signal.HOLD: 0}
        for strategy in self.strategies:
            sig = strategy.generate_signal(df)
            votes[sig] += strategy.vote_weight
            raw_votes[sig] += 1
            logger.debug(
                f"{symbol} | {strategy.name:20s} → {sig.name} "
                f"(weight={strategy.vote_weight:.1f})"
            )

        ai_score = self._ai_strategy.last_score()
        self._last_ai_scores[symbol] = ai_score
        logger.info(
            f"{symbol} | BUY={votes[Signal.BUY]:.1f} ({raw_votes[Signal.BUY]})  "
            f"SELL={votes[Signal.SELL]:.1f} ({raw_votes[Signal.SELL]})  "
            f"HOLD={votes[Signal.HOLD]:.1f} ({raw_votes[Signal.HOLD]})  "
            f"AI_score={ai_score:+.4f}  (need {self.config.min_signal_consensus})"
        )

        buy_votes = votes[Signal.BUY]
        sell_votes = votes[Signal.SELL]

        if buy_votes >= self.config.min_signal_consensus or sell_votes >= self.config.min_signal_consensus:
            if buy_votes > sell_votes and ai_score >= self._min_ai_buy_score:
                return Signal.BUY
            if sell_votes > buy_votes and ai_score <= self._max_ai_sell_score:
                return Signal.SELL

            logger.info(
                f"{symbol} | Signal suppressed by AI filter "
                f"(ai={ai_score:+.4f}, buy_min={self._min_ai_buy_score:+.2f}, "
                f"sell_max={self._max_ai_sell_score:+.2f})"
            )
        return Signal.HOLD

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------

    def _sync_account_positions(self) -> None:
        """Import and refresh existing exchange holdings for configured symbols."""
        for symbol in self.config.symbols:
            quantity = self.broker.get_asset_quantity(symbol)
            existing = self.portfolio.get(symbol)

            if quantity <= 0:
                if existing is not None:
                    self.portfolio.close(symbol)
                    self._record_position_closed(symbol)
                    logger.info(f"Removed {symbol} from portfolio because no exchange balance remains")
                continue

            current_price = self.broker.get_price(symbol)
            if current_price <= 0:
                continue

            average_entry = self.broker.get_average_entry_price(symbol)
            entry_price = average_entry or (existing.entry_price if existing else current_price)

            synced_position = Position(
                symbol=symbol,
                quantity=quantity,
                entry_price=entry_price,
                stop_loss=self.risk.stop_loss_price(entry_price, "LONG"),
                take_profit=self.risk.take_profit_price(entry_price, "LONG"),
                side="LONG",
            )

            if existing is None:
                self.portfolio.open(synced_position)
                self._record_position_opened(symbol)
                logger.info(
                    f"Imported existing exchange holding for {symbol}: qty={quantity:.6f} "
                    f"entry={entry_price:.4f}"
                )
                continue

            quantity_changed = abs(existing.quantity - quantity) > 1e-12
            entry_changed = abs(existing.entry_price - entry_price) > 1e-12
            if quantity_changed or entry_changed:
                self.portfolio.open(synced_position)
                self._position_opened_at.setdefault(symbol, time.time())
                logger.info(
                    f"Synchronized exchange holding for {symbol}: qty={quantity:.6f} "
                    f"entry={entry_price:.4f}"
                )

    def _check_open_positions(self) -> None:
        """Check SL/TP for all open positions and exit if triggered."""
        for symbol in list(self.portfolio.positions):
            pos = self.portfolio.get(symbol)
            if pos is None:
                continue
            current_price = self.broker.get_price(symbol)
            reason = self.risk.exit_reason(pos, current_price)
            if reason:
                order = self.broker.place_market_order(symbol, "SELL", pos.quantity)
                if order.status in ("FILLED", "NEW"):
                    self.portfolio.close(symbol)
                    self._record_position_closed(symbol)
                    logger.info(f"Exited {symbol} — reason: {reason}")

    def _handle_signal(self, symbol: str, signal: Signal) -> None:
        quote_balance = self.broker.get_balance(self._quote_asset)
        equity = self._portfolio_equity()

        if signal == Signal.BUY:
            has_position = self.portfolio.has(symbol)
            ai_score = self._last_ai_scores.get(symbol, 0.0)

            if not has_position and self._is_reentry_cooldown_active(symbol):
                elapsed = time.time() - self._last_exit_at.get(symbol, 0.0)
                logger.info(
                    f"{symbol} | BUY blocked by cooldown "
                    f"({elapsed:.0f}s < {self._trading_cooldown_sec}s)"
                )
                return

            if ai_score < self._min_ai_buy_score:
                logger.info(
                    f"{symbol} | BUY blocked: AI score too weak "
                    f"({ai_score:+.4f} < {self._min_ai_buy_score:+.2f})"
                )
                return

            trend_ok, trend_reason = self._trend_filter_buy(symbol)
            if not trend_ok:
                logger.info(f"{symbol} | BUY blocked by trend filter ({trend_reason})")
                return

            if not has_position and self.portfolio.count() >= self.config.risk.max_open_positions:
                logger.warning(
                    f"Max open positions ({self.config.risk.max_open_positions}) reached — "
                    f"skipping {symbol}"
                )
                return
            if self.risk.is_daily_loss_exceeded(equity):
                logger.warning("Daily loss limit reached — no new trades today")
                return

            price = self.broker.get_price(symbol)
            if price <= 0:
                logger.warning(f"No valid price for {symbol}, skipping BUY")
                return

            target_quantity = self.risk.calculate_quantity(quote_balance, price, equity)
            quantity_to_buy = target_quantity

            if has_position:
                current_position = self.portfolio.get(symbol)
                if current_position is None:
                    logger.warning(f"{symbol} flagged as open but position is missing")
                    return
                quantity_to_buy = max(0.0, target_quantity - current_position.quantity)
                if quantity_to_buy <= 0:
                    logger.info(
                        f"{symbol} | BUY signal but target already reached "
                        f"(target={target_quantity:.8f}, current={current_position.quantity:.8f})"
                    )
                    return

            order = self.broker.place_market_order(symbol, "BUY", quantity_to_buy)
            if order.status in ("FILLED", "NEW"):
                exchange_qty = self.broker.get_asset_quantity(symbol)
                final_qty = exchange_qty if exchange_qty > 0 else quantity_to_buy
                self.portfolio.open(Position(
                    symbol=symbol,
                    quantity=final_qty,
                    entry_price=price,
                    stop_loss=self.risk.stop_loss_price(price, "LONG"),
                    take_profit=self.risk.take_profit_price(price, "LONG"),
                    side="LONG",
                ))
                self._record_position_opened(symbol)
            else:
                logger.warning(f"{symbol} | BUY signal not executed (order status={order.status})")

        elif signal == Signal.SELL and self.portfolio.has(symbol):
            pos = self.portfolio.get(symbol)
            if pos is None:
                logger.warning(f"{symbol} | SELL signal but position is missing")
                return

            current_price = self.broker.get_price(symbol)
            if current_price <= 0:
                logger.warning(f"{symbol} | SELL skipped due to invalid current price")
                return

            hold_age = self._position_age_seconds(symbol)
            if hold_age < self._min_hold_sec:
                logger.info(
                    f"{symbol} | SELL blocked by min hold time "
                    f"({hold_age:.0f}s < {self._min_hold_sec}s)"
                )
                return

            pnl_pct = (current_price - pos.entry_price) / pos.entry_price if pos.entry_price > 0 else 0.0
            if pnl_pct < self._min_signal_exit_pnl_pct:
                logger.info(
                    f"{symbol} | SELL blocked by min signal PnL "
                    f"({pnl_pct:.3%} < {self._min_signal_exit_pnl_pct:.3%})"
                )
                return

            order = self.broker.place_market_order(symbol, "SELL", pos.quantity)
            if order.status in ("FILLED", "NEW"):
                self.portfolio.close(symbol)
                self._record_position_closed(symbol)
            else:
                logger.warning(f"{symbol} | SELL signal not executed (order status={order.status})")
        elif signal == Signal.SELL:
            logger.info(f"{symbol} | SELL signal but no open position")
        else:
            logger.info(f"{symbol} | HOLD signal — no action")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        logger.info("=" * 60)
        logger.info("Day Trading Agent — starting up")
        logger.info(f"Mode        : {'TESTNET' if self.config.testnet else '*** LIVE TRADING ***'}")
        logger.info(f"Symbols     : {', '.join(self.config.symbols)}")
        logger.info(f"Timeframe   : {self.config.timeframe}")
        logger.info(f"Strategies  : {[s.name for s in self.strategies]}")
        logger.info(f"Consensus   : {self.config.min_signal_consensus}/{len(self.strategies)}")
        logger.info(f"Max pos.    : {self.config.risk.max_open_positions}")
        logger.info(f"Stop-loss   : {self.config.risk.stop_loss_pct:.1%}")
        logger.info(f"Take-profit : {self.config.risk.take_profit_pct:.1%}")
        logger.info("=" * 60)

        self._running = True
        try:
            while self._running:
                self._maybe_reset_daily()
                self._sync_account_positions()
                self._check_open_positions()

                for symbol in self.config.symbols:
                    try:
                        signal = self._consensus_signal(symbol)
                        logger.info(f"{symbol} | signal={signal.name}")
                        self._handle_signal(symbol, signal)
                    except Exception as exc:
                        logger.error(f"Unhandled error for {symbol}: {exc}", exc_info=True)

                balance = self.broker.get_balance(self._quote_asset)
                equity = self._portfolio_equity()
                logger.info(f"Balance: {balance:.2f} {self._quote_asset} | Equity: {equity:.2f} {self._quote_asset}")
                logger.info(self.portfolio.summary(self.broker.get_price))
                logger.info(f"Sleeping {self.config.check_interval}s ...\n")
                time.sleep(self.config.check_interval)

        except KeyboardInterrupt:
            logger.info("Stopped by user (Ctrl+C)")
        finally:
            self._running = False

    def stop(self) -> None:
        self._running = False
