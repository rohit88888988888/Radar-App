"""
test_order_flow_dashboard.py — live diagnostic view of delta_order_flow.py.
Confirms real trade data is flowing before this goes anywhere near main.py
or mission_control.html. Every number on this page is either real or an
explicit empty state — nothing here is simulated.

Run:
    pip install flask websocket-client --break-system-packages
    python3 test_order_flow_dashboard.py
Then open the Replit webview URL (or http://localhost:8081 locally).
"""
import json
import delta_order_flow
from flask import Flask, jsonify

app = Flask(__name__)

SYMBOLS = ["BTC"]  # bare asset — delta_order_flow resolves to BTCUSDT/BTCUSD
                    # based on delta_order_flow.REGION. Add more once confirmed working.


@app.route("/flow")
def flow():
    return jsonify({s: delta_order_flow.get_order_flow(s) for s in SYMBOLS})


@app.route("/tape")
def tape():
    return jsonify({s: delta_order_flow.get_recent_trades(s, limit=12) for s in SYMBOLS})


HOME_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Order Flow — Diagnostic</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {
    --void: #0A0E14; --panel: #10151D; --line: #1C232E;
    --text: #C9D1D9; --muted: #5B6573;
    --buy: #5FD98A; --sell: #F0666B; --amber: #E8A23D;
  }
  * { box-sizing: border-box; }
  body {
    background: var(--void); color: var(--text);
    font-family: 'Inter', sans-serif; margin: 0;
    padding: 20px 14px 50px; min-height: 100vh;
  }
  .masthead { display: flex; align-items: baseline; justify-content: space-between; }
  .masthead h1 {
    font-family: 'JetBrains Mono', monospace; font-size: 14px; font-weight: 700;
    letter-spacing: 0.1em; margin: 0;
  }
  .masthead .tag { font-family: 'JetBrains Mono', monospace; font-size: 10px; color: var(--muted); }
  .subhead { font-size: 12px; color: var(--muted); margin: 6px 0 20px; line-height: 1.5; max-width: 46ch; }

  .card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 16px; margin-bottom: 14px; }
  .card-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
  .symbol-row { display: flex; align-items: center; gap: 8px; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); flex-shrink: 0; }
  .dot.live { background: var(--amber); animation: pulse 1.6s infinite; }
  @keyframes pulse {
    0% { box-shadow: 0 0 0 0 rgba(232,162,61,0.55); }
    70% { box-shadow: 0 0 0 7px rgba(232,162,61,0); }
    100% { box-shadow: 0 0 0 0 rgba(232,162,61,0); }
  }
  .symbol-name { font-family: 'JetBrains Mono', monospace; font-weight: 700; font-size: 15px; }
  .clock { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--muted); }

  .gauge { position: relative; height: 30px; background: var(--void); border-radius: 6px; overflow: hidden; display: flex; margin-bottom: 6px; }
  .gauge-half { position: relative; width: 50%; height: 100%; }
  .gauge-half.left { display: flex; justify-content: flex-end; }
  .gauge-half.right { display: flex; justify-content: flex-start; }
  .gauge-fill { height: 100%; transition: width 0.5s ease; }
  .gauge-fill.sell { background: linear-gradient(90deg, transparent, var(--sell)); }
  .gauge-fill.buy { background: linear-gradient(90deg, var(--buy), transparent); }
  .gauge-center-line { position: absolute; left: 50%; top: 0; bottom: 0; width: 1px; background: var(--line); }
  .delta-label { text-align: center; font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--muted); margin-bottom: 16px; }
  .delta-label b { font-size: 13px; }

  .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
  .stat .k { font-size: 9px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 3px; }
  .stat .v { font-family: 'JetBrains Mono', monospace; font-size: 13px; font-weight: 500; }
  .stat .v.buy { color: var(--buy); } .stat .v.sell { color: var(--sell); }

  .tape-label { font-size: 9px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; margin: 16px 0 6px; border-top: 1px solid var(--line); padding-top: 12px; }
  .tape { font-family: 'JetBrains Mono', monospace; font-size: 11px; max-height: 240px; overflow: hidden; }
  .tape-row { display: flex; gap: 8px; padding: 3px 0; animation: slidein 0.3s ease; border-bottom: 1px solid rgba(255,255,255,0.03); }
  @keyframes slidein { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: translateY(0); } }
  .tape-row .t { color: var(--muted); width: 58px; flex-shrink: 0; }
  .tape-row .side { width: 30px; flex-shrink: 0; font-weight: 700; }
  .tape-row .side.buy { color: var(--buy); } .tape-row .side.sell { color: var(--sell); }
  .tape-row .sz { width: 64px; flex-shrink: 0; text-align: right; }
  .tape-row .px { color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  .empty { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--muted); padding: 18px 4px; text-align: center; line-height: 1.6; }
  .empty .big { color: var(--sell); display: block; font-size: 20px; margin-bottom: 6px; }

  @media (prefers-reduced-motion: reduce) {
    .dot.live { animation: none; }
    .tape-row { animation: none; }
    .gauge-fill { transition: none; }
  }
</style>
</head>
<body>
  <div class="masthead">
    <h1>ORDER FLOW</h1>
    <span class="tag">DELTA EXCHANGE · DIAGNOSTIC</span>
  </div>
  <p class="subhead">Real buy/sell volume read straight from Delta's own trade feed — not TradingView's footprint. This view exists to confirm the data is real before it goes anywhere near Mission Control.</p>
  <p class="subhead" style="margin-top:-14px;">Region: <b>__REGION__</b> &nbsp;·&nbsp; Resolved symbols: <b>__RESOLVED_SYMBOLS__</b></p>
  <div id="cards">loading…</div>

<script>
const SYMBOLS = __SYMBOLS_JSON__;

function fmtClock(d) { return d.toLocaleTimeString('en-GB', { hour12: false }); }
function fmtTradeTime(unixSeconds) { return fmtClock(new Date(unixSeconds * 1000)); }

function renderCard(sym, f, trades) {
  if (!f) {
    return `<div class="card">
      <div class="card-head"><div class="symbol-row"><span class="dot"></span><span class="symbol-name">${sym}</span></div></div>
      <div class="empty"><span class="big">○</span>No data yet.<br>WebSocket isn't connected, or the field names don't match — check the server console for the "first raw message" log line.</div>
    </div>`;
  }
  const total = f.buy_volume + f.sell_volume;
  const buyPct = total ? (f.buy_volume / total * 100) : 0;
  const sellPct = total ? (f.sell_volume / total * 100) : 0;
  const deltaSign = f.delta >= 0 ? '+' : '';
  const deltaColor = f.delta >= 0 ? 'var(--buy)' : 'var(--sell)';

  const tapeHtml = trades.length
    ? trades.map(t => `<div class="tape-row">
        <span class="t">${fmtTradeTime(t.time)}</span>
        <span class="side ${t.side}">${t.side.toUpperCase()}</span>
        <span class="sz">${Number(t.size).toFixed(4)}</span>
        <span class="px">@ ${Number(t.price).toLocaleString()}</span>
      </div>`).join('')
    : `<div class="empty">Connected, waiting for the first print…</div>`;

  return `<div class="card">
    <div class="card-head">
      <div class="symbol-row"><span class="dot ${f.ws_connected ? 'live' : ''}"></span><span class="symbol-name">${sym}</span></div>
      <span class="clock">${fmtClock(new Date())}</span>
    </div>
    <div class="gauge">
      <div class="gauge-half left"><div class="gauge-fill sell" style="width:${sellPct}%"></div></div>
      <div class="gauge-half right"><div class="gauge-fill buy" style="width:${buyPct}%"></div></div>
      <div class="gauge-center-line"></div>
    </div>
    <div class="delta-label">DELTA&nbsp; <b style="color:${deltaColor}">${deltaSign}${f.delta.toFixed(3)}</b> &nbsp;over ${f.window_seconds}s</div>
    <div class="stats">
      <div class="stat"><div class="k">Buy Vol</div><div class="v buy">${f.buy_volume.toFixed(3)}</div></div>
      <div class="stat"><div class="k">Sell Vol</div><div class="v sell">${f.sell_volume.toFixed(3)}</div></div>
      <div class="stat"><div class="k">Trades</div><div class="v">${f.trade_count}</div></div>
      <div class="stat"><div class="k">Buy Share</div><div class="v">${f.buy_share != null ? (f.buy_share*100).toFixed(0) + '%' : '—'}</div></div>
    </div>
    <div class="tape-label">Live Tape</div>
    <div class="tape">${tapeHtml}</div>
  </div>`;
}

async function tick() {
  const container = document.getElementById('cards');
  try {
    const [flowRes, tapeRes] = await Promise.all([fetch('/flow'), fetch('/tape')]);
    const flow = await flowRes.json();
    const tape = await tapeRes.json();
    container.innerHTML = SYMBOLS.map(sym => renderCard(sym, flow[sym], tape[sym] || [])).join('');
  } catch (e) {
    container.innerHTML = `<div class="card empty"><span class="big">⚠</span>Fetch failed — is the server still running?<br>${e}</div>`;
  }
}
tick();
setInterval(tick, 3000);
</script>
</body>
</html>
"""


@app.route("/")
def home():
    resolved = [delta_order_flow.resolve_symbol(s) for s in SYMBOLS]
    html = HOME_HTML.replace("__SYMBOLS_JSON__", json.dumps(SYMBOLS))
    html = html.replace("__REGION__", delta_order_flow.REGION)
    html = html.replace("__RESOLVED_SYMBOLS__", ", ".join(resolved))
    return html


if __name__ == "__main__":
    delta_order_flow.start(SYMBOLS)
    app.run(host="0.0.0.0", port=8081)
  
