import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
from loguru import logger
from sqlalchemy import select, and_

from ..database.operations import Database
from ..database.models import SaleRecord, PriceHistory, Gift
from ..config import BacktestingConfig, TradingConfig, AnalysisConfig
from ..utils.helpers import safe_divide, calculate_discount_percent, format_ton


@dataclass
class BacktestTrade:
    gift_id: str
    collection_id: str
    buy_price: float
    buy_date: datetime
    sell_price: Optional[float] = None
    sell_date: Optional[datetime] = None
    profit: float = 0.0
    profit_percent: float = 0.0
    floor_at_buy: Optional[float] = None
    discount_at_buy: float = 0.0
    status: str = "open"


@dataclass
class BacktestResult:
    strategy_name: str
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: float
    total_profit: float
    total_profit_percent: float
    total_trades: int
    win_count: int
    loss_count: int
    win_rate: float
    max_drawdown: float
    sharpe_ratio: float
    avg_hold_hours: float
    best_trade: float
    worst_trade: float
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: List[Dict] = field(default_factory=list)


class Backtester:
    def __init__(
        self,
        db: Database,
        backtest_config: BacktestingConfig,
        trading_config: TradingConfig,
        analysis_config: AnalysisConfig,
    ):
        self.db = db
        self.config = backtest_config
        self.trading = trading_config
        self.analysis = analysis_config

    async def run(self, strategy_name: str = "underpriced") -> BacktestResult:
        logger.info(f"Starting backtest: {strategy_name}")

        start_dt = datetime.fromisoformat(self.config.start_date).replace(tzinfo=timezone.utc)
        end_dt = datetime.fromisoformat(self.config.end_date).replace(tzinfo=timezone.utc)

        sales = await self._load_historical_sales(start_dt, end_dt)
        logger.info(f"Loaded {len(sales)} historical sales for backtesting")

        capital = self.config.initial_capital_ton
        trades: List[BacktestTrade] = []
        equity_curve = [{"date": start_dt.isoformat(), "capital": capital, "trades": 0}]

        collections = list(set(s.collection_id for s in sales))
        sales_by_date = sorted(sales, key=lambda s: s.sold_at)

        for i, sale in enumerate(sales_by_date):
            collection_id = sale.collection_id
            price = sale.price_ton

            prior_sales = [
                s for s in sales_by_date[:i]
                if s.collection_id == collection_id
            ]
            if len(prior_sales) < self.trading.require_min_sales_count:
                continue

            floor = self._calculate_floor(prior_sales)
            avg = self._calculate_avg(prior_sales, days=7, reference_date=sale.sold_at)
            last10_avg = self._calculate_last_n_avg(prior_sales, n=10)

            if not floor or not avg:
                continue

            discount = calculate_discount_percent(price, floor)
            if discount < self.trading.underpriced_threshold_percent:
                continue

            if price > self.trading.max_single_purchase_ton:
                continue
            if price < self.trading.min_floor_price_ton:
                continue

            commission = price * (self.config.commission_percent / 100)
            total_cost = price + commission

            if total_cost > capital:
                continue

            if self.config.simulate_slippage:
                actual_buy_price = price * (1 + 0.005)
            else:
                actual_buy_price = price

            capital -= actual_buy_price

            future_sales = [
                s for s in sales_by_date[i+1:]
                if s.collection_id == collection_id and s.sold_at > sale.sold_at
            ]

            sell_price = None
            sell_date = None
            if future_sales:
                target_sell = future_sales[0]
                sell_price = target_sell.price_ton
                sell_date = target_sell.sold_at
                sell_commission = sell_price * (self.config.commission_percent / 100)
                net_sell = sell_price - sell_commission
                capital += net_sell

            profit = (sell_price - actual_buy_price) if sell_price else 0.0
            profit_pct = calculate_discount_percent(actual_buy_price, sell_price) * -1 if sell_price else 0.0

            trade = BacktestTrade(
                gift_id=sale.gift_id,
                collection_id=collection_id,
                buy_price=actual_buy_price,
                buy_date=sale.sold_at,
                sell_price=sell_price,
                sell_date=sell_date,
                profit=profit,
                profit_percent=profit_pct,
                floor_at_buy=floor,
                discount_at_buy=discount,
                status="closed" if sell_price else "open",
            )
            trades.append(trade)

            equity_curve.append({
                "date": sale.sold_at.isoformat(),
                "capital": round(capital, 4),
                "trades": len(trades),
            })

        closed_trades = [t for t in trades if t.status == "closed"]
        profits = [t.profit for t in closed_trades]
        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p <= 0]

        hold_hours = []
        for t in closed_trades:
            if t.sell_date and t.buy_date:
                hold_hours.append((t.sell_date - t.buy_date).total_seconds() / 3600)

        max_drawdown = self._calculate_max_drawdown(equity_curve)
        sharpe = self._calculate_sharpe_ratio(equity_curve, self.config.initial_capital_ton)

        result = BacktestResult(
            strategy_name=strategy_name,
            start_date=start_dt,
            end_date=end_dt,
            initial_capital=self.config.initial_capital_ton,
            final_capital=capital,
            total_profit=capital - self.config.initial_capital_ton,
            total_profit_percent=safe_divide(
                capital - self.config.initial_capital_ton,
                self.config.initial_capital_ton
            ) * 100,
            total_trades=len(trades),
            win_count=len(wins),
            loss_count=len(losses),
            win_rate=safe_divide(len(wins), max(len(closed_trades), 1)) * 100,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe,
            avg_hold_hours=sum(hold_hours) / len(hold_hours) if hold_hours else 0,
            best_trade=max(profits) if profits else 0,
            worst_trade=min(profits) if profits else 0,
            trades=trades,
            equity_curve=equity_curve,
        )

        logger.info(self._format_result(result))
        return result

    async def _load_historical_sales(self, start: datetime, end: datetime) -> List[SaleRecord]:
        async with self.db.session() as session:
            result = await session.execute(
                select(SaleRecord).where(
                    and_(SaleRecord.sold_at >= start, SaleRecord.sold_at <= end)
                ).order_by(SaleRecord.sold_at)
            )
            return result.scalars().all()

    def _calculate_floor(self, sales: List[SaleRecord]) -> Optional[float]:
        prices = [s.price_ton for s in sales if s.price_ton > 0]
        return min(prices) if prices else None

    def _calculate_avg(
        self, sales: List[SaleRecord], days: int, reference_date: datetime
    ) -> Optional[float]:
        cutoff = reference_date - timedelta(days=days)
        recent = [s.price_ton for s in sales if s.sold_at >= cutoff and s.price_ton > 0]
        return sum(recent) / len(recent) if recent else None

    def _calculate_last_n_avg(self, sales: List[SaleRecord], n: int = 10) -> Optional[float]:
        if not sales:
            return None
        last_n = sorted(sales, key=lambda s: s.sold_at, reverse=True)[:n]
        prices = [s.price_ton for s in last_n if s.price_ton > 0]
        return sum(prices) / len(prices) if prices else None

    def _calculate_max_drawdown(self, equity_curve: List[Dict]) -> float:
        if not equity_curve:
            return 0.0
        capitals = [e["capital"] for e in equity_curve]
        peak = capitals[0]
        max_dd = 0.0
        for c in capitals:
            if c > peak:
                peak = c
            dd = (peak - c) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        return max_dd * 100

    def _calculate_sharpe_ratio(self, equity_curve: List[Dict], initial: float) -> float:
        if len(equity_curve) < 2:
            return 0.0
        returns = []
        for i in range(1, len(equity_curve)):
            prev = equity_curve[i-1]["capital"]
            curr = equity_curve[i]["capital"]
            if prev > 0:
                returns.append((curr - prev) / prev)

        if not returns:
            return 0.0

        import statistics as stat
        avg_return = stat.mean(returns)
        std_return = stat.stdev(returns) if len(returns) > 1 else 0.001
        risk_free_rate = 0.0
        return safe_divide(avg_return - risk_free_rate, std_return) * (252 ** 0.5)

    def _format_result(self, r: BacktestResult) -> str:
        profit_icon = "📈" if r.total_profit >= 0 else "📉"
        return (
            f"\n{'='*45}\n"
            f"🔬 BACKTEST RESULTS: {r.strategy_name.upper()}\n"
            f"{'='*45}\n"
            f"Period:          {r.start_date.date()} → {r.end_date.date()}\n"
            f"Initial Capital: {format_ton(r.initial_capital)}\n"
            f"Final Capital:   {format_ton(r.final_capital)}\n"
            f"{profit_icon} Total Profit: {format_ton(r.total_profit)} ({r.total_profit_percent:+.2f}%)\n"
            f"{'─'*45}\n"
            f"Total Trades:    {r.total_trades}\n"
            f"Win/Loss:        {r.win_count}W / {r.loss_count}L\n"
            f"Win Rate:        {r.win_rate:.1f}%\n"
            f"Best Trade:      {format_ton(r.best_trade)}\n"
            f"Worst Trade:     {format_ton(r.worst_trade)}\n"
            f"Avg Hold Time:   {r.avg_hold_hours:.1f}h\n"
            f"Max Drawdown:    {r.max_drawdown:.2f}%\n"
            f"Sharpe Ratio:    {r.sharpe_ratio:.2f}\n"
            f"{'='*45}"
        )

    async def run_multiple_strategies(self) -> Dict[str, BacktestResult]:
        strategies = {}
        original_threshold = self.trading.underpriced_threshold_percent

        for threshold in [10, 15, 20, 25, 30]:
            self.trading.underpriced_threshold_percent = threshold
            result = await self.run(strategy_name=f"underpriced_{threshold}pct")
            strategies[f"threshold_{threshold}"] = result

        self.trading.underpriced_threshold_percent = original_threshold
        return strategies
