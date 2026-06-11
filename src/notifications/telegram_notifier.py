import asyncio
from datetime import datetime, timezone
from typing import Dict, Optional, Any
from loguru import logger

try:
    import aiogram
    from aiogram import Bot
    _AIOGRAM_VERSION = tuple(int(x) for x in aiogram.__version__.split(".")[:2])
    if _AIOGRAM_VERSION >= (3, 0):
        from aiogram.enums import ParseMode
        _PARSE_MODE_HTML = ParseMode.HTML
    else:
        from aiogram.types import ParseMode
        _PARSE_MODE_HTML = "html"
    USE_AIOGRAM = True
except ImportError:
    USE_AIOGRAM = False
    _PARSE_MODE_HTML = "HTML"

from ..config import NotificationBot
from ..traders.strategy import TradeOpportunity
from ..utils.helpers import format_ton, format_percent


class TelegramNotifier:
    def __init__(self, config: NotificationBot):
        self.config = config
        self._bot: Optional[Any] = None
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._running = False

    async def start(self):
        if not self.config.enabled or not self.config.bot_token:
            logger.warning("Telegram notifier disabled or bot token missing")
            self._running = True
            asyncio.create_task(self._send_loop())
            return

        if USE_AIOGRAM:
            try:
                if _AIOGRAM_VERSION >= (3, 0):
                    self._bot = Bot(token=self.config.bot_token)
                else:
                    self._bot = Bot(token=self.config.bot_token, parse_mode=_PARSE_MODE_HTML)
                logger.info(f"Telegram notifier started (aiogram {aiogram.__version__})")
            except Exception as e:
                logger.warning(f"aiogram bot init failed, using fallback: {e}")
                self._bot = None

        self._running = True
        asyncio.create_task(self._send_loop())

    async def stop(self):
        self._running = False
        if self._bot and USE_AIOGRAM:
            try:
                if _AIOGRAM_VERSION >= (3, 0):
                    await self._bot.session.close()
                else:
                    import warnings
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", DeprecationWarning)
                        await self._bot.close()
            except Exception:
                pass

    async def _send_loop(self):
        while self._running:
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._send_message(msg)
                await asyncio.sleep(0.5)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Notifier send loop error: {e}")

    async def _send_message(self, text: str):
        if not self.config.bot_token or not self.config.chat_id or self.config.chat_id == "YOUR_CHAT_ID":
            logger.debug(f"Notification (no chat_id): {text[:80]}...")
            return

        if USE_AIOGRAM and self._bot:
            try:
                if _AIOGRAM_VERSION >= (3, 0):
                    from aiogram.enums import ParseMode as PM
                    await self._bot.send_message(
                        chat_id=self.config.chat_id,
                        text=text,
                        parse_mode=PM.HTML,
                        disable_web_page_preview=True,
                    )
                else:
                    await self._bot.send_message(
                        chat_id=self.config.chat_id,
                        text=text,
                        parse_mode="html",
                        disable_web_page_preview=True,
                    )
                return
            except Exception as e:
                logger.error(f"aiogram send error: {e}")

        import aiohttp
        try:
            url = f"https://api.telegram.org/bot{self.config.bot_token}/sendMessage"
            payload = {
                "chat_id": self.config.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(f"Telegram API error {resp.status}: {body[:200]}")
        except Exception as e:
            logger.error(f"Fallback notifier error: {e}")

    def _enqueue(self, text: str):
        try:
            self._queue.put_nowait(text)
        except asyncio.QueueFull:
            logger.warning("Notification queue full — dropping message")

    def notify_opportunity(self, opportunity: TradeOpportunity):
        emoji = "🔥" if opportunity.discount_vs_floor >= 40 else "💡"
        text = (
            f"{emoji} <b>OPPORTUNITY FOUND</b>\n\n"
            f"🎁 <b>{opportunity.gift_name}</b>\n"
            f"🆔 Gift ID: <code>{opportunity.gift_id}</code>\n"
            f"📦 Collection: <code>{opportunity.collection_id}</code>\n\n"
            f"💰 <b>Current Price:</b> {format_ton(opportunity.current_price_ton)}\n"
            f"📊 <b>Floor Price:</b> {format_ton(opportunity.floor_price_ton) if opportunity.floor_price_ton else 'N/A'}\n"
            f"📈 <b>Avg Price (7d):</b> {format_ton(opportunity.avg_price_ton) if opportunity.avg_price_ton else 'N/A'}\n"
            f"📉 <b>Last 10 Sales Avg:</b> {format_ton(opportunity.last_10_avg_ton) if opportunity.last_10_avg_ton else 'N/A'}\n\n"
            f"🏷️ <b>Discount vs Floor:</b> {format_percent(opportunity.discount_vs_floor)}\n"
            f"🏷️ <b>Discount vs Avg:</b> {format_percent(opportunity.discount_vs_avg)}\n"
            f"⭐ <b>Rarity Score:</b> {opportunity.rarity_score or 'N/A'}\n"
            f"🎯 <b>Opportunity Score:</b> {opportunity.opportunity_score:.4f}\n\n"
            f"📝 {opportunity.reason}\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        self._enqueue(text)

    def notify_purchase_success(self, opportunity: TradeOpportunity, account_name: str, tx_hash: str):
        text = (
            f"✅ <b>PURCHASE SUCCESSFUL</b>\n\n"
            f"🎁 <b>{opportunity.gift_name}</b>\n"
            f"👤 Account: <code>{account_name}</code>\n"
            f"💸 <b>Paid:</b> {format_ton(opportunity.current_price_ton)}\n"
            f"📊 Floor was: {format_ton(opportunity.floor_price_ton) if opportunity.floor_price_ton else 'N/A'}\n"
            f"💹 Discount: {format_percent(opportunity.discount_vs_floor)}\n"
            f"🔗 TX: <code>{tx_hash}</code>\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        self._enqueue(text)

    def notify_purchase_failed(self, opportunity: TradeOpportunity, account_name: str, error: str):
        text = (
            f"❌ <b>PURCHASE FAILED</b>\n\n"
            f"🎁 <b>{opportunity.gift_name}</b>\n"
            f"👤 Account: <code>{account_name}</code>\n"
            f"💰 Price: {format_ton(opportunity.current_price_ton)}\n"
            f"⚠️ <b>Error:</b> {error}\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        self._enqueue(text)

    def notify_daily_limit_reached(self, account_name: str, spent: float, limit: float):
        text = (
            f"⛔ <b>DAILY LIMIT REACHED</b>\n\n"
            f"👤 Account: <code>{account_name}</code>\n"
            f"💸 Spent today: {format_ton(spent)}\n"
            f"📊 Daily limit: {format_ton(limit)}\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        self._enqueue(text)

    def notify_system_start(self, accounts_count: int, trading_enabled: bool):
        status = "🟢 ACTIVE" if trading_enabled else "👁️ MONITOR-ONLY"
        text = (
            f"🚀 <b>Gift Monitor Started</b>\n\n"
            f"👥 Accounts loaded: {accounts_count}\n"
            f"⚙️ Trading: {status}\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        self._enqueue(text)

    def notify_system_error(self, error: str, component: str):
        text = (
            f"🚨 <b>SYSTEM ERROR</b>\n\n"
            f"🔧 Component: <code>{component}</code>\n"
            f"⚠️ <b>Error:</b> {error[:500]}\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        self._enqueue(text)

    def notify_stats_summary(self, stats: Dict[str, Any]):
        profit = stats.get("total_profit_ton", 0.0)
        profit_sign = "+" if profit >= 0 else ""
        text = (
            f"📊 <b>Daily Stats Summary</b>\n\n"
            f"🛒 Total Purchases: {stats.get('total_purchases', 0)}\n"
            f"💸 Total Spent: {format_ton(stats.get('total_spent_ton', 0.0))}\n"
            f"💹 Total Profit: {profit_sign}{format_ton(profit)}\n"
            f"🏆 Win Rate: {stats.get('win_rate', 0.0):.1f}%\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        self._enqueue(text)
