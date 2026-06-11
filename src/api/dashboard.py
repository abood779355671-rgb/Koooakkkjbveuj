from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from loguru import logger

from .routes import router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Telegram Gift Monitor",
        description="Real-time monitoring and auto-buying system for Telegram Collectible Gifts",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router, prefix="/api/v1")

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        return _get_dashboard_html()

    @app.on_event("startup")
    async def on_startup():
        logger.info("Dashboard API started")

    return app


def _get_dashboard_html() -> str:
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Telegram Gift Monitor</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0d1117; color: #c9d1d9; }
        .header { background: #161b22; border-bottom: 1px solid #30363d; padding: 16px 24px; display: flex; align-items: center; gap: 12px; }
        .header h1 { font-size: 20px; font-weight: 600; color: #f0f6fc; }
        .status-dot { width: 10px; height: 10px; border-radius: 50%; background: #238636; animation: pulse 2s infinite; }
        @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
        .container { max-width: 1400px; margin: 0 auto; padding: 24px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; }
        .card h3 { font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; color: #8b949e; margin-bottom: 8px; }
        .card .value { font-size: 28px; font-weight: 700; color: #f0f6fc; }
        .card .sub { font-size: 12px; color: #8b949e; margin-top: 4px; }
        .positive { color: #3fb950; }
        .negative { color: #f85149; }
        .chart-card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; margin-bottom: 24px; }
        .chart-card h2 { font-size: 16px; font-weight: 600; color: #f0f6fc; margin-bottom: 16px; }
        .table-card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; overflow: hidden; margin-bottom: 24px; }
        .table-card h2 { font-size: 16px; font-weight: 600; color: #f0f6fc; padding: 16px 20px; border-bottom: 1px solid #30363d; }
        table { width: 100%; border-collapse: collapse; }
        th { background: #0d1117; padding: 10px 16px; text-align: left; font-size: 12px; text-transform: uppercase; color: #8b949e; }
        td { padding: 12px 16px; border-top: 1px solid #21262d; font-size: 14px; }
        tr:hover td { background: #1c2128; }
        .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }
        .badge-success { background: #1a4031; color: #3fb950; }
        .badge-failed { background: #3d1e1e; color: #f85149; }
        .badge-pending { background: #2d2a1a; color: #d29922; }
        .tabs { display: flex; gap: 4px; margin-bottom: 24px; }
        .tab { padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 14px; border: none; background: transparent; color: #8b949e; }
        .tab.active { background: #238636; color: white; }
        .tab:hover:not(.active) { background: #21262d; color: #f0f6fc; }
        #loading { position: fixed; top: 50%; left: 50%; transform: translate(-50%,-50%); color: #8b949e; }
        .refresh-btn { margin-left: auto; padding: 6px 14px; background: #238636; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; }
        .refresh-btn:hover { background: #2ea043; }
    </style>
</head>
<body>
<div class="header">
    <div class="status-dot" id="statusDot"></div>
    <h1>🎁 Telegram Gift Monitor</h1>
    <button class="refresh-btn" onclick="loadAll()">↻ Refresh</button>
</div>
<div class="container">
    <div class="tabs">
        <button class="tab active" onclick="showTab('overview')">Overview</button>
        <button class="tab" onclick="showTab('purchases')">Purchases</button>
        <button class="tab" onclick="showTab('opportunities')">Opportunities</button>
        <button class="tab" onclick="showTab('backtest')">Backtest</button>
    </div>

    <div id="tab-overview">
        <div class="grid" id="statsGrid"></div>
        <div class="chart-card">
            <h2>📈 Daily P&L</h2>
            <canvas id="pnlChart" height="80"></canvas>
        </div>
        <div class="chart-card">
            <h2>👥 Account Performance</h2>
            <canvas id="accountChart" height="60"></canvas>
        </div>
    </div>

    <div id="tab-purchases" style="display:none">
        <div class="table-card">
            <h2>🛒 Recent Purchases</h2>
            <table>
                <thead>
                    <tr><th>Gift</th><th>Account</th><th>Price (TON)</th><th>Discount</th><th>Profit</th><th>Status</th><th>Date</th></tr>
                </thead>
                <tbody id="purchasesTable"></tbody>
            </table>
        </div>
    </div>

    <div id="tab-opportunities" style="display:none">
        <div class="table-card">
            <h2>💡 Top Opportunities</h2>
            <table>
                <thead>
                    <tr><th>Gift</th><th>Collection</th><th>Price</th><th>Floor</th><th>Discount</th><th>Rarity</th><th>Action</th></tr>
                </thead>
                <tbody id="oppsTable"></tbody>
            </table>
        </div>
    </div>

    <div id="tab-backtest" style="display:none">
        <div class="card" style="margin-bottom:16px">
            <h3>Run Backtest</h3>
            <div style="display:flex; gap:12px; margin-top:12px; align-items:center">
                <select id="strategySelect" style="background:#0d1117;color:#c9d1d9;border:1px solid #30363d;padding:6px 12px;border-radius:6px">
                    <option value="underpriced">Underpriced</option>
                </select>
                <button onclick="runBacktest()" style="padding:6px 16px;background:#238636;color:white;border:none;border-radius:6px;cursor:pointer">Run</button>
            </div>
        </div>
        <div id="backtestResults"></div>
    </div>
</div>

<script>
const API = '/api/v1';

async function fetchJSON(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(r.statusText);
    return r.json();
}

function fmt(n, d=4) { return n != null ? n.toFixed(d) : 'N/A'; }
function fmtDate(s) { return s ? new Date(s).toLocaleString() : 'N/A'; }
function profit(v) { return v > 0 ? `<span class="positive">+${fmt(v)}</span>` : `<span class="negative">${fmt(v)}</span>`; }
function badge(s) {
    const cls = s === 'success' ? 'badge-success' : s === 'failed' ? 'badge-failed' : 'badge-pending';
    return `<span class="badge ${cls}">${s}</span>`;
}

let pnlChart, accountChart;

async function loadStats() {
    const [pnl, daily, accounts, status] = await Promise.all([
        fetchJSON(`${API}/stats/pnl?days=30`),
        fetchJSON(`${API}/stats/daily?days=30`),
        fetchJSON(`${API}/stats/accounts`),
        fetchJSON(`${API}/system/status`),
    ]);

    document.getElementById('statusDot').style.background = status.status === 'running' ? '#238636' : '#d29922';

    const grid = document.getElementById('statsGrid');
    const profitClass = pnl.total_profit_ton >= 0 ? 'positive' : 'negative';
    grid.innerHTML = `
        <div class="card"><h3>Total Profit</h3><div class="value ${profitClass}">${fmt(pnl.total_profit_ton)} TON</div><div class="sub">${fmt(pnl.total_profit_percent, 2)}% ROI (30d)</div></div>
        <div class="card"><h3>Total Purchases</h3><div class="value">${pnl.total_purchases}</div><div class="sub">Last 30 days</div></div>
        <div class="card"><h3>Win Rate</h3><div class="value positive">${fmt(pnl.win_rate_percent, 1)}%</div><div class="sub">${pnl.win_count}W / ${pnl.loss_count}L</div></div>
        <div class="card"><h3>Total Spent</h3><div class="value">${fmt(pnl.total_spent_ton)} TON</div><div class="sub">Avg discount: ${fmt(pnl.avg_discount_percent, 1)}%</div></div>
        <div class="card"><h3>Best Trade</h3><div class="value positive">+${fmt(pnl.best_trade_ton)} TON</div><div class="sub">Worst: ${fmt(pnl.worst_trade_ton)} TON</div></div>
        <div class="card"><h3>Trading Mode</h3><div class="value" style="font-size:16px">${status.trading_enabled ? (status.auto_confirm ? '🟢 AUTO' : '👁️ DRY RUN') : '⛔ DISABLED'}</div><div class="sub">Threshold: ${status.threshold_percent}%</div></div>
    `;

    if (pnlChart) pnlChart.destroy();
    const ctx = document.getElementById('pnlChart').getContext('2d');
    pnlChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: daily.data.map(d => d.date),
            datasets: [
                { label: 'Profit (TON)', data: daily.data.map(d => d.profit), backgroundColor: daily.data.map(d => d.profit >= 0 ? '#2ea043' : '#da3633'), },
                { label: 'Spent (TON)', data: daily.data.map(d => -d.spent), backgroundColor: 'rgba(99,179,237,0.3)', type: 'line', borderColor: '#63b3ed', fill: false, tension: 0.3 },
            ]
        },
        options: { responsive: true, plugins: { legend: { labels: { color: '#c9d1d9' } } }, scales: { x: { ticks: { color: '#8b949e' }, grid: { color: '#21262d' } }, y: { ticks: { color: '#8b949e' }, grid: { color: '#21262d' } } } }
    });

    if (accountChart) accountChart.destroy();
    const ctx2 = document.getElementById('accountChart').getContext('2d');
    const accData = accounts.accounts;
    accountChart = new Chart(ctx2, {
        type: 'bar',
        data: {
            labels: accData.map(a => a.account),
            datasets: [
                { label: 'Profit (TON)', data: accData.map(a => a.profit_ton), backgroundColor: '#2ea043' },
                { label: 'Spent (TON)', data: accData.map(a => a.spent_ton), backgroundColor: 'rgba(99,179,237,0.4)' },
            ]
        },
        options: { responsive: true, plugins: { legend: { labels: { color: '#c9d1d9' } } }, scales: { x: { ticks: { color: '#8b949e' }, grid: { color: '#21262d' } }, y: { ticks: { color: '#8b949e' }, grid: { color: '#21262d' } } } }
    });
}

async function loadPurchases() {
    const data = await fetchJSON(`${API}/purchases?limit=50`);
    const tbody = document.getElementById('purchasesTable');
    tbody.innerHTML = data.purchases.map(p => `
        <tr>
            <td><code style="font-size:11px">${p.gift_id.substring(0,12)}…</code></td>
            <td>${p.account_name}</td>
            <td>${fmt(p.purchase_price_ton)}</td>
            <td><span class="${p.discount_percent > 0 ? 'positive' : ''}">${fmt(p.discount_percent, 1)}%</span></td>
            <td>${p.profit_ton != null ? profit(p.profit_ton) : '—'}</td>
            <td>${badge(p.status)}</td>
            <td style="color:#8b949e;font-size:12px">${fmtDate(p.purchased_at)}</td>
        </tr>
    `).join('');
}

async function loadOpportunities() {
    const data = await fetchJSON(`${API}/stats/opportunities?limit=30`);
    const tbody = document.getElementById('oppsTable');
    tbody.innerHTML = data.opportunities.map(o => `
        <tr>
            <td><code style="font-size:11px">${o.gift_id.substring(0,12)}…</code></td>
            <td><code style="font-size:11px">${o.collection_id.substring(0,12)}…</code></td>
            <td>${fmt(o.price)}</td>
            <td>${o.floor ? fmt(o.floor) : '—'}</td>
            <td><span class="positive">${fmt(o.discount, 1)}%</span></td>
            <td>${o.rarity ? fmt(o.rarity, 3) : '—'}</td>
            <td>${badge(o.action)}</td>
        </tr>
    `).join('');
}

async function runBacktest() {
    const strategy = document.getElementById('strategySelect').value;
    const container = document.getElementById('backtestResults');
    container.innerHTML = '<div class="card"><p style="color:#8b949e">Running backtest...</p></div>';

    const r = await fetchJSON(`${API}/backtest/run?strategy=${strategy}`);
    const profitClass = r.total_profit_ton >= 0 ? 'positive' : 'negative';
    container.innerHTML = `
        <div class="grid">
            <div class="card"><h3>Final Capital</h3><div class="value">${fmt(r.final_capital_ton)} TON</div><div class="sub">Started: ${fmt(r.initial_capital_ton)} TON</div></div>
            <div class="card"><h3>Total Profit</h3><div class="value ${profitClass}">${fmt(r.total_profit_ton)} TON</div><div class="sub">${r.total_profit_percent > 0 ? '+' : ''}${fmt(r.total_profit_percent, 2)}%</div></div>
            <div class="card"><h3>Win Rate</h3><div class="value positive">${fmt(r.win_rate_percent, 1)}%</div><div class="sub">${r.win_count}W / ${r.loss_count}L / ${r.total_trades} total</div></div>
            <div class="card"><h3>Sharpe Ratio</h3><div class="value">${fmt(r.sharpe_ratio, 2)}</div><div class="sub">Max Drawdown: ${fmt(r.max_drawdown_percent, 2)}%</div></div>
            <div class="card"><h3>Best Trade</h3><div class="value positive">+${fmt(r.best_trade_ton)} TON</div><div class="sub">Worst: ${fmt(r.worst_trade_ton)} TON</div></div>
            <div class="card"><h3>Avg Hold Time</h3><div class="value">${fmt(r.avg_hold_hours, 1)}h</div><div class="sub">Period: ${r.period}</div></div>
        </div>
    `;
}

function showTab(name) {
    ['overview','purchases','opportunities','backtest'].forEach(t => {
        document.getElementById(`tab-${t}`).style.display = t === name ? 'block' : 'none';
    });
    document.querySelectorAll('.tab').forEach((el, i) => {
        el.classList.toggle('active', ['overview','purchases','opportunities','backtest'][i] === name);
    });
    if (name === 'purchases') loadPurchases();
    if (name === 'opportunities') loadOpportunities();
}

async function loadAll() {
    try { await loadStats(); } catch(e) { console.error('Stats error:', e); }
}

loadAll();
setInterval(loadAll, 30000);
</script>
</body>
</html>
"""
