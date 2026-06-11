from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from loguru import logger
from sqlalchemy import select, func, and_, desc
import statistics as stats

from ..database.operations import GiftRepository, Database
from ..database.models import PurchaseRecord, SaleRecord, MarketStats, OpportunityLog
from ..utils.helpers import safe_divide, format_ton, format_percent


@dataclass
class PnLSummary:
    total_purchases: int
    total_spent_ton: float
    total_revenue_ton: float
    total_profit_ton: float
    total_profit_percent: float
    realized_profit_ton: float
    unrealized_profit_ton: float
    win_count: int
    loss_count: int
    win_rate_percent: float
    avg_profit_per_trade_ton: float
    best_trade_ton: float
    worst_trade_ton: float
    avg_discount_percent: float
    avg_hold_hours: float


@dataclass
class CollectionStats:
    collection_id: str
    total_listings: int
    floor_price_ton: Optional[float]
    avg_price_ton: Optional[float]
    volume_24h_ton: float
    sales_count_24h: int
    price_change_24h_percent: float
    opportunities_found: int


class StatisticsEngine:
    def __init__(self, db: Database):
        self.db = db

    async def get_pnl_summary(
        self,
        account_name: Optional[str] = None,
        days: int = 30,
    ) -> PnLSummary:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        async with self.db.session() as session:
            query = select(PurchaseRecord).where(
                and_(
                    PurchaseRecord.purchased_at >= cutoff,
                    PurchaseRecord.status == "success",
                )
            )
            if account_name:
                query = query.where(PurchaseRecord.account_name == account_name)

            result = await session.execute(query)
            purchases: List[PurchaseRecord] = result.scalars().all()

        if not purchases:
            return PnLSummary(
                total_purchases=0, total_spent_ton=0, total_revenue_ton=0,
                total_profit_ton=0, total_profit_percent=0,
                realized_profit_ton=0, unrealized_profit_ton=0,
                win_count=0, loss_count=0, win_rate_percent=0,
                avg_profit_per_trade_ton=0, best_trade_ton=0, worst_trade_ton=0,
                avg_discount_percent=0, avg_hold_hours=0,
            )

        total_spent = sum(p.purchase_price_ton for p in purchases)
        sold_purchases = [p for p in purchases if p.sell_price_ton is not None]
        unsold_purchases = [p for p in purchases if p.sell_price_ton is None]

        total_revenue = sum(p.sell_price_ton for p in sold_purchases)
        realized_profit = sum(
            (p.sell_price_ton - p.purchase_price_ton) for p in sold_purchases
        )
        unrealized_profit = 0.0

        profits = [p.profit_ton for p in sold_purchases if p.profit_ton is not None]
        win_count = sum(1 for p in profits if p > 0)
        loss_count = sum(1 for p in profits if p <= 0)

        hold_hours = []
        for p in sold_purchases:
            if p.sold_at and p.purchased_at:
                delta = (p.sold_at - p.purchased_at).total_seconds() / 3600
                hold_hours.append(delta)

        discounts = [p.discount_percent for p in purchases if p.discount_percent]

        return PnLSummary(
            total_purchases=len(purchases),
            total_spent_ton=total_spent,
            total_revenue_ton=total_revenue,
            total_profit_ton=realized_profit + unrealized_profit,
            total_profit_percent=safe_divide(realized_profit, total_spent) * 100,
            realized_profit_ton=realized_profit,
            unrealized_profit_ton=unrealized_profit,
            win_count=win_count,
            loss_count=loss_count,
            win_rate_percent=safe_divide(win_count, max(win_count + loss_count, 1)) * 100,
            avg_profit_per_trade_ton=safe_divide(realized_profit, len(sold_purchases)) if sold_purchases else 0,
            best_trade_ton=max(profits) if profits else 0,
            worst_trade_ton=min(profits) if profits else 0,
            avg_discount_percent=stats.mean(discounts) if discounts else 0,
            avg_hold_hours=stats.mean(hold_hours) if hold_hours else 0,
        )

    async def get_daily_pnl(self, days: int = 30) -> List[Dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        async with self.db.session() as session:
            result = await session.execute(
                select(PurchaseRecord)
                .where(and_(
                    PurchaseRecord.purchased_at >= cutoff,
                    PurchaseRecord.status == "success",
                ))
                .order_by(PurchaseRecord.purchased_at)
            )
            purchases: List[PurchaseRecord] = result.scalars().all()

        daily: Dict[str, Dict] = {}
        for p in purchases:
            day = p.purchased_at.strftime("%Y-%m-%d")
            if day not in daily:
                daily[day] = {"date": day, "purchases": 0, "spent": 0.0, "profit": 0.0, "revenue": 0.0}
            daily[day]["purchases"] += 1
            daily[day]["spent"] += p.purchase_price_ton
            if p.profit_ton:
                daily[day]["profit"] += p.profit_ton
            if p.sell_price_ton:
                daily[day]["revenue"] += p.sell_price_ton

        return sorted(daily.values(), key=lambda x: x["date"])

    async def get_collection_stats(self, collection_id: str) -> CollectionStats:
        cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)

        async with self.db.session() as session:
            listings_result = await session.execute(
                select(func.count()).where(
                    and_(
                        SaleRecord.collection_id == collection_id,
                    )
                )
            )

            sales_24h = await session.execute(
                select(func.count(), func.sum(SaleRecord.price_ton))
                .where(and_(
                    SaleRecord.collection_id == collection_id,
                    SaleRecord.sold_at >= cutoff_24h,
                ))
            )
            sales_row = sales_24h.one()

            opps = await session.execute(
                select(func.count(OpportunityLog.id))
                .where(OpportunityLog.collection_id == collection_id)
            )

            prev_stats = await session.execute(
                select(MarketStats)
                .where(MarketStats.collection_id == collection_id)
                .order_by(desc(MarketStats.recorded_at))
                .limit(2)
            )
            stats_rows = prev_stats.scalars().all()

        floor = stats_rows[0].floor_price_ton if stats_rows else None
        avg = stats_rows[0].avg_price_ton if stats_rows else None
        prev_floor = stats_rows[1].floor_price_ton if len(stats_rows) > 1 else floor

        price_change = 0.0
        if floor and prev_floor and prev_floor > 0:
            price_change = ((floor - prev_floor) / prev_floor) * 100

        return CollectionStats(
            collection_id=collection_id,
            total_listings=stats_rows[0].listings_count if stats_rows else 0,
            floor_price_ton=floor,
            avg_price_ton=avg,
            volume_24h_ton=stats_rows[0].volume_24h_ton if stats_rows else 0.0,
            sales_count_24h=sales_row[0] or 0,
            price_change_24h_percent=price_change,
            opportunities_found=opps.scalar_one() or 0,
        )

    async def get_top_opportunities(self, limit: int = 20) -> List[Dict[str, Any]]:
        async with self.db.session() as session:
            result = await session.execute(
                select(OpportunityLog)
                .order_by(desc(OpportunityLog.discount_percent))
                .limit(limit)
            )
            opps = result.scalars().all()

        return [
            {
                "gift_id": o.gift_id,
                "collection_id": o.collection_id,
                "price": o.current_price_ton,
                "floor": o.floor_price_ton,
                "discount": o.discount_percent,
                "rarity": o.rarity_score,
                "action": o.action_taken,
                "discovered_at": o.discovered_at.isoformat(),
            }
            for o in opps
        ]

    async def get_account_performance(self) -> List[Dict[str, Any]]:
        async with self.db.session() as session:
            result = await session.execute(
                select(
                    PurchaseRecord.account_name,
                    func.count(PurchaseRecord.id).label("count"),
                    func.sum(PurchaseRecord.purchase_price_ton).label("spent"),
                    func.sum(PurchaseRecord.profit_ton).label("profit"),
                    func.avg(PurchaseRecord.discount_percent).label("avg_discount"),
                )
                .where(PurchaseRecord.status == "success")
                .group_by(PurchaseRecord.account_name)
            )
            rows = result.all()

        return [
            {
                "account": r.account_name,
                "purchases": r.count,
                "spent_ton": round(r.spent or 0, 4),
                "profit_ton": round(r.profit or 0, 4),
                "avg_discount_percent": round(r.avg_discount or 0, 2),
                "roi_percent": safe_divide(r.profit or 0, r.spent or 1) * 100,
            }
            for r in rows
        ]

    async def format_pnl_report(self, summary: PnLSummary) -> str:
        profit_icon = "📈" if summary.total_profit_ton >= 0 else "📉"
        return (
            f"{'='*40}\n"
            f"📊 P&L REPORT\n"
            f"{'='*40}\n"
            f"Total Trades:       {summary.total_purchases}\n"
            f"Total Spent:        {format_ton(summary.total_spent_ton)}\n"
            f"Total Revenue:      {format_ton(summary.total_revenue_ton)}\n"
            f"{profit_icon} Total Profit:   {format_ton(summary.total_profit_ton)}\n"
            f"ROI:                {format_percent(summary.total_profit_percent)}\n"
            f"{'─'*40}\n"
            f"Realized:           {format_ton(summary.realized_profit_ton)}\n"
            f"Unrealized:         {format_ton(summary.unrealized_profit_ton)}\n"
            f"{'─'*40}\n"
            f"Win/Loss:           {summary.win_count}W / {summary.loss_count}L\n"
            f"Win Rate:           {summary.win_rate_percent:.1f}%\n"
            f"Best Trade:         {format_ton(summary.best_trade_ton)}\n"
            f"Worst Trade:        {format_ton(summary.worst_trade_ton)}\n"
            f"Avg Profit/Trade:   {format_ton(summary.avg_profit_per_trade_ton)}\n"
            f"Avg Discount:       {format_percent(summary.avg_discount_percent)}\n"
            f"Avg Hold Time:      {summary.avg_hold_hours:.1f}h\n"
            f"{'='*40}"
        )
