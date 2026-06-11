import asyncio
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple
from loguru import logger

try:
    from pyrogram import Client
    from pyrogram.errors import FloodWait, RPCError
    HAS_PYROGRAM = True
except ImportError:
    HAS_PYROGRAM = False
    Client = None

from ..config import Settings
from ..database.operations import GiftRepository
from ..traders.strategy import TradeOpportunity
from ..utils.helpers import format_ton, retry_async


class AutoBuyer:
    def __init__(self, settings: Settings, gift_repo: GiftRepository):
        self.settings = settings
        self.gift_repo = gift_repo
        self._clients: Dict[str, Any] = {}
        self._active_purchases: set = set()
        self._lock = asyncio.Lock()

    async def initialize_clients(self):
        if not HAS_PYROGRAM:
            logger.warning("pyrogram not installed — Telegram client disabled")
            return

        sessions_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "sessions")
        sessions_dir = os.path.abspath(sessions_dir)
        os.makedirs(sessions_dir, exist_ok=True)

        for account in self.settings.telegram_accounts:
            if not account.enabled:
                continue
            try:
                client = Client(
                    name=account.session_name,
                    api_id=int(account.api_id),
                    api_hash=account.api_hash,
                    phone_number=account.phone,
                    workdir=sessions_dir,
                    in_memory=False,
                )
                await client.start()
                self._clients[account.name] = client
                logger.info(f"Telegram client initialized: {account.name}")
            except Exception as e:
                logger.warning(
                    f"Client {account.name} not connected (needs interactive auth): {e}. "
                    f"Run 'python main.py auth' to authenticate."
                )

    async def shutdown_clients(self):
        for name, client in self._clients.items():
            try:
                await client.stop()
                logger.info(f"Client stopped: {name}")
            except Exception as e:
                logger.error(f"Error stopping client {name}: {e}")
        self._clients.clear()

    async def can_buy(self, account_name: str, price_ton: float) -> Tuple[bool, str]:
        limit = await self.gift_repo.get_daily_limit(account_name)
        trading = self.settings.trading

        if limit.total_spent_ton + price_ton > trading.max_daily_spend_ton:
            return False, f"Daily spend limit exceeded ({limit.total_spent_ton:.2f}/{trading.max_daily_spend_ton} TON)"

        if limit.purchase_count >= trading.max_daily_purchases:
            return False, f"Daily purchase limit reached ({limit.purchase_count}/{trading.max_daily_purchases})"

        if price_ton > trading.max_single_purchase_ton:
            return False, f"Price {price_ton:.4f} TON exceeds single purchase limit {trading.max_single_purchase_ton} TON"

        return True, "OK"

    async def execute_purchase(
        self, opportunity: TradeOpportunity, account_name: str
    ) -> Dict[str, Any]:
        if opportunity.gift_id in self._active_purchases:
            return {"success": False, "error": "Purchase already in progress for this gift"}

        async with self._lock:
            if await self.gift_repo.was_recently_purchased(
                opportunity.gift_id,
                self.settings.trading.duplicate_protection_hours
            ):
                return {"success": False, "error": "Duplicate protection triggered"}

            can, reason = await self.can_buy(account_name, opportunity.current_price_ton)
            if not can:
                return {"success": False, "error": reason}

            self._active_purchases.add(opportunity.gift_id)

        purchase_record = await self.gift_repo.create_purchase_record({
            "gift_id": opportunity.gift_id,
            "collection_id": opportunity.collection_id,
            "account_name": account_name,
            "purchase_price_ton": opportunity.current_price_ton,
            "floor_price_at_purchase": opportunity.floor_price_ton,
            "avg_price_at_purchase": opportunity.avg_price_ton,
            "discount_percent": opportunity.discount_vs_floor,
            "status": "pending",
        })

        try:
            result = await self._send_purchase_transaction(
                account_name=account_name,
                opportunity=opportunity,
                purchase_id=purchase_record.id,
            )

            if result["success"]:
                await self.gift_repo.update_purchase_record(purchase_record.id, {
                    "status": "success",
                    "transaction_hash": result.get("tx_hash"),
                })
                await self.gift_repo.update_daily_limit(account_name, opportunity.current_price_ton)
                logger.success(
                    f"Purchase successful: {opportunity.gift_name} at {format_ton(opportunity.current_price_ton)} "
                    f"(discount: {opportunity.discount_vs_floor:.1f}%)"
                )
            else:
                await self.gift_repo.update_purchase_record(purchase_record.id, {
                    "status": "failed",
                    "error_message": result.get("error"),
                })
                logger.error(f"Purchase failed: {opportunity.gift_name} — {result.get('error')}")

            return {**result, "purchase_id": purchase_record.id}

        except Exception as e:
            await self.gift_repo.update_purchase_record(purchase_record.id, {
                "status": "error",
                "error_message": str(e),
            })
            logger.error(f"Purchase exception for {opportunity.gift_id}: {e}")
            return {"success": False, "error": str(e), "purchase_id": purchase_record.id}
        finally:
            self._active_purchases.discard(opportunity.gift_id)

    @retry_async(max_attempts=2, wait_min=1, wait_max=5)
    async def _send_purchase_transaction(
        self, account_name: str, opportunity: TradeOpportunity, purchase_id: int
    ) -> Dict[str, Any]:
        client = self._clients.get(account_name)
        if not client:
            return {"success": False, "error": f"No active session for account '{account_name}'. Run auth first."}

        if not self.settings.trading.auto_confirm:
            logger.info(
                f"[DRY RUN] Would buy: {opportunity.gift_name} @ "
                f"{format_ton(opportunity.current_price_ton)} via {account_name}"
            )
            return {"success": True, "tx_hash": f"dry_run_{purchase_id}", "dry_run": True}

        try:
            result = await self._fragment_buy(client, opportunity)
            return result
        except Exception as e:
            if HAS_PYROGRAM:
                from pyrogram.errors import FloodWait, RPCError
                if isinstance(e, FloodWait):
                    logger.warning(f"FloodWait {e.value}s on account {account_name}")
                    await asyncio.sleep(e.value)
                    return {"success": False, "error": f"FloodWait: {e.value}s"}
                if isinstance(e, RPCError):
                    return {"success": False, "error": f"Telegram RPC error: {e}"}
            return {"success": False, "error": str(e)}

    async def _fragment_buy(self, client: Any, opportunity: TradeOpportunity) -> Dict[str, Any]:
        try:
            msg = await client.send_message(
                "@fragment",
                f"/buy {opportunity.gift_id}",
            )
            await asyncio.sleep(3)
            async for message in client.get_chat_history("@fragment", limit=5):
                if message.reply_markup:
                    for row in message.reply_markup.inline_keyboard:
                        for btn in row:
                            if any(kw in btn.text.lower() for kw in ("confirm", "buy", "purchase")):
                                await message.click(btn.text)
                                return {"success": True, "tx_hash": f"fragment_{msg.id}"}
            return {"success": False, "error": "No confirmation button found in @fragment"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_active_purchases(self) -> set:
        return self._active_purchases.copy()

    def get_client_count(self) -> int:
        return len(self._clients)
