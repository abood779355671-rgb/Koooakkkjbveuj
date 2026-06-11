from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
from sqlalchemy import select, update, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from loguru import logger

from .models import (
    Base, Gift, GiftCollection, SaleRecord, PriceHistory,
    PurchaseRecord, DailyLimit, OpportunityLog, MarketStats
)
from ..config import DatabaseConfig


class Database:
    def __init__(self, config: DatabaseConfig):
        self.config = config
        self.engine = None
        self.session_factory = None

    async def initialize(self):
        if self.config.type == "sqlite":
            import aiosqlite
            db_path = self.config.sqlite_path
            from pathlib import Path
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            url = f"sqlite+aiosqlite:///{db_path}"
        else:
            url = self.config.postgres_url.replace("postgresql://", "postgresql+asyncpg://")

        self.engine = create_async_engine(url, echo=False, pool_pre_ping=True)
        self.session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False, class_=AsyncSession
        )

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        logger.info(f"Database initialized: {self.config.type}")

    async def close(self):
        if self.engine:
            await self.engine.dispose()

    def session(self) -> AsyncSession:
        return self.session_factory()


class GiftRepository:
    def __init__(self, db: Database):
        self.db = db

    async def upsert_collection(self, collection_data: Dict[str, Any]) -> GiftCollection:
        async with self.db.session() as session:
            async with session.begin():
                result = await session.execute(
                    select(GiftCollection).where(
                        GiftCollection.collection_id == collection_data["collection_id"]
                    )
                )
                collection = result.scalar_one_or_none()

                if collection:
                    for key, value in collection_data.items():
                        setattr(collection, key, value)
                    collection.updated_at = datetime.now(timezone.utc)
                else:
                    collection = GiftCollection(**collection_data)
                    session.add(collection)

                await session.flush()
                return collection

    async def upsert_gift(self, gift_data: Dict[str, Any]) -> Gift:
        async with self.db.session() as session:
            async with session.begin():
                result = await session.execute(
                    select(Gift).where(Gift.gift_id == gift_data["gift_id"])
                )
                gift = result.scalar_one_or_none()

                if gift:
                    old_price = gift.current_price_ton
                    for key, value in gift_data.items():
                        setattr(gift, key, value)
                    gift.updated_at = datetime.now(timezone.utc)
                    gift.last_seen_at = datetime.now(timezone.utc)

                    if old_price != gift_data.get("current_price_ton") and gift_data.get("current_price_ton"):
                        price_entry = PriceHistory(
                            gift_id=gift.gift_id,
                            price_ton=gift_data["current_price_ton"],
                            is_for_sale=gift_data.get("is_for_sale", False),
                        )
                        session.add(price_entry)
                else:
                    gift = Gift(**gift_data)
                    gift.first_seen_at = datetime.now(timezone.utc)
                    gift.last_seen_at = datetime.now(timezone.utc)
                    session.add(gift)

                    if gift_data.get("current_price_ton"):
                        price_entry = PriceHistory(
                            gift_id=gift.gift_id,
                            price_ton=gift_data["current_price_ton"],
                            is_for_sale=gift_data.get("is_for_sale", False),
                        )
                        session.add(price_entry)

                await session.flush()
                return gift

    async def get_gift(self, gift_id: str) -> Optional[Gift]:
        async with self.db.session() as session:
            result = await session.execute(
                select(Gift).where(Gift.gift_id == gift_id)
            )
            return result.scalar_one_or_none()

    async def get_active_listings(self, collection_id: Optional[str] = None,
                                   max_price: Optional[float] = None) -> List[Gift]:
        async with self.db.session() as session:
            query = select(Gift).where(Gift.is_for_sale == True)
            if collection_id:
                query = query.where(Gift.collection_id == collection_id)
            if max_price:
                query = query.where(Gift.current_price_ton <= max_price)
            query = query.order_by(Gift.current_price_ton.asc())
            result = await session.execute(query)
            return result.scalars().all()

    async def get_recent_sales(self, collection_id: str, limit: int = 10) -> List[SaleRecord]:
        async with self.db.session() as session:
            result = await session.execute(
                select(SaleRecord)
                .where(SaleRecord.collection_id == collection_id)
                .order_by(desc(SaleRecord.sold_at))
                .limit(limit)
            )
            return result.scalars().all()

    async def add_sale_record(self, sale_data: Dict[str, Any]) -> Optional[SaleRecord]:
        async with self.db.session() as session:
            async with session.begin():
                if sale_data.get("transaction_hash"):
                    existing = await session.execute(
                        select(SaleRecord).where(
                            SaleRecord.transaction_hash == sale_data["transaction_hash"]
                        )
                    )
                    if existing.scalar_one_or_none():
                        return None

                sale = SaleRecord(**sale_data)
                session.add(sale)
                await session.flush()
                return sale

    async def get_floor_price(self, collection_id: str, window: int = 10) -> Optional[float]:
        async with self.db.session() as session:
            result = await session.execute(
                select(func.min(Gift.current_price_ton))
                .where(
                    and_(
                        Gift.collection_id == collection_id,
                        Gift.is_for_sale == True,
                        Gift.current_price_ton > 0,
                    )
                )
            )
            return result.scalar_one_or_none()

    async def get_avg_sale_price(self, collection_id: str, days: int = 7) -> Optional[float]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        async with self.db.session() as session:
            result = await session.execute(
                select(func.avg(SaleRecord.price_ton))
                .where(
                    and_(
                        SaleRecord.collection_id == collection_id,
                        SaleRecord.sold_at >= cutoff,
                    )
                )
            )
            return result.scalar_one_or_none()

    async def get_last_n_sales_avg(self, collection_id: str, n: int = 10) -> Optional[float]:
        async with self.db.session() as session:
            subq = (
                select(SaleRecord.price_ton)
                .where(SaleRecord.collection_id == collection_id)
                .order_by(desc(SaleRecord.sold_at))
                .limit(n)
                .subquery()
            )
            result = await session.execute(select(func.avg(subq.c.price_ton)))
            return result.scalar_one_or_none()

    async def was_recently_purchased(self, gift_id: str, hours: int = 24) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        async with self.db.session() as session:
            result = await session.execute(
                select(func.count(PurchaseRecord.id))
                .where(
                    and_(
                        PurchaseRecord.gift_id == gift_id,
                        PurchaseRecord.purchased_at >= cutoff,
                        PurchaseRecord.status.in_(["success", "pending"]),
                    )
                )
            )
            return result.scalar_one() > 0

    async def get_daily_limit(self, account_name: str) -> DailyLimit:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        async with self.db.session() as session:
            async with session.begin():
                result = await session.execute(
                    select(DailyLimit).where(
                        and_(
                            DailyLimit.account_name == account_name,
                            DailyLimit.date == today,
                        )
                    )
                )
                limit = result.scalar_one_or_none()
                if not limit:
                    limit = DailyLimit(account_name=account_name, date=today)
                    session.add(limit)
                    await session.flush()
                return limit

    async def update_daily_limit(self, account_name: str, spent_ton: float):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        async with self.db.session() as session:
            async with session.begin():
                result = await session.execute(
                    select(DailyLimit).where(
                        and_(
                            DailyLimit.account_name == account_name,
                            DailyLimit.date == today,
                        )
                    )
                )
                limit = result.scalar_one_or_none()
                if limit:
                    limit.total_spent_ton += spent_ton
                    limit.purchase_count += 1
                    limit.updated_at = datetime.now(timezone.utc)
                else:
                    limit = DailyLimit(
                        account_name=account_name,
                        date=today,
                        total_spent_ton=spent_ton,
                        purchase_count=1,
                    )
                    session.add(limit)

    async def log_opportunity(self, opportunity_data: Dict[str, Any]) -> OpportunityLog:
        async with self.db.session() as session:
            async with session.begin():
                opp = OpportunityLog(**opportunity_data)
                session.add(opp)
                await session.flush()
                return opp

    async def create_purchase_record(self, purchase_data: Dict[str, Any]) -> PurchaseRecord:
        async with self.db.session() as session:
            async with session.begin():
                purchase = PurchaseRecord(**purchase_data)
                session.add(purchase)
                await session.flush()
                return purchase

    async def update_purchase_record(self, purchase_id: int, updates: Dict[str, Any]):
        async with self.db.session() as session:
            async with session.begin():
                await session.execute(
                    update(PurchaseRecord)
                    .where(PurchaseRecord.id == purchase_id)
                    .values(**updates)
                )

    async def get_all_purchases(self, account_name: Optional[str] = None,
                                 status: Optional[str] = None,
                                 limit: int = 100) -> List[PurchaseRecord]:
        async with self.db.session() as session:
            query = select(PurchaseRecord)
            if account_name:
                query = query.where(PurchaseRecord.account_name == account_name)
            if status:
                query = query.where(PurchaseRecord.status == status)
            query = query.order_by(desc(PurchaseRecord.purchased_at)).limit(limit)
            result = await session.execute(query)
            return result.scalars().all()

    async def save_market_stats(self, stats_data: Dict[str, Any]) -> MarketStats:
        async with self.db.session() as session:
            async with session.begin():
                stats = MarketStats(**stats_data)
                session.add(stats)
                await session.flush()
                return stats

    async def get_portfolio_summary(self) -> Dict[str, Any]:
        async with self.db.session() as session:
            total_result = await session.execute(
                select(
                    func.count(PurchaseRecord.id),
                    func.sum(PurchaseRecord.purchase_price_ton),
                    func.sum(PurchaseRecord.profit_ton),
                ).where(PurchaseRecord.status == "success")
            )
            row = total_result.one()
            return {
                "total_purchases": row[0] or 0,
                "total_spent_ton": row[1] or 0.0,
                "total_profit_ton": row[2] or 0.0,
                "win_rate": await self._get_win_rate(session),
            }

    async def _get_win_rate(self, session: AsyncSession) -> float:
        total = await session.execute(
            select(func.count(PurchaseRecord.id)).where(
                and_(PurchaseRecord.status == "success", PurchaseRecord.profit_ton != None)
            )
        )
        wins = await session.execute(
            select(func.count(PurchaseRecord.id)).where(
                and_(PurchaseRecord.status == "success", PurchaseRecord.profit_ton > 0)
            )
        )
        total_count = total.scalar_one() or 0
        win_count = wins.scalar_one() or 0
        return (win_count / total_count * 100) if total_count > 0 else 0.0
