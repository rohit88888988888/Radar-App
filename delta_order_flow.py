"""
delta_order_flow.py — Real-time order-flow (buy/sell volume + delta) tracker
built on Delta Exchange's public "trades" WebSocket channel.

WHY THIS EXISTS: TradingView's native request.footprint() needs Premium or
Ultimate. This bypasses that entirely by reading real, exchange-tagged
buy/sell trades directly from Delta — genuine order flow, not an approximation.

⚠️ NOT VERIFIED AGAINST A LIVE CONNECTION. I (Claude) have no network access
in my sandbox, so this code has never actually talked to Delta's servers.
Confirmed against Delta's official docs (docs.delta.exchange, docs-global.delta.exchange,
and Delta's own python-rest-client repo): the channel name "trades", the
subscribe message shape, and — importantly — that Delta runs TWO separate
production environments with different hosts AND different symbol naming:

    Region   REST base                    WS base                          BTC perp symbol
    Global   api.delta.exchange           socket.delta.exchange             BTCUSDT
    India    api.india.delta.exchange     socket.india.delta.exchange       BTCUSD

That symbol difference (BTCUSDT vs BTCUSD) was the actual bug the first
version of this file had — it hardcoded the India-style symbol while
guessing the Global-style URL, a combination that can never work together.
This version fixes that by making REGION a single top-level setting and
resolving symbols from it, plus a watchdog that tells you directly if a
mismatch happens again instead of just returning null forever.

STILL NOT independently confirmed: the exact field name for trade side
inside the live WS push message (inferred from Delta's REST trades
response, which does use "side"). Run the __main__ test block at the
bottom FIRST and read the log output before wiring this into main.py —
if the field name is off, the raw message log line will show you the
real shape immediately, and _extract_side()'s fallbacks are there to
absorb small naming differences without you having to touch calling code.

Install dependency first:
    pip install websocket-client --break-system-packages
"""

import json
import threading
import time
import logging
from collections import deque, defaultdict

try:
    import websocket  # package name: websocket-client
except ImportError:
    websocket = None

log = logging.getLogger("apex_webhook")  # same logger name as main.py, so
                                          # logs blend in when imported together

# ── REGION SETTING — the one thing you need to check for your account ──
# "global" -> www.delta.exchange account (BTC perp symbol: BTCUSDT)
# "india"  -> india.delta.exchange account (BTC perp symbol: BTCUSD)
# Confirmed against Delta's docs and official python-rest-client repo.
REGION = "india"  # change to "india" if your account is on india.delta.exchange

WS_URLS = {
    "global": "wss://socket.delta.exchange",
    "india": "wss://socket.india.delta.exchange",
}

# Suffix used for perpetual-future symbols in each region, e.g. BTC -> BTCUSDT.
PERP_SUFFIX = {
    "global": "USDT",
    "india": "USD",
}

if REGION not in WS_URLS:
    raise ValueError(f"REGION must be 'global' or 'india', got {REGION!r}")

DELTA_WS_URL = WS_URLS[REGION]

RECONNECT_DELAY_SECONDS = 5
PING_INTERVAL_SECONDS = 25
NO_DATA_WARNING_SECONDS = 15  # how long to wait after connecting before nudging

_lock = threading.Lock()
_trade_buffer = defaultdict(deque)  # symbol -> deque of (timestamp, side, size)
_ws_connected = False
_raw_message_logged = False  # log the very first raw message once, for verification
_subscribed_symbols = []


def resolve_symbol(asset_or_symbol):
    """Accepts either a bare asset ('BTC') or an already-fully-qualified
    exchange symbol ('BTCUSDT' / 'BTCUSD'). Bare assets get the
    region-correct perpetual suffix appended automatically, so callers
    don't need to know which region uses which suffix. Already-qualified
    symbols pass through unchanged."""
    s = asset_or_symbol.upper()
    if s.endswith("USD") or s.endswith("USDT"):
        return s
    return f"{s}{PERP_SUFFIX[REGION]}"


def _extract_side(trade):
    """Trade side field name isn't 100% confirmed for the WS push shape —
    try the documented REST field first, then a couple of plausible fallbacks."""
    return trade.get("side") or trade.get("buyer_role") or trade.get("taker_side")


def _on_message(ws, message):
    global _ws_connected, _raw_message_logged
    try:
        data = json.loads(message)

        if not _raw_message_logged:
            log.info(f"🔍 order_flow: first raw WS message (for verification): {message[:500]}")
            _raw_message_logged = True

        msg_type = data.get("type")
        if msg_type not in ("trades", "all_trades"):  # accept either naming
            return

        # Some exchanges send one trade per message, some send a batch list —
        # handle both shapes defensively.
        trades = data.get("trades") if isinstance(data.get("trades"), list) else [data]

        with _lock:
            for t in trades:
                symbol = t.get("symbol") or data.get("symbol")
                side = _extract_side(t)
                try:
                    size = float(t.get("size", 0))
                except (TypeError, ValueError):
                    size = 0
                try:
                    price = float(t.get("price", 0))
                except (TypeError, ValueError):
                    price = 0
                if symbol and side and size:
                    _trade_buffer[symbol].append((time.time(), side, size, price))

    except Exception as e:
        log.error(f"❌ order_flow: failed to parse message: {e} | raw={str(message)[:200]}")


def _on_open(ws, symbols):
    global _ws_connected
    _ws_connected = True
    log.info(f"✅ order_flow: WebSocket connected (region={REGION}) — "
             f"subscribing to trades for {symbols}")
    payload = {"type": "subscribe", "payload": {"channels": [{"name": "trades", "symbols": symbols}]}}
    ws.send(json.dumps(payload))
    threading.Timer(NO_DATA_WARNING_SECONDS, _warn_if_no_data, args=(symbols,)).start()


def _warn_if_no_data(symbols):
    if _ws_connected and not _raw_message_logged:
        log.warning(
            f"⚠️ order_flow: connected {NO_DATA_WARNING_SECONDS}s ago but "
            f"zero messages received for {symbols} on REGION={REGION!r}. "
            f"Most likely cause: symbol doesn't exist in this region (global "
            f"uses e.g. BTCUSDT, india uses BTCUSD) — double check the "
            f"symbol against your account's platform, or flip REGION at "
            f"the top of this file if you're on the other one."
        )


def _on_error(ws, error):
    log.error(f"❌ order_flow: WebSocket error: {error}")


def _on_close(ws, code, msg):
    global _ws_connected
    _ws_connected = False
    log.warning(f"⚠️ order_flow: WebSocket closed (code={code}, msg={msg}) — will reconnect")


def _run_forever(symbols):
    if websocket is None:
        log.error("❌ order_flow: 'websocket-client' not installed — run: "
                   "pip install websocket-client --break-system-packages")
        return
    while True:
        try:
            ws = websocket.WebSocketApp(
                DELTA_WS_URL,
                on_open=lambda w: _on_open(w, symbols),
                on_message=_on_message,
                on_error=_on_error,
                on_close=_on_close,
            )
            ws.run_forever(ping_interval=PING_INTERVAL_SECONDS, ping_timeout=10)
        except Exception as e:
            log.error(f"❌ order_flow: connection loop crashed: {e}")
        log.warning(f"⚠️ order_flow: reconnecting in {RECONNECT_DELAY_SECONDS}s...")
        time.sleep(RECONNECT_DELAY_SECONDS)


def start(symbols):
    """Call once at startup with either bare assets (e.g. ['BTC', 'ETH']) or
    fully-qualified Delta symbols (e.g. ['BTCUSDT']) — bare assets are
    resolved to the correct symbol for REGION automatically. Runs in a
    daemon background thread — safe to call alongside the Flask app."""
    global _subscribed_symbols
    resolved = [resolve_symbol(s) for s in symbols]
    if resolved != symbols:
        log.info(f"ℹ️ order_flow: resolved {symbols} -> {resolved} for REGION={REGION!r}")
    _subscribed_symbols = resolved
    t = threading.Thread(target=_run_forever, args=(resolved,), daemon=True)
    t.start()
    return t


def get_order_flow(symbol, window_seconds=60):
    """Real buy/sell volume + delta for `symbol` over the trailing window_seconds.
    `symbol` can be a bare asset ('BTC') or full symbol ('BTCUSDT') — resolved
    the same way as in start(). Returns None if nothing has arrived yet (WS
    not connected, wrong symbol/region, or genuinely no trades in that window)."""
    symbol = resolve_symbol(symbol)
    cutoff = time.time() - window_seconds
    with _lock:
        buf = _trade_buffer.get(symbol)
        if not buf:
            return None
        while buf and buf[0][0] < cutoff:
            buf.popleft()
        if not buf:
            return None
        buy_vol = sum(size for ts, side, size, price in buf if side == "buy")
        sell_vol = sum(size for ts, side, size, price in buf if side == "sell")
        trade_count = len(buf)
    total = buy_vol + sell_vol
    return {
        "symbol": symbol,
        "window_seconds": window_seconds,
        "buy_volume": buy_vol,
        "sell_volume": sell_vol,
        "delta": buy_vol - sell_vol,
        "buy_share": round(buy_vol / total, 3) if total else None,
        "trade_count": trade_count,
        "ws_connected": _ws_connected,
    }


def get_recent_trades(symbol, limit=15):
    """Most recent individual trades for `symbol`, newest first — feeds a
    live tape/ticker display. `symbol` can be a bare asset or full symbol,
    same resolution as get_order_flow(). Each item: {time, side, size, price}."""
    symbol = resolve_symbol(symbol)
    with _lock:
        buf = _trade_buffer.get(symbol)
        if not buf:
            return []
        recent = list(buf)[-limit:]
    recent.reverse()
    return [{"time": ts, "side": side, "size": size, "price": price} for ts, side, size, price in recent]


if __name__ == "__main__":
    # STANDALONE TEST — run this file alone before touching main.py:
    #     python3 delta_order_flow.py
    # Expected: a "✅ ... connected" line, then a "🔍 ... first raw message"
    # line (READ THIS — it tells you the true message shape), then growing
    # buy/sell numbers every 5s.
    # If you only see reconnect warnings -> URL/region is wrong, flip REGION.
    # If connected but a "⚠️ ... zero messages" warning shows up after 15s
    # -> symbol doesn't exist in this region, check REGION matches your account.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    test_assets = ["BTC"]  # resolved to BTCUSDT (global) or BTCUSD (india) automatically
    print(f"REGION={REGION!r} -> WS URL={DELTA_WS_URL!r}")
    print(f"Connecting and listening for trades on {test_assets} for 30 seconds...\n")
    start(test_assets)
    for _ in range(6):
        time.sleep(5)
        print(get_order_flow(test_assets[0]))
              
