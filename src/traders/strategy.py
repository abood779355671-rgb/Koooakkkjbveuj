from dataclasses import dataclass
from typing import Optional, List
from loguru import logger

from ..config import Settings, TradingConfig, AnalysisConfig
from ..database.operations import GiftRepository
from ..utils.helpers import calculate_discount_percent, safe_divide


@dataclass
class TradeOpportunity:
    gift_id: str
    collection_id: str
    gift_name: str
    current_price_ton: float
    floor_price_ton: Optional[float]
    avg_price_ton: Optional[float]
    last_10_avg_ton: Optional[float]
    rarity_score: Optional[float]
    rarity_rank: Optional[int]
    supply: Optional[int]
    discount_vs_floor: float
    discount_vs_avg: float
    discount_vs_last10: float
    opportunity_score: float
    should_buy: bool
    reason: str


class TradingStrategy:
    def __init__(self, settings: Settings, gift_repo: GiftRepository):
        self.settings = settings
        self.gift_repo = gift_repo
        self.trading: TradingConfig = settings.trading
        self.analysis: AnalysisConfig = settings.analysis

    async def evaluate_gift(self, gift_data: dict) -> Optional[TradeOpportunity]:
        gift_id = gift_data.get("gift_id")
        collection_id = gift_data.get("collection_id")
        current_price = gift_data.get("current_price_ton")

        if not all([gift_id, collection_id, current_price]):
            return None

        if current_price < self.trading.min_floor_price_ton:
            return None
        if current_price > self.trading.max_floor_price_ton:
            return None
        if current_price > self.trading.max_single_purchase_ton:
            return None

        floor_price = await self.gift_repo.get_floor_price(collection_id)
        avg_price = await self.gift_repo.get_avg_sale_price(
            collection_id, self.analysis.historical_avg_window_days
        )
        last10_avg = await self.gift_repo.get_last_n_sales_avg(
            collection_id, self.analysis.floor_price_window_sales
        )

        recent_sales = await self.gift_repo.get_recent_sales(collection_id, 10)
        if len(recent_sales) < self.trading.require_min_sales_count:
            return None

        discount_vs_floor = calculate_discount_percent(current_price, floor_price) if floor_price else 0.0
        discount_vs_avg = calculate_discount_percent(current_price, avg_price) if avg_price else 0.0
        discount_vs_last10 = calculate_discount_percent(current_price, last10_avg) if last10_avg else 0.0

        opportunity_score = self._calculate_score(
            current_price=current_price,
            floor_price=floor_price,
            avg_price=avg_price,
            last10_avg=last10_avg,
            rarity_score=gift_data.get("rarity_score"),
            discount_vs_floor=discount_vs_floor,
            discount_vs_avg=discount_vs_avg,
        )

        threshold = self.trading.underpriced_threshold_percent
        should_buy = (
            self.trading.enabled
            and discount_vs_floor >= threshold
            and discount_vs_avg >= (threshold * 0.8)
        )

        if should_buy:
            reason = (
                f"Underpriced by {discount_vs_floor:.1f}% vs floor, "
                f"{discount_vs_avg:.1f}% vs avg, "
                f"score={opportunity_score:.2f}"
            )
        else:
            reason = f"Below threshold (floor discount={discount_vs_floor:.1f}%, need {threshold}%)"

        return TradeOpportunity(
            gift_id=gift_id,
            collection_id=collection_id,
            gift_name=gift_data.get("name", "Unknown"),
            current_price_ton=current_price,
            floor_price_ton=floor_price,
            avg_price_ton=avg_price,
            last_10_avg_ton=last10_avg,
            rarity_score=gift_data.get("rarity_score"),
            rarity_rank=gift_data.get("rarity_rank"),
            supply=gift_data.get("supply"),
            discount_vs_floor=discount_vs_floor,
            discount_vs_avg=discount_vs_avg,
            discount_vs_last10=discount_vs_last10,
            opportunity_score=opportunity_score,
            should_buy=should_buy,
            reason=reason,
        )

    def _calculate_score(
        self,
        current_price: float,
        floor_price: Optional[float],
        avg_price: Optional[float],
        last10_avg: Optional[float],
        rarity_score: Optional[float],
        discount_vs_floor: float,
        discount_vs_avg: float,
    ) -> float:
        price_score = 0.0
        if floor_price and floor_price > 0:
            price_score = min(discount_vs_floor / 100, 1.0)

        rarity_component = 0.0
        if rarity_score is not None:
            r = max(self.analysis.min_rarity_score, min(self.analysis.max_rarity_score, rarity_score))
            rarity_component = safe_divide(r - self.analysis.min_rarity_score,
                                           self.analysis.max_rarity_score - self.analysis.min_rarity_score)

        volume_score = min(discount_vs_avg / 100, 1.0) if avg_price else 0.0

        score = (
            price_score * self.analysis.price_weight
            + rarity_component * self.analysis.rarity_weight
            + volume_score * self.analysis.volume_weight
        )
        return round(score, 4)

    async def evaluate_batch(self, gifts: List[dict]) -> List[TradeOpportunity]:
        opportunities = []
        for gift in gifts:
            try:
                opp = await self.evaluate_gift(gift)
                if opp:
                    opportunities.append(opp)
            except Exception as e:
                logger.error(f"Error evaluating gift {gift.get('gift_id')}: {e}")

        opportunities.sort(key=lambda x: x.opportunity_score, reverse=True)
        return opportunities
