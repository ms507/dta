import math
import time
from pathlib import Path

import pandas as pd
from binance.client import Client
from binance.exceptions import BinanceAPIException
from requests.exceptions import RequestException
from urllib3.exceptions import ReadTimeoutError

from .base import BaseBroker, Order
from utils.logger import get_logger

logger = get_logger("BinanceBroker")

# Binance Spot Testnet endpoint
_TESTNET_URL = "https://testnet.binance.vision/api"


class BinanceBroker(BaseBroker):
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = True,
        ca_bundle: str | None = None,
        private_key_path: str | None = None,
        private_key_pass: str | None = None,
        request_timeout: int = 20,
        max_retries: int = 3,
        retry_backoff_sec: float = 1.0,
    ) -> None:
        self.testnet = testnet
        self.request_timeout = max(1, int(request_timeout))
        self.max_retries = max(0, int(max_retries))
        self.retry_backoff_sec = max(0.0, float(retry_backoff_sec))
        request_params = {}
        if ca_bundle:
            request_params["verify"] = ca_bundle
        request_params["timeout"] = self.request_timeout

        client_kwargs = {
            "api_key": api_key,
            "api_secret": api_secret or None,
            "testnet": testnet,
            "requests_params": request_params or None,
            "ping": False,
        }
        if private_key_path:
            client_kwargs["private_key"] = Path(private_key_path)
        if private_key_pass:
            client_kwargs["private_key_pass"] = private_key_pass

        self.client = Client(
            **client_kwargs,
        )
        if testnet:
            self.client.API_URL = _TESTNET_URL

        # Ping can intermittently fail (e.g., proxy/gateway 502). Do not abort startup here.
        try:
            self._call_with_retries("ping", self.client.ping)
        except Exception as exc:
            logger.warning(f"Startup ping failed, continuing anyway: {exc}")

        mode = "TESTNET" if testnet else "LIVE"
        verify_mode = ca_bundle if ca_bundle else "system/certifi store"
        auth_mode = f"private_key={private_key_path}" if private_key_path else "api_secret"
        logger.info(
            f"Binance broker ready ({mode}) | auth={auth_mode} | TLS verify={verify_mode} | "
            f"timeout={self.request_timeout}s retries={self.max_retries}"
        )

    def _is_retryable_binance_error(self, exc: BinanceAPIException) -> bool:
        status_code = getattr(exc, "status_code", None)
        if status_code is None:
            return False
        if status_code in (418, 429):
            return True
        return 500 <= status_code < 600

    def _call_with_retries(self, operation: str, func, *args, **kwargs):
        attempts = self.max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                return func(*args, **kwargs)
            except BinanceAPIException as exc:
                retryable = self._is_retryable_binance_error(exc)
                if not retryable or attempt >= attempts:
                    raise
                delay = self.retry_backoff_sec * (2 ** (attempt - 1))
                logger.warning(
                    f"{operation} failed with Binance API error (status={getattr(exc, 'status_code', None)}), "
                    f"retrying in {delay:.1f}s [{attempt}/{attempts}]"
                )
                if delay > 0:
                    time.sleep(delay)
            except (ReadTimeoutError, RequestException, TimeoutError) as exc:
                if attempt >= attempts:
                    raise
                delay = self.retry_backoff_sec * (2 ** (attempt - 1))
                logger.warning(
                    f"{operation} timed out/network error: {exc}. Retrying in {delay:.1f}s "
                    f"[{attempt}/{attempts}]"
                )
                if delay > 0:
                    time.sleep(delay)

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def _get_symbol_info(self, symbol: str) -> dict | None:
        try:
            return self._call_with_retries("get_symbol_info", self.client.get_symbol_info, symbol)
        except (BinanceAPIException, ReadTimeoutError, RequestException, TimeoutError) as exc:
            logger.error(f"get_symbol_info({symbol}) failed: {exc}")
            return None

    def get_asset_quantity(self, symbol: str) -> float:
        info = self._get_symbol_info(symbol)
        if not info:
            return 0.0

        asset = info.get("baseAsset")
        if not asset:
            logger.error(f"Missing baseAsset in symbol info for {symbol}")
            return 0.0

        try:
            balance = self._call_with_retries("get_asset_balance", self.client.get_asset_balance, asset=asset)
            if not balance:
                return 0.0
            free = float(balance.get("free", 0.0))
            locked = float(balance.get("locked", 0.0))
            return free + locked
        except (BinanceAPIException, ReadTimeoutError, RequestException, TimeoutError) as exc:
            logger.error(f"get_asset_quantity({symbol}) failed: {exc}")
            return 0.0

    def _get_quote_asset(self, symbol: str) -> str:
        info = self._get_symbol_info(symbol)
        if not info:
            return "USDT"
        return str(info.get("quoteAsset", "USDT")).upper()

    def get_average_entry_price(self, symbol: str) -> float | None:
        try:
            trades = self._call_with_retries(
                "get_my_trades", self.client.get_my_trades, symbol=symbol, limit=1000
            )
        except (BinanceAPIException, ReadTimeoutError, RequestException, TimeoutError) as exc:
            logger.error(f"get_average_entry_price({symbol}) failed: {exc}")
            return None

        if not trades:
            return None

        net_quantity = 0.0
        net_cost = 0.0

        for trade in trades:
            quantity = float(trade["qty"])
            price = float(trade["price"])

            if trade["isBuyer"]:
                net_cost += quantity * price
                net_quantity += quantity
                continue

            if net_quantity <= 0:
                continue

            matched_quantity = min(quantity, net_quantity)
            average_cost = net_cost / net_quantity
            net_cost -= matched_quantity * average_cost
            net_quantity -= matched_quantity

        if net_quantity <= 0:
            return None

        return net_cost / net_quantity

    def get_balance(self, asset: str = "USDT") -> float:
        try:
            balance = self._call_with_retries("get_asset_balance", self.client.get_asset_balance, asset=asset)
            return float(balance["free"])
        except (BinanceAPIException, ReadTimeoutError, RequestException, TimeoutError) as exc:
            logger.error(f"get_balance failed: {exc}")
            return 0.0

    def get_price(self, symbol: str) -> float:
        try:
            ticker = self._call_with_retries("get_symbol_ticker", self.client.get_symbol_ticker, symbol=symbol)
            return float(ticker["price"])
        except (BinanceAPIException, ReadTimeoutError, RequestException, TimeoutError) as exc:
            logger.error(f"get_price({symbol}) failed: {exc}")
            return 0.0

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def get_candles(self, symbol: str, interval: str, limit: int = 100) -> pd.DataFrame:
        try:
            klines = self._call_with_retries(
                "get_klines", self.client.get_klines, symbol=symbol, interval=interval, limit=limit
            )
            df = pd.DataFrame(klines, columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades",
                "taker_buy_base", "taker_buy_quote", "ignore",
            ])
            for col in ("open", "high", "low", "close", "volume"):
                df[col] = pd.to_numeric(df[col])
            df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
            df.set_index("open_time", inplace=True)
            return df[["open", "high", "low", "close", "volume"]]
        except (BinanceAPIException, ReadTimeoutError, RequestException, TimeoutError) as exc:
            logger.error(f"get_candles({symbol}) failed: {exc}")
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def get_step_size(self, symbol: str) -> float:
        """Return the LOT_SIZE step size for a symbol."""
        try:
            info = self._get_symbol_info(symbol)
            if not info:
                return 0.001
            for f in info["filters"]:
                if f["filterType"] == "LOT_SIZE":
                    return float(f["stepSize"])
        except BinanceAPIException as exc:
            logger.error(f"get_step_size({symbol}) failed: {exc}")
        return 0.001

    def get_min_qty(self, symbol: str) -> float:
        """Return the LOT_SIZE minQty for a symbol."""
        try:
            info = self._get_symbol_info(symbol)
            if not info:
                return 0.0
            for f in info["filters"]:
                if f["filterType"] == "LOT_SIZE":
                    return float(f["minQty"])
        except BinanceAPIException as exc:
            logger.error(f"get_min_qty({symbol}) failed: {exc}")
        return 0.0

    def get_min_notional(self, symbol: str) -> float:
        """Return the minimum quote notional from NOTIONAL/MIN_NOTIONAL filter."""
        try:
            info = self._get_symbol_info(symbol)
            if not info:
                return 0.0
            for f in info["filters"]:
                filter_type = f.get("filterType")
                if filter_type == "NOTIONAL":
                    return float(f.get("minNotional", 0.0))
                if filter_type == "MIN_NOTIONAL":
                    return float(f.get("minNotional", 0.0))
        except BinanceAPIException as exc:
            logger.error(f"get_min_notional({symbol}) failed: {exc}")
        return 0.0

    def _round_quantity(self, quantity: float, step_size: float) -> float:
        """Floor quantity to the allowed precision."""
        if step_size <= 0:
            return quantity
        precision = max(0, round(-math.log10(step_size)))
        floored = math.floor(quantity / step_size) * step_size
        return round(floored, precision)

    def _ceil_quantity(self, quantity: float, step_size: float) -> float:
        """Ceil quantity to the allowed precision."""
        if step_size <= 0:
            return quantity
        precision = max(0, round(-math.log10(step_size)))
        ceiled = math.ceil(quantity / step_size) * step_size
        return round(ceiled, precision)

    def _format_quantity(self, quantity: float, step_size: float) -> str:
        """Format quantity as fixed-point decimal to satisfy Binance API regex."""
        if step_size <= 0:
            return f"{quantity:.8f}".rstrip("0").rstrip(".")
        precision = max(0, round(-math.log10(step_size)))
        return f"{quantity:.{precision}f}"

    def place_market_order(self, symbol: str, side: str, quantity: float) -> Order:
        step_size = self.get_step_size(symbol)
        min_qty = self.get_min_qty(symbol)
        min_notional = self.get_min_notional(symbol)
        quantity = self._round_quantity(quantity, step_size)

        if quantity <= 0 or (min_qty > 0 and quantity < min_qty):
            reason = (
                f"quantity {quantity:.8f} below minQty {min_qty:.8f}" if min_qty > 0
                else f"quantity {quantity:.8f} is not tradable"
            )
            logger.warning(f"Quantity too small for {symbol}: {quantity} — order skipped")
            return Order(symbol=symbol, side=side, quantity=quantity, status="REJECTED", reject_reason=reason)

        price = self.get_price(symbol)
        notional = quantity * price if price > 0 else 0.0
        if min_notional > 0 and notional < min_notional:
            # Add a safety margin because Binance may validate market orders with moving/average price.
            safety_notional = min_notional * 1.05
            required_qty = self._ceil_quantity(safety_notional / price if price > 0 else quantity, step_size)

            if side.upper() == "BUY" and price > 0:
                quote_asset = self._get_quote_asset(symbol)
                quote_balance = self.get_balance(quote_asset)
                required_notional = required_qty * price

                if required_notional <= quote_balance:
                    logger.info(
                        f"Adjusted BUY quantity for {symbol} to meet minNotional: "
                        f"{quantity:.8f} -> {required_qty:.8f}"
                    )
                    quantity = required_qty
                    notional = required_notional
                else:
                    reason = (
                        f"insufficient {quote_asset} balance for minNotional "
                        f"(need {required_notional:.6f}, have {quote_balance:.6f})"
                    )
                    logger.warning(
                        f"Notional too small for {symbol}: qty={quantity} value={notional:.6f} < "
                        f"minNotional={min_notional:.6f}. Required qty≈{required_qty:.8f}, "
                        f"but only {quote_balance:.6f} {quote_asset} available."
                    )
                    return Order(
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                        status="REJECTED",
                        reject_reason=reason,
                    )
            else:
                # For SELL orders: allow selling even if undersized by raising quantity to minNotional
                if side.upper() == "SELL":
                    available_qty = self.get_asset_quantity(symbol)
                    if required_qty <= available_qty:
                        logger.info(
                            f"Adjusted SELL quantity for {symbol} to meet minNotional: "
                            f"{quantity:.8f} -> {required_qty:.8f} (available: {available_qty:.8f})"
                        )
                        quantity = required_qty
                        notional = required_qty * price
                    else:
                        reason = (
                            f"insufficient asset quantity for minNotional "
                            f"(need {required_qty:.8f}, have {available_qty:.8f})"
                        )
                        logger.warning(
                            f"Cannot adjust SELL for {symbol}: required={required_qty:.8f} > available={available_qty:.8f}. "
                            f"Notional {notional:.6f} < minNotional {min_notional:.6f} — order rejected."
                        )
                        return Order(
                            symbol=symbol,
                            side=side,
                            quantity=quantity,
                            status="REJECTED",
                            reject_reason=reason,
                        )
                else:
                    reason = (
                        f"notional {notional:.6f} below minNotional {min_notional:.6f}"
                    )
                    logger.warning(
                        f"Notional too small for {symbol}: qty={quantity} value={notional:.6f} < "
                        f"minNotional={min_notional:.6f}. Required qty≈{required_qty:.8f}"
                    )
                    return Order(
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                        status="REJECTED",
                        reject_reason=reason,
                    )

        quantity_str = self._format_quantity(quantity, step_size)

        try:
            result = self._call_with_retries(
                "order_market", self.client.order_market, symbol=symbol, side=side, quantity=quantity_str
            )
            logger.info(
                f"Order executed: {side} {quantity} {symbol} | "
                f"order_id={result['orderId']} status={result['status']}"
            )
            return Order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_id=str(result["orderId"]),
                status=result["status"],
            )
        except (BinanceAPIException, ReadTimeoutError, RequestException, TimeoutError) as exc:
            logger.error(f"place_market_order({symbol}, {side}, {quantity}) failed: {exc}")
            return Order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                status="FAILED",
                reject_reason=str(exc),
            )
