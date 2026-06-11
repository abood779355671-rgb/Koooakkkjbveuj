import asyncio
import aiohttp
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from loguru import logger

from ..config import Settings
from ..database.operations import GiftRepository
from ..utils.helpers import retry_async, nano_to_ton


FRAGMENT_API_BASE = "https://fragment.com/api"
GETGEMS_API_BASE = "https://getgems.io/graphql"
TONSCAN_API = "https://tonscan.org/api/v3"


class GiftTracker:
    def __init__(self, settings: Settings, gift_repo: GiftRepository):
        self.settings = settings
        self.gift_repo = gift_repo
        self._session: Optional[aiohttp.ClientSession] = None
        self._known_collections: Dict[str, Dict] = {}

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; GiftMonitor/1.0)",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
            self._session = aiohttp.ClientSession(timeout=timeout, headers=headers)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    @retry_async(max_attempts=3, wait_min=1, wait_max=5)
    async def fetch_active_listings(self, collection_id: str) -> List[Dict[str, Any]]:
        gifts = []
        try:
            fragment_gifts = await self._fetch_from_fragment(collection_id)
            gifts.extend(fragment_gifts)
        except Exception as e:
            logger.warning(f"Fragment fetch failed for {collection_id}: {e}")

        try:
            getgems_gifts = await self._fetch_from_getgems(collection_id)
            gifts.extend(getgems_gifts)
        except Exception as e:
            logger.warning(f"GetGems fetch failed for {collection_id}: {e}")

        seen = set()
        unique_gifts = []
        for g in gifts:
            if g["gift_id"] not in seen:
                seen.add(g["gift_id"])
                unique_gifts.append(g)

        return unique_gifts

    async def _fetch_from_fragment(self, collection_id: str) -> List[Dict[str, Any]]:
        session = await self._get_session()
        url = f"{FRAGMENT_API_BASE}/collectibles"
        params = {
            "collection": collection_id,
            "sort": "price_asc",
            "limit": 100,
            "status": "on_sale",
        }

        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                raise Exception(f"Fragment API error: {resp.status}")
            data = await resp.json()

        gifts = []
        for item in data.get("items", []):
            gift = self._parse_fragment_gift(item, collection_id)
            if gift:
                gifts.append(gift)
        return gifts

    def _parse_fragment_gift(self, item: Dict, collection_id: str) -> Optional[Dict]:
        try:
            price_nano = item.get("price", 0)
            price_ton = nano_to_ton(price_nano) if price_nano else None

            return {
                "gift_id": f"fragment_{item.get('id', '')}",
                "collection_id": collection_id,
                "name": item.get("name", "Unknown"),
                "gift_number": item.get("number"),
                "current_price_ton": price_ton,
                "is_for_sale": True,
                "owner_id": item.get("owner_address"),
                "rarity_score": item.get("rarity_score"),
                "rarity_rank": item.get("rarity_rank"),
                "supply": item.get("supply"),
                "thumbnail_url": item.get("image"),
                "attributes_json": item.get("attributes", {}),
                "last_seen_at": datetime.now(timezone.utc),
            }
        except Exception as e:
            logger.error(f"Error parsing Fragment gift: {e}")
            return None

    async def _fetch_from_getgems(self, collection_id: str) -> List[Dict[str, Any]]:
        session = await self._get_session()
        query = """
        query GetNFTsByCollection($collectionAddress: String!, $first: Int!, $cursor: String) {
          nftItemsByCollection(
            collectionAddress: $collectionAddress
            first: $first
            after: $cursor
            filter: { saleStatus: ON_SALE }
            orderBy: { field: PRICE, direction: ASC }
          ) {
            edges {
              node {
                id
                name
                index
                imagePreview
                currentSale {
                  fullPrice
                }
                attributes {
                  trait_type
                  value
                }
                rarityRank
                rarityScore
                owner { address }
              }
            }
            pageInfo { hasNextPage endCursor }
          }
        }
        """
        variables = {"collectionAddress": collection_id, "first": 100}
        async with session.post(GETGEMS_API_BASE, json={"query": query, "variables": variables}) as resp:
            if resp.status != 200:
                raise Exception(f"GetGems API error: {resp.status}")
            data = await resp.json()

        gifts = []
        edges = data.get("data", {}).get("nftItemsByCollection", {}).get("edges", [])
        for edge in edges:
            node = edge.get("node", {})
            gift = self._parse_getgems_gift(node, collection_id)
            if gift:
                gifts.append(gift)
        return gifts

    def _parse_getgems_gift(self, node: Dict, collection_id: str) -> Optional[Dict]:
        try:
            sale = node.get("currentSale") or {}
            price_nano = sale.get("fullPrice", 0)
            price_ton = nano_to_ton(int(price_nano)) if price_nano else None

            return {
                "gift_id": f"gg_{node.get('id', '')}",
                "collection_id": collection_id,
                "name": node.get("name", "Unknown"),
                "gift_number": node.get("index"),
                "current_price_ton": price_ton,
                "is_for_sale": price_ton is not None,
                "owner_id": (node.get("owner") or {}).get("address"),
                "rarity_score": node.get("rarityScore"),
                "rarity_rank": node.get("rarityRank"),
                "thumbnail_url": node.get("imagePreview"),
                "attributes_json": node.get("attributes", []),
                "last_seen_at": datetime.now(timezone.utc),
            }
        except Exception as e:
            logger.error(f"Error parsing GetGems gift: {e}")
            return None

    @retry_async(max_attempts=2, wait_min=1, wait_max=3)
    async def fetch_sale_history(self, collection_id: str, gift_id: str) -> List[Dict]:
        session = await self._get_session()
        url = f"{TONSCAN_API}/nft/sales"
        params = {"collection": collection_id, "nft": gift_id, "limit": 20}

        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()

        sales = []
        for tx in data.get("transactions", []):
            try:
                sales.append({
                    "gift_id": gift_id,
                    "collection_id": collection_id,
                    "price_ton": nano_to_ton(int(tx.get("value", 0))),
                    "seller_id": tx.get("from"),
                    "buyer_id": tx.get("to"),
                    "transaction_hash": tx.get("hash"),
                    "sold_at": datetime.fromtimestamp(tx.get("utime", 0), tz=timezone.utc),
                })
            except Exception:
                pass
        return sales

    async def fetch_all_collection_ids(self) -> List[str]:
        session = await self._get_session()
        try:
            url = f"{FRAGMENT_API_BASE}/collections"
            async with session.get(url, params={"limit": 200, "type": "gift"}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return [c["id"] for c in data.get("collections", [])]
        except Exception as e:
            logger.warning(f"Could not fetch collection list: {e}")

        return list(self._known_collections.keys())

    async def fetch_collection_info(self, collection_id: str) -> Optional[Dict]:
        session = await self._get_session()
        try:
            url = f"{FRAGMENT_API_BASE}/collection/{collection_id}"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        "collection_id": collection_id,
                        "name": data.get("name", collection_id),
                        "gift_type": data.get("type", "collectible"),
                        "total_supply": data.get("total_supply"),
                        "description": data.get("description"),
                        "thumbnail_url": data.get("image"),
                    }
        except Exception as e:
            logger.error(f"Error fetching collection info for {collection_id}: {e}")
        return None
