import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
from src.analytics.backtesting import Backtester, BacktestResult
from src.config import BacktestingConfig, TradingConfig, AnalysisConfig
from src.database.models import SaleRecord


def make_sale(collection_id: str, gift_id: str, price: float, days_ago: float) -> SaleRecord:
    s = SaleRecord()
    s.collection_id = collection_id
    s.gift_id = gift_id
    s.price_ton = price
    s.sold_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return s


@pytest.mark.asyncio
async def test_backtest_basic():
    db = MagicMock()
    db.session = MagicMock()

    sales = []
    for i in range(20):
        sales.append(make_sale("col_001", f"gift_{i:03d}", 10.0, 20 - i))
    sales.append(make_sale("col_001", "gift_cheap", 7.0, 10))
    sales.append(make_sale("col_001", "gift_cheap_buy", 10.5, 9))

    async def mock_load(*args, **kwargs):
        return sales

    backtest_config = BacktestingConfig(
        start_date=(datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d"),
        end_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        initial_capital_ton=100.0,
        commission_percent=0.5,
        simulate_slippage=True,
    )

    trading_config = TradingConfig(
        enabled=True,
        underpriced_threshold_percent=20.0,
        max_single_purchase_ton=50.0,
        min_floor_price_ton=0.1,
        max_floor_price_ton=500.0,
        require_min_sales_count=3,
    )

    analysis_config = AnalysisConfig()

    backtester = Backtester(db, backtest_config, trading_config, analysis_config)
    backtester._load_historical_sales = mock_load

    result = await backtester.run()

    assert isinstance(result, BacktestResult)
    assert result.initial_capital == 100.0
    assert result.total_trades >= 0
    assert 0.0 <= result.win_rate <= 100.0


def test_floor_calculation():
    db = MagicMock()
    backtester = Backtester(
        db,
        BacktestingConfig(),
        TradingConfig(),
        AnalysisConfig(),
    )

    sales = [make_sale("col", "g1", p, 1) for p in [10.0, 8.0, 12.0, 9.0]]
    floor = backtester._calculate_floor(sales)
    assert floor == 8.0


def test_avg_calculation():
    db = MagicMock()
    backtester = Backtester(
        db,
        BacktestingConfig(),
        TradingConfig(),
        AnalysisConfig(),
    )

    ref_date = datetime.now(timezone.utc)
    sales = [make_sale("col", "g1", 10.0, i) for i in range(1, 6)]
    avg = backtester._calculate_avg(sales, days=10, reference_date=ref_date)
    assert avg == pytest.approx(10.0)


def test_max_drawdown():
    db = MagicMock()
    backtester = Backtester(db, BacktestingConfig(), TradingConfig(), AnalysisConfig())

    equity = [
        {"capital": 100},
        {"capital": 110},
        {"capital": 90},
        {"capital": 105},
    ]
    dd = backtester._calculate_max_drawdown(equity)
    assert dd == pytest.approx(100 * (110 - 90) / 110, abs=0.01)
