import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.traders.strategy import TradingStrategy, TradeOpportunity
from src.config import Settings, TradingConfig, AnalysisConfig


def make_settings(threshold: float = 20.0, enabled: bool = True) -> Settings:
    s = Settings()
    s.trading = TradingConfig(
        enabled=enabled,
        underpriced_threshold_percent=threshold,
        max_single_purchase_ton=50.0,
        min_floor_price_ton=0.1,
        max_floor_price_ton=500.0,
        require_min_sales_count=1,
    )
    s.analysis = AnalysisConfig()
    return s


@pytest.mark.asyncio
async def test_evaluate_gift_underpriced():
    settings = make_settings(threshold=20.0)
    mock_repo = AsyncMock()
    mock_repo.get_floor_price.return_value = 10.0
    mock_repo.get_avg_sale_price.return_value = 9.5
    mock_repo.get_last_n_sales_avg.return_value = 9.0
    mock_repo.get_recent_sales.return_value = [MagicMock()] * 5

    strategy = TradingStrategy(settings, mock_repo)

    gift_data = {
        "gift_id": "test_001",
        "collection_id": "col_001",
        "name": "Test Gift #1",
        "current_price_ton": 7.0,
        "rarity_score": 0.8,
        "rarity_rank": 10,
        "supply": 500,
        "is_for_sale": True,
    }

    opp = await strategy.evaluate_gift(gift_data)

    assert opp is not None
    assert opp.should_buy is True
    assert opp.discount_vs_floor == pytest.approx(30.0, abs=0.1)
    assert opp.opportunity_score > 0


@pytest.mark.asyncio
async def test_evaluate_gift_fairly_priced():
    settings = make_settings(threshold=20.0)
    mock_repo = AsyncMock()
    mock_repo.get_floor_price.return_value = 10.0
    mock_repo.get_avg_sale_price.return_value = 10.5
    mock_repo.get_last_n_sales_avg.return_value = 10.2
    mock_repo.get_recent_sales.return_value = [MagicMock()] * 5

    strategy = TradingStrategy(settings, mock_repo)

    gift_data = {
        "gift_id": "test_002",
        "collection_id": "col_001",
        "name": "Test Gift #2",
        "current_price_ton": 9.5,
        "is_for_sale": True,
    }

    opp = await strategy.evaluate_gift(gift_data)
    assert opp is not None
    assert opp.should_buy is False


@pytest.mark.asyncio
async def test_evaluate_gift_no_sales_history():
    settings = make_settings(threshold=20.0)
    mock_repo = AsyncMock()
    mock_repo.get_floor_price.return_value = 10.0
    mock_repo.get_avg_sale_price.return_value = 10.0
    mock_repo.get_last_n_sales_avg.return_value = 10.0
    mock_repo.get_recent_sales.return_value = []

    strategy = TradingStrategy(settings, mock_repo)

    gift_data = {
        "gift_id": "test_003",
        "collection_id": "col_001",
        "name": "Test Gift #3",
        "current_price_ton": 5.0,
        "is_for_sale": True,
    }

    opp = await strategy.evaluate_gift(gift_data)
    assert opp is None


@pytest.mark.asyncio
async def test_evaluate_gift_exceeds_max_price():
    settings = make_settings()
    mock_repo = AsyncMock()

    strategy = TradingStrategy(settings, mock_repo)

    gift_data = {
        "gift_id": "test_004",
        "collection_id": "col_001",
        "name": "Expensive Gift",
        "current_price_ton": 999.0,
        "is_for_sale": True,
    }

    opp = await strategy.evaluate_gift(gift_data)
    assert opp is None


@pytest.mark.asyncio
async def test_evaluate_batch():
    settings = make_settings(threshold=15.0)
    mock_repo = AsyncMock()
    mock_repo.get_floor_price.return_value = 10.0
    mock_repo.get_avg_sale_price.return_value = 10.0
    mock_repo.get_last_n_sales_avg.return_value = 10.0
    mock_repo.get_recent_sales.return_value = [MagicMock()] * 3

    strategy = TradingStrategy(settings, mock_repo)

    gifts = [
        {"gift_id": f"test_{i:03d}", "collection_id": "col_001",
         "name": f"Gift {i}", "current_price_ton": price, "is_for_sale": True}
        for i, price in [(1, 7.0), (2, 8.5), (3, 9.0), (4, 10.5)]
    ]

    opps = await strategy.evaluate_batch(gifts)
    assert len(opps) > 0
    scores = [o.opportunity_score for o in opps]
    assert scores == sorted(scores, reverse=True)
