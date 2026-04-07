from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from binance.client import Client
from dotenv import dotenv_values
from flask import Flask, redirect, render_template, request, url_for

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
STATE_PATH = BASE_DIR / ".dashboard_state.json"
BOT_PID_PATH = BASE_DIR / ".bot.pid"
BOT_LOG_PATH = BASE_DIR / "bot_stdout.log"

ALLOWED_ENV_KEYS = [
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "BINANCE_PRIVATE_KEY_PATH",
    "BINANCE_PRIVATE_KEY_PASS",
    "BINANCE_TESTNET",
    "BINANCE_CA_BUNDLE",
    "TRADING_SYMBOLS",
    "TIMEFRAME",
    "LOOKBACK_CANDLES",
    "MIN_SIGNAL_CONSENSUS",
    "CHECK_INTERVAL",
    "MAX_POSITION_PCT",
    "STOP_LOSS_PCT",
    "TAKE_PROFIT_PCT",
    "MAX_DAILY_LOSS_PCT",
    "MAX_OPEN_POSITIONS",
]
SENSITIVE_KEYS = {
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "BINANCE_PRIVATE_KEY_PASS",
}
QUOTE_SUFFIXES = ("USDT", "USDC", "BUSD", "FDUSD", "EUR", "BTC", "ETH")

app = Flask(__name__)
ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def _get_recent_bot_activity(limit: int = 10) -> list[dict[str, str]]:
    """Parse recent bot activity from bot output and trading logs."""
    activities: list[dict[str, str]] = []
    log_files = list(BASE_DIR.glob("trading_*.log"))
    if BOT_LOG_PATH.exists():
        log_files.append(BOT_LOG_PATH)
    log_files = sorted(log_files, key=lambda p: p.stat().st_mtime, reverse=True)

    for log_file in log_files:
        if len(activities) >= limit:
            break
        try:
            lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()
            for line in reversed(lines):
                if len(activities) >= limit:
                    break
                clean_line = ANSI_ESCAPE_RE.sub("", line)
                line_lower = clean_line.lower()
                parts = clean_line.split(" | ", 3)
                ts = parts[0] if len(parts) >= 1 else ""
                msg = parts[3] if len(parts) >= 4 else clean_line

                if "order executed:" in line_lower and " buy " in line_lower:
                    activities.append({"time": ts, "action": "BUY", "message": msg})
                elif "order executed:" in line_lower and " sell " in line_lower:
                    activities.append({"time": ts, "action": "SELL", "message": msg})
                elif " signal=hold" in line_lower or " no action" in line_lower:
                    activities.append({"time": ts, "action": "HOLD", "message": msg})
                elif "buy=" in line_lower and "sell=" in line_lower and "hold=" in line_lower:
                    activities.append({"time": ts, "action": "SIGNAL", "message": msg})
                elif "ai_score=" in line_lower:
                    activities.append({"time": ts, "action": "AI", "message": msg})
                elif "error" in line_lower:
                    activities.append({"time": ts, "action": "ERROR", "message": msg})
        except Exception:
            continue

    return activities[:limit]


def _read_bot_pid() -> int | None:
    if not BOT_PID_PATH.exists():
        return None
    try:
        return int(BOT_PID_PATH.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _bot_status() -> dict[str, Any]:
    pid = _read_bot_pid()
    if pid is None:
        return {"running": False, "pid": None}
    if not _is_pid_running(pid):
        try:
            BOT_PID_PATH.unlink(missing_ok=True)
        except Exception:
            pass
        return {"running": False, "pid": None}
    return {"running": True, "pid": pid}


def _start_bot_process() -> tuple[bool, str]:
    status = _bot_status()
    if status["running"]:
        return False, f"Bot laeuft bereits (PID {status['pid']})"

    with BOT_LOG_PATH.open("a", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            [sys.executable, "main.py"],
            cwd=str(BASE_DIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    BOT_PID_PATH.write_text(str(proc.pid), encoding="utf-8")
    return True, f"Bot gestartet (PID {proc.pid})"


def _stop_bot_process() -> tuple[bool, str]:
    status = _bot_status()
    if not status["running"]:
        return False, "Bot ist bereits gestoppt"

    pid = int(status["pid"])
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        return False, f"Stop fehlgeschlagen: {exc}"

    try:
        BOT_PID_PATH.unlink(missing_ok=True)
    except Exception:
        pass
    return True, f"Bot gestoppt (PID {pid})"


def _env_values() -> dict[str, str]:
    if not ENV_PATH.exists():
        return {}
    raw = dotenv_values(str(ENV_PATH))
    return {k: (v or "") for k, v in raw.items()}


def _bool_env(value: str, default: bool = False) -> bool:
    if not value:
        return default
    return value.strip().lower() == "true"


def _infer_quote_asset(symbols: str) -> str:
    first = symbols.split(",")[0].strip().upper() if symbols else ""
    for suffix in QUOTE_SUFFIXES:
        if first.endswith(suffix):
            return suffix
    return "USDT"


def _create_client(env: dict[str, str]) -> Client:
    request_params = {}
    ca_bundle = env.get("BINANCE_CA_BUNDLE", "").strip()
    if ca_bundle:
        candidate = Path(ca_bundle)
        if candidate.exists():
            request_params["verify"] = str(candidate)
        else:
            # Fallback for configs copied from Windows to Linux LXC.
            local_candidate = BASE_DIR / "certs" / candidate.name
            if local_candidate.exists():
                request_params["verify"] = str(local_candidate)

    kwargs: dict[str, Any] = {
        "api_key": env.get("BINANCE_API_KEY", "").strip(),
        "api_secret": (env.get("BINANCE_API_SECRET", "").strip() or None),
        "testnet": _bool_env(env.get("BINANCE_TESTNET", "true"), default=True),
        "requests_params": request_params or None,
        "ping": False,
    }

    private_key_path = env.get("BINANCE_PRIVATE_KEY_PATH", "").strip()
    private_key_pass = env.get("BINANCE_PRIVATE_KEY_PASS", "").strip()
    if private_key_path:
        kwargs["private_key"] = Path(private_key_path)
    if private_key_pass:
        kwargs["private_key_pass"] = private_key_pass

    client = Client(**kwargs)
    if _bool_env(env.get("BINANCE_TESTNET", "true"), default=True):
        client.API_URL = "https://testnet.binance.vision/api"
    return client


def _get_price_usdt(client: Client, asset: str, cache: dict[str, float | None]) -> float | None:
    asset = asset.upper()
    if asset == "USDT":
        return 1.0
    if asset == "USDC":
        if "USDCUSDT" not in cache:
            try:
                cache["USDCUSDT"] = float(client.get_symbol_ticker(symbol="USDCUSDT")["price"])
            except Exception:
                cache["USDCUSDT"] = 1.0
        return cache["USDCUSDT"]

    symbol = f"{asset}USDT"
    if symbol not in cache:
        try:
            cache[symbol] = float(client.get_symbol_ticker(symbol=symbol)["price"])
        except Exception:
            cache[symbol] = None
    return cache[symbol]


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _append_portfolio_history(state: dict[str, Any], total_usdt: float, max_points: int = 500) -> None:
    """Append a history point at most once per minute for portfolio charting."""
    now = datetime.now()
    history = state.get("history", [])

    if history:
        last_ts_raw = str(history[-1].get("t", ""))
        try:
            last_ts = datetime.fromisoformat(last_ts_raw)
            if (now - last_ts).total_seconds() < 55:
                return
        except ValueError:
            pass

    history.append({"t": now.isoformat(timespec="seconds"), "v": round(total_usdt, 6)})
    if len(history) > max_points:
        history = history[-max_points:]
    state["history"] = history


def _update_env_file(updates: dict[str, str]) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    for key, value in updates.items():
        replaced = False
        for idx, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[idx] = f"{key}={value}"
                replaced = True
                break
        if not replaced:
            lines.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


@app.route("/")
def dashboard():
    env = _env_values()
    quote_asset = _infer_quote_asset(env.get("TRADING_SYMBOLS", ""))
    bot = _bot_status()
    message = request.args.get("msg", "")

    snapshot: dict[str, Any] = {
        "connected": False,
        "error": "",
        "quote_asset": quote_asset,
        "quote_free": 0.0,
        "quote_locked": 0.0,
        "total_usdt": 0.0,
        "daily_pnl_abs": 0.0,
        "daily_pnl_pct": 0.0,
        "assets": [],
        "history_labels": [],
        "history_values": [],
    }

    try:
        client = _create_client(env)
        account = client.get_account()
        snapshot["connected"] = True

        price_cache: dict[str, float | None] = {}
        assets: list[dict[str, Any]] = []
        total_usdt = 0.0

        for b in account.get("balances", []):
            free = float(b["free"])
            locked = float(b["locked"])
            total_qty = free + locked
            if total_qty <= 0:
                continue

            asset = b["asset"].upper()
            px = _get_price_usdt(client, asset, price_cache)
            value_usdt = total_qty * px if px is not None else None
            if value_usdt is not None:
                total_usdt += value_usdt

            assets.append(
                {
                    "asset": asset,
                    "free": free,
                    "locked": locked,
                    "price_usdt": px,
                    "value_usdt": value_usdt,
                }
            )

            if asset == quote_asset:
                snapshot["quote_free"] = free
                snapshot["quote_locked"] = locked

        assets.sort(key=lambda x: (x["value_usdt"] is None, -(x["value_usdt"] or 0.0)))
        snapshot["assets"] = assets
        snapshot["total_usdt"] = total_usdt

        state = _load_state()
        today = str(date.today())
        if state.get("date") != today or state.get("start_total_usdt") is None:
            state = {
                "date": today,
                "start_total_usdt": total_usdt,
                "history": [{"t": datetime.now().isoformat(timespec="seconds"), "v": round(total_usdt, 6)}],
            }
        else:
            _append_portfolio_history(state, total_usdt)

        _save_state(state)

        history = state.get("history", [])
        snapshot["history_labels"] = [str(point.get("t", ""))[-8:] for point in history]
        snapshot["history_values"] = [float(point.get("v", 0.0)) for point in history]

        start = float(state.get("start_total_usdt", total_usdt))
        pnl_abs = total_usdt - start
        pnl_pct = (pnl_abs / start * 100.0) if start > 0 else 0.0
        snapshot["daily_pnl_abs"] = pnl_abs
        snapshot["daily_pnl_pct"] = pnl_pct

    except Exception as exc:
        snapshot["error"] = str(exc)

    activities = _get_recent_bot_activity(limit=10)
    return render_template("dashboard.html", snapshot=snapshot, env=env, bot=bot, message=message, activities=activities)


@app.post("/bot/start")
def bot_start():
    _ok, msg = _start_bot_process()
    return redirect(url_for("dashboard", msg=msg))


@app.post("/bot/stop")
def bot_stop():
    _ok, msg = _stop_bot_process()
    return redirect(url_for("dashboard", msg=msg))


@app.route("/settings", methods=["GET", "POST"])
def settings():
    env = _env_values()
    message = ""

    if request.method == "POST":
        updates: dict[str, str] = {}
        for key in ALLOWED_ENV_KEYS:
            submitted = request.form.get(key, "").strip()
            if key in SENSITIVE_KEYS and submitted == "":
                updates[key] = env.get(key, "")
            else:
                updates[key] = submitted
        _update_env_file(updates)
        return redirect(url_for("settings", saved="1"))

    if request.args.get("saved") == "1":
        message = ".env gespeichert"

    fields = []
    for key in ALLOWED_ENV_KEYS:
        fields.append(
            {
                "key": key,
                "value": "" if key in SENSITIVE_KEYS else env.get(key, ""),
                "is_sensitive": key in SENSITIVE_KEYS,
                "is_set": bool(env.get(key, "")),
            }
        )

    return render_template("settings.html", fields=fields, message=message)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
