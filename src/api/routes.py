from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Header
from pydantic import BaseModel

from ..database.operations import GiftRepository, Database
from ..analytics.statistics import StatisticsEngine
from ..analytics.backtesting import Backtester
from ..config import Settings


router = APIRouter()


class PurchaseResponse(BaseModel):
    gift_id: str
    collection_id: str
    account_name: str
    purchase_price_ton: float
    status: str
    discount_percent: Optional[float]
    purchased_at: str


class OpportunityResponse(BaseModel):
    gift_id: str
    collection_id: str
    current_price_ton: float
    floor_price_ton: Optional[float]
    discount_percent: float
    rarity_score: Optional[float]
    action_taken: str
    discovered_at: str


def get_db(db: Database = None) -> Database:
    from ..core.gift_manager import GiftManager
    return GiftManager.instance.db if GiftManager.instance else None


def get_settings() -> Settings:
    from ..config import get_settings as _get_settings
    return _get_settings()


def verify_api_key(x_api_key: str = Header(None), settings: Settings = Depends(get_settings)):
    if settings.api.secret_key and settings.api.secret_key != "CHANGE_THIS_SECRET_KEY":
        if x_api_key != settings.api.secret_key:
            raise HTTPException(status_code=401, detail="Invalid API key")


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "gift-monitor",
    }


@router.get("/stats/pnl")
async def get_pnl(
    account_name: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365),
    _: None = Depends(verify_api_key),
):
    from ..core.gift_manager import GiftManager
    manager = GiftManager.instance
    if not manager:
        raise HTTPException(status_code=503, detail="System not initialized")

    engine = StatisticsEngine(manager.db)
    summary = await engine.get_pnl_summary(account_name=account_name, days=days)
    return {
        "total_purchases": summary.total_purchases,
        "total_spent_ton": summary.total_spent_ton,
        "total_revenue_ton": summary.total_revenue_ton,
        "total_profit_ton": summary.total_profit_ton,
        "total_profit_percent": summary.total_profit_percent,
        "realized_profit_ton": summary.realized_profit_ton,
        "unrealized_profit_ton": summary.unrealized_profit_ton,
        "win_count": summary.win_count,
        "loss_count": summary.loss_count,
        "win_rate_percent": summary.win_rate_percent,
        "avg_profit_per_trade_ton": summary.avg_profit_per_trade_ton,
        "best_trade_ton": summary.best_trade_ton,
        "worst_trade_ton": summary.worst_trade_ton,
        "avg_discount_percent": summary.avg_discount_percent,
        "avg_hold_hours": summary.avg_hold_hours,
        "period_days": days,
    }


@router.get("/stats/daily")
async def get_daily_pnl(
    days: int = Query(30, ge=1, le=365),
    _: None = Depends(verify_api_key),
):
    from ..core.gift_manager import GiftManager
    manager = GiftManager.instance
    if not manager:
        raise HTTPException(status_code=503, detail="System not initialized")

    engine = StatisticsEngine(manager.db)
    data = await engine.get_daily_pnl(days=days)
    return {"data": data, "days": days}


@router.get("/stats/accounts")
async def get_account_performance(_: None = Depends(verify_api_key)):
    from ..core.gift_manager import GiftManager
    manager = GiftManager.instance
    if not manager:
        raise HTTPException(status_code=503, detail="System not initialized")

    engine = StatisticsEngine(manager.db)
    return {"accounts": await engine.get_account_performance()}


@router.get("/stats/opportunities")
async def get_opportunities(
    limit: int = Query(20, ge=1, le=100),
    _: None = Depends(verify_api_key),
):
    from ..core.gift_manager import GiftManager
    manager = GiftManager.instance
    if not manager:
        raise HTTPException(status_code=503, detail="System not initialized")

    engine = StatisticsEngine(manager.db)
    opps = await engine.get_top_opportunities(limit=limit)
    return {"opportunities": opps, "count": len(opps)}


@router.get("/purchases")
async def get_purchases(
    account_name: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _: None = Depends(verify_api_key),
):
    from ..core.gift_manager import GiftManager
    manager = GiftManager.instance
    if not manager:
        raise HTTPException(status_code=503, detail="System not initialized")

    purchases = await manager.gift_repo.get_all_purchases(
        account_name=account_name, status=status, limit=limit
    )
    return {
        "purchases": [
            {
                "id": p.id,
                "gift_id": p.gift_id,
                "collection_id": p.collection_id,
                "account_name": p.account_name,
                "purchase_price_ton": p.purchase_price_ton,
                "floor_price_at_purchase": p.floor_price_at_purchase,
                "discount_percent": p.discount_percent,
                "status": p.status,
                "transaction_hash": p.transaction_hash,
                "profit_ton": p.profit_ton,
                "profit_percent": p.profit_percent,
                "purchased_at": p.purchased_at.isoformat(),
            }
            for p in purchases
        ],
        "count": len(purchases),
    }


@router.get("/market/listings")
async def get_active_listings(
    collection_id: Optional[str] = Query(None),
    max_price: Optional[float] = Query(None),
    _: None = Depends(verify_api_key),
):
    from ..core.gift_manager import GiftManager
    manager = GiftManager.instance
    if not manager:
        raise HTTPException(status_code=503, detail="System not initialized")

    listings = await manager.gift_repo.get_active_listings(
        collection_id=collection_id, max_price=max_price
    )
    return {
        "listings": [
            {
                "gift_id": g.gift_id,
                "collection_id": g.collection_id,
                "name": g.name,
                "price_ton": g.current_price_ton,
                "rarity_score": g.rarity_score,
                "rarity_rank": g.rarity_rank,
            }
            for g in listings
        ],
        "count": len(listings),
    }


@router.post("/backtest/run")
async def run_backtest(
    strategy: str = Query("underpriced"),
    _: None = Depends(verify_api_key),
):
    from ..core.gift_manager import GiftManager
    manager = GiftManager.instance
    if not manager:
        raise HTTPException(status_code=503, detail="System not initialized")

    settings = get_settings()
    backtester = Backtester(
        db=manager.db,
        backtest_config=settings.backtesting,
        trading_config=settings.trading,
        analysis_config=settings.analysis,
    )

    result = await backtester.run(strategy_name=strategy)
    return {
        "strategy": result.strategy_name,
        "period": f"{result.start_date.date()} to {result.end_date.date()}",
        "initial_capital_ton": result.initial_capital,
        "final_capital_ton": result.final_capital,
        "total_profit_ton": result.total_profit,
        "total_profit_percent": result.total_profit_percent,
        "total_trades": result.total_trades,
        "win_count": result.win_count,
        "loss_count": result.loss_count,
        "win_rate_percent": result.win_rate,
        "max_drawdown_percent": result.max_drawdown,
        "sharpe_ratio": result.sharpe_ratio,
        "avg_hold_hours": result.avg_hold_hours,
        "best_trade_ton": result.best_trade,
        "worst_trade_ton": result.worst_trade,
        "equity_curve": result.equity_curve[:100],
    }


@router.post("/backtest/compare")
async def compare_strategies(_: None = Depends(verify_api_key)):
    from ..core.gift_manager import GiftManager
    manager = GiftManager.instance
    if not manager:
        raise HTTPException(status_code=503, detail="System not initialized")

    settings = get_settings()
    backtester = Backtester(
        db=manager.db,
        backtest_config=settings.backtesting,
        trading_config=settings.trading,
        analysis_config=settings.analysis,
    )

    results = await backtester.run_multiple_strategies()
    comparison = []
    for name, r in results.items():
        comparison.append({
            "strategy": name,
            "profit_percent": r.total_profit_percent,
            "win_rate": r.win_rate,
            "total_trades": r.total_trades,
            "max_drawdown": r.max_drawdown,
            "sharpe_ratio": r.sharpe_ratio,
        })

    comparison.sort(key=lambda x: x["profit_percent"], reverse=True)
    return {"strategies": comparison}


@router.get("/system/status")
async def get_system_status(_: None = Depends(verify_api_key)):
    from ..core.gift_manager import GiftManager
    manager = GiftManager.instance

    if not manager:
        return {"status": "not_initialized"}

    return {
        "status": "running",
        "trading_enabled": manager.settings.trading.enabled,
        "auto_confirm": manager.settings.trading.auto_confirm,
        "scan_count": manager.monitor.get_scan_count() if manager.monitor else 0,
        "active_clients": manager.buyer.get_client_count() if manager.buyer else 0,
        "threshold_percent": manager.settings.trading.underpriced_threshold_percent,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
