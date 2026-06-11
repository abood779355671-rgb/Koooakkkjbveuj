import asyncio
import signal
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from loguru import logger

from ..config import Settings, get_settings
from ..database.operations import Database, GiftRepository
from ..monitors.market_monitor import MarketMonitor
from ..traders.strategy import TradingStrategy, TradeOpportunity
from ..traders.auto_buyer import AutoBuyer
from ..notifications.telegram_notifier import TelegramNotifier
from ..analytics.statistics import StatisticsEngine


class GiftManager:
    instance: Optional["GiftManager"] = None

    def __init__(self, settings: Settings):
        self.settings = settings
        self.db: Optional[Database] = None
        self.gift_repo: Optional[GiftRepository] = None
        self.monitor: Optional[MarketMonitor] = None
        self.strategy: Optional[TradingStrategy] = None
        self.buyer: Optional[AutoBuyer] = None
        self.notifier: Optional[TelegramNotifier] = None
        self.stats_engine: Optional[StatisticsEngine] = None
        self._tasks: List[asyncio.Task] = []
        self._running = False
        GiftManager.instance = self

    async def initialize(self):
        logger.info("Initializing Gift Manager...")

        self.db = Database(self.settings.database)
        await self.db.initialize()

        self.gift_repo = GiftRepository(self.db)
        self.strategy = TradingStrategy(self.settings, self.gift_repo)
        self.buyer = AutoBuyer(self.settings, self.gift_repo)
        self.notifier = TelegramNotifier(self.settings.notification_bot)
        self.stats_engine = StatisticsEngine(self.db)

        self.monitor = MarketMonitor(self.settings, self.gift_repo)
        self.monitor.add_callback(self._on_new_listings)

        await self.notifier.start()
        await self.buyer.initialize_clients()

        logger.info("Gift Manager initialized successfully")
        self.notifier.notify_system_start(
            accounts_count=len(self.settings.telegram_accounts),
            trading_enabled=self.settings.trading.enabled,
        )

    async def start(self):
        self._running = True
        logger.info("Starting Gift Manager...")

        task_monitor = asyncio.create_task(self.monitor.start(), name="market_monitor")
        self._tasks.append(task_monitor)

        if self.settings.api.enabled:
            task_api = asyncio.create_task(self._start_api_server(), name="api_server")
            self._tasks.append(task_api)

        task_daily = asyncio.create_task(self._daily_stats_loop(), name="daily_stats")
        self._tasks.append(task_daily)

        try:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        except asyncio.CancelledError:
            logger.info("Gift Manager tasks cancelled")

    async def stop(self):
        self._running = False
        logger.info("Stopping Gift Manager...")

        if self.monitor:
            await self.monitor.stop()

        for task in self._tasks:
            task.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)

        if self.buyer:
            await self.buyer.shutdown_clients()

        if self.notifier:
            await self.notifier.stop()

        if self.db:
            await self.db.close()

        logger.info("Gift Manager stopped")

    async def _on_new_listings(self, gifts: List[Dict[str, Any]]):
        if not gifts:
            return

        logger.debug(f"Processing {len(gifts)} new/updated listings")
        opportunities = await self.strategy.evaluate_batch(gifts)

        for opp in opportunities:
            if opp.discount_vs_floor < 5:
                continue

            await self.gift_repo.log_opportunity({
                "gift_id": opp.gift_id,
                "collection_id": opp.collection_id,
                "current_price_ton": opp.current_price_ton,
                "floor_price_ton": opp.floor_price_ton,
                "avg_price_ton": opp.avg_price_ton,
                "discount_percent": opp.discount_vs_floor,
                "rarity_score": opp.rarity_score,
                "action_taken": "buy" if opp.should_buy else "notified",
                "details_json": {
                    "rarity_rank": opp.rarity_rank,
                    "supply": opp.supply,
                    "score": opp.opportunity_score,
                },
            })

            if opp.discount_vs_floor >= self.settings.trading.underpriced_threshold_percent:
                self.notifier.notify_opportunity(opp)
                logger.info(
                    f"Opportunity: {opp.gift_name} at {opp.current_price_ton:.4f} TON "
                    f"(floor discount: {opp.discount_vs_floor:.1f}%)"
                )

            if opp.should_buy and self.settings.trading.enabled:
                await self._try_buy(opp)

    async def _try_buy(self, opp: TradeOpportunity):
        enabled_accounts = [
            acc for acc in self.settings.telegram_accounts if acc.enabled
        ]

        for account in enabled_accounts:
            can_buy, reason = await self.buyer.can_buy(account.name, opp.current_price_ton)
            if not can_buy:
                logger.debug(f"Account {account.name} cannot buy: {reason}")
                continue

            result = await self.buyer.execute_purchase(opp, account.name)

            if result.get("success"):
                if not result.get("dry_run"):
                    self.notifier.notify_purchase_success(
                        opp, account.name, result.get("tx_hash", "")
                    )
            else:
                self.notifier.notify_purchase_failed(
                    opp, account.name, result.get("error", "Unknown error")
                )
            break

    async def _start_api_server(self):
        import uvicorn
        from ..api.dashboard import create_app

        app = create_app()
        config = uvicorn.Config(
            app,
            host=self.settings.api.host,
            port=self.settings.api.port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        logger.info(f"Dashboard starting at http://{self.settings.api.host}:{self.settings.api.port}")
        await server.serve()

    async def _daily_stats_loop(self):
        while self._running:
            await asyncio.sleep(86400)
            try:
                summary = await self.gift_repo.get_portfolio_summary()
                self.notifier.notify_stats_summary(summary)
            except Exception as e:
                logger.error(f"Daily stats error: {e}")

    async def run_backtest(self, strategy: str = "underpriced"):
        from ..analytics.backtesting import Backtester
        backtester = Backtester(
            db=self.db,
            backtest_config=self.settings.backtesting,
            trading_config=self.settings.trading,
            analysis_config=self.settings.analysis,
        )
        return await backtester.run(strategy_name=strategy)

    async def print_stats(self):
        summary = await self.stats_engine.get_pnl_summary()
        report = await self.stats_engine.format_pnl_report(summary)
        print(report)
