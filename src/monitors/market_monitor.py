import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable
from loguru import logger

from ..config import Settings
from ..database.operations import GiftRepository
from ..utils.helpers import RateLimiter, CircuitBreaker, retry_async
from .gift_tracker import GiftTracker


class MarketMonitor:
    def __init__(self, settings: Settings, gift_repo: GiftRepository):
        self.settings = settings
        self.gift_repo = gift_repo
        self.tracker = GiftTracker(settings, gift_repo)
        self.rate_limiter = RateLimiter(
            max_calls=settings.monitoring.max_concurrent_requests,
            period=1.0,
        )
        self.circuit_breaker = CircuitBreaker(failure_threshold=5, reset_timeout=60)
        self._running = False
        self._callbacks: List[Callable] = []
        self._market_cache: Dict[str, Dict] = {}
        self._scan_count = 0

    def add_callback(self, callback: Callable):
        self._callbacks.append(callback)

    async def start(self):
        self._running = True
        logger.info("Market monitor started")
        await asyncio.gather(
            self._scan_loop(),
            self._market_refresh_loop(),
            return_exceptions=True,
        )

    async def stop(self):
        self._running = False
        logger.info("Market monitor stopped")

    async def _scan_loop(self):
        while self._running:
            try:
                if not self.circuit_breaker.is_open():
                    await self._scan_market()
                    self.circuit_breaker.record_success()
                else:
                    logger.warning("Circuit breaker open — skipping scan")
            except Exception as e:
                logger.error(f"Scan loop error: {e}")
                self.circuit_breaker.record_failure()

            await asyncio.sleep(self.settings.monitoring.scan_interval_seconds)

    async def _market_refresh_loop(self):
        while self._running:
            try:
                await self._refresh_market_data()
            except Exception as e:
                logger.error(f"Market refresh error: {e}")

            await asyncio.sleep(self.settings.monitoring.market_refresh_interval_seconds)

    async def _scan_market(self):
        self._scan_count += 1
        collections = await self._get_target_collections()
        tasks = []
        for collection_id in collections:
            tasks.append(self._scan_collection(collection_id))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        new_listings = []
        for result in results:
            if isinstance(result, list):
                new_listings.extend(result)
            elif isinstance(result, Exception):
                logger.error(f"Collection scan error: {result}")

        if new_listings:
            logger.info(f"Scan #{self._scan_count}: found {len(new_listings)} listings")
            for callback in self._callbacks:
                try:
                    await callback(new_listings)
                except Exception as e:
                    logger.error(f"Callback error: {e}")

    async def _scan_collection(self, collection_id: str) -> List[Dict[str, Any]]:
        await self.rate_limiter.acquire()
        gifts = await self.tracker.fetch_active_listings(collection_id)
        new_or_updated = []

        for gift_data in gifts:
            existing = await self.gift_repo.get_gift(gift_data["gift_id"])
            if not existing or existing.current_price_ton != gift_data.get("current_price_ton"):
                await self.gift_repo.upsert_gift(gift_data)
                new_or_updated.append(gift_data)

        return new_or_updated

    async def _refresh_market_data(self):
        collections = await self._get_target_collections()
        for collection_id in collections:
            try:
                await self.rate_limiter.acquire()
                floor = await self.gift_repo.get_floor_price(collection_id)
                avg = await self.gift_repo.get_avg_sale_price(collection_id, days=7)
                vol = await self._calculate_24h_volume(collection_id)
                listings = await self.gift_repo.get_active_listings(collection_id)

                stats = {
                    "collection_id": collection_id,
                    "floor_price_ton": floor,
                    "avg_price_ton": avg,
                    "volume_24h_ton": vol,
                    "listings_count": len(listings),
                    "recorded_at": datetime.now(timezone.utc),
                }
                await self.gift_repo.save_market_stats(stats)
                self._market_cache[collection_id] = stats
                logger.debug(f"Market refreshed [{collection_id}]: floor={floor} TON, avg={avg} TON")
            except Exception as e:
                logger.error(f"Error refreshing market for {collection_id}: {e}")

    async def _calculate_24h_volume(self, collection_id: str) -> float:
        from datetime import timedelta
        from sqlalchemy import select, func, and_
        from ..database.models import SaleRecord
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        async with self.gift_repo.db.session() as session:
            result = await session.execute(
                select(func.sum(SaleRecord.price_ton)).where(
                    and_(
                        SaleRecord.collection_id == collection_id,
                        SaleRecord.sold_at >= cutoff,
                    )
                )
            )
            return result.scalar_one_or_none() or 0.0

    async def _get_target_collections(self) -> List[str]:
        configured = self.settings.monitoring.track_collections
        if configured:
            return configured
        return await self.tracker.fetch_all_collection_ids()

    def get_market_cache(self, collection_id: str) -> Optional[Dict]:
        return self._market_cache.get(collection_id)

    def get_scan_count(self) -> int:
        return self._scan_count
