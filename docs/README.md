# Telegram Gift Monitor — Documentation

## Overview

A professional real-time monitoring and auto-buying system for **Telegram Collectible Gifts** and **NFT Gifts** on the TON blockchain.

## Features

| Feature | Description |
|---------|-------------|
| 🔍 Real-time Monitoring | Scans listings every 5 seconds across all collections |
| 📊 Market Analysis | Floor price, avg price, rarity scoring, 24h volume |
| 🤖 Auto Buyer | Purchases underpriced gifts automatically |
| 👥 Multi-Account | Supports multiple Telegram accounts with individual limits |
| 📈 Statistics | Full P&L dashboard with win rate, ROI, hold time |
| 🔬 Backtesting | Test strategies on historical data |
| 🔔 Notifications | Instant Telegram alerts for every event |
| 🛡️ Safety | Daily limits, duplicate protection, circuit breaker |
| 🖥️ Dashboard | Web dashboard at `http://localhost:8080` |

---

## Architecture

```
gift-monitor/
├── main.py                     # CLI entry point
├── settings.json               # Configuration
├── requirements.txt            # Dependencies
├── src/
│   ├── config.py               # Settings loader & dataclasses
│   ├── core/
│   │   └── gift_manager.py     # Main orchestrator
│   ├── database/
│   │   ├── models.py           # SQLAlchemy models
│   │   └── operations.py       # Repository pattern
│   ├── monitors/
│   │   ├── market_monitor.py   # Scan loop + callbacks
│   │   └── gift_tracker.py     # Fragment + GetGems API
│   ├── traders/
│   │   ├── strategy.py         # Trade evaluation engine
│   │   └── auto_buyer.py       # Purchase execution
│   ├── notifications/
│   │   └── telegram_notifier.py # Telegram bot alerts
│   ├── analytics/
│   │   ├── statistics.py       # P&L engine
│   │   └── backtesting.py      # Historical simulation
│   ├── api/
│   │   ├── dashboard.py        # FastAPI app + HTML dashboard
│   │   └── routes.py           # REST API endpoints
│   └── utils/
│       ├── logger.py           # Loguru setup
│       └── helpers.py          # Utilities, rate limiter, circuit breaker
├── tests/
│   ├── test_strategy.py
│   ├── test_helpers.py
│   └── test_backtesting.py
├── config/
│   └── settings.example.json
├── Dockerfile
└── docker-compose.yml
```

---

## Quick Start

### 1. Install Dependencies

```bash
cd gift-monitor
pip install -r requirements.txt
```

### 2. Configure Settings

```bash
cp config/settings.example.json settings.json
```

Edit `settings.json`:
- Add your Telegram API credentials (`api_id`, `api_hash`)
- Add your bot token and chat ID for notifications
- Set your trading limits

### 3. Get Telegram API Credentials

1. Go to [my.telegram.org](https://my.telegram.org)
2. Log in with your phone number
3. Click "API development tools"
4. Create a new application
5. Copy `api_id` and `api_hash`

### 4. Set Up Notification Bot

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow instructions
3. Copy the bot token to `settings.json`
4. Get your chat ID by messaging [@userinfobot](https://t.me/userinfobot)

### 5. First Run (Dry Run)

```bash
# Test without any actual purchases
python main.py start --dry-run

# Monitor only, no buying
python main.py start --monitor-only
```

### 6. Enable Auto-Buying

In `settings.json`:
```json
{
  "trading": {
    "enabled": true,
    "auto_confirm": true,   ← ONLY after testing!
    "underpriced_threshold_percent": 20,
    "max_daily_spend_ton": 50.0
  }
}
```

---

## CLI Commands

```bash
# Start the monitor
python main.py start

# Start in dry-run mode (no real purchases)
python main.py start --dry-run

# Start in monitor-only mode
python main.py start --monitor-only

# Run backtesting
python main.py backtest --strategy underpriced

# Show P&L statistics
python main.py stats --days 30

# Validate your settings file
python main.py validate-config
```

---

## Configuration Reference

### Trading Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | `false` | Enable auto-buying |
| `underpriced_threshold_percent` | `20` | Minimum discount % to trigger buy |
| `max_daily_spend_ton` | `100` | Maximum TON to spend per day per account |
| `max_daily_purchases` | `20` | Maximum purchases per day per account |
| `max_single_purchase_ton` | `10` | Maximum price for a single purchase |
| `require_min_sales_count` | `3` | Minimum historical sales required |
| `duplicate_protection_hours` | `24` | Cooldown after buying same gift |
| `auto_confirm` | `false` | Actually execute transactions |

### Analysis Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `floor_price_window_sales` | `10` | Sales used to calculate floor |
| `historical_avg_window_days` | `7` | Days for average price calculation |
| `rarity_weight` | `0.3` | Weight of rarity in opportunity score |
| `price_weight` | `0.5` | Weight of price discount in score |
| `volume_weight` | `0.2` | Weight of volume in score |

---

## Opportunity Score

Each gift gets a score from 0.0 to 1.0 based on:

```
score = (discount_vs_floor × price_weight)
      + (rarity_score × rarity_weight)
      + (discount_vs_avg × volume_weight)
```

A gift is bought when:
1. `discount_vs_floor >= threshold` (e.g., 20%)
2. `discount_vs_avg >= threshold × 0.8`
3. All daily limits are within bounds
4. No duplicate protection triggered

---

## REST API

The dashboard API runs at `http://localhost:8080`.

| Endpoint | Description |
|----------|-------------|
| `GET /` | Web dashboard |
| `GET /api/v1/health` | Health check |
| `GET /api/v1/stats/pnl` | P&L summary |
| `GET /api/v1/stats/daily` | Daily P&L chart data |
| `GET /api/v1/stats/accounts` | Per-account performance |
| `GET /api/v1/stats/opportunities` | Top opportunities found |
| `GET /api/v1/purchases` | Purchase history |
| `GET /api/v1/market/listings` | Active listings |
| `POST /api/v1/backtest/run` | Run backtest |
| `POST /api/v1/backtest/compare` | Compare strategies |
| `GET /api/v1/system/status` | System status |

### Authentication

Add header: `X-API-Key: your-secret-key`

---

## Backtesting

Run a backtest to evaluate performance on historical data:

```bash
python main.py backtest --strategy underpriced
```

Or via API:
```bash
curl -X POST http://localhost:8080/api/v1/backtest/run?strategy=underpriced
```

The system automatically compares multiple threshold levels (10%, 15%, 20%, 25%, 30%) to find the optimal strategy.

---

## Docker

```bash
# Build and run with Docker Compose
docker-compose up -d

# View logs
docker-compose logs -f gift-monitor

# Stop
docker-compose down
```

---

## Database Schema

| Table | Description |
|-------|-------------|
| `gift_collections` | Collection metadata & floor prices |
| `gifts` | Individual gift items with prices & rarity |
| `sale_records` | Historical sales transactions |
| `price_history` | Price tracking over time |
| `purchase_records` | Our purchase history & P&L |
| `daily_limits` | Per-account daily spend tracking |
| `opportunity_logs` | All detected opportunities |
| `market_stats` | Market snapshots over time |

---

## Safety Features

- **Dry Run Mode**: Test without real purchases (`--dry-run`)
- **Daily Limits**: Per-account spend cap and purchase count cap
- **Duplicate Protection**: Prevent buying the same gift twice in 24h
- **Circuit Breaker**: Pauses scanning after repeated API failures
- **Rate Limiter**: Respects API rate limits
- **Manual Confirmation**: `auto_confirm: false` logs but doesn't buy
- **Price Bounds**: Min/max price filters prevent extreme purchases

---

## ⚠️ Disclaimer

This tool is for educational purposes. Auto-buying carries financial risk. Always:
1. Test in dry-run mode first
2. Start with small daily limits
3. Monitor the system closely
4. You are responsible for all purchases made
