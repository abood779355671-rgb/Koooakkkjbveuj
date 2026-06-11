#!/usr/bin/env python3
"""
Telegram Gift Monitor
Real-time monitoring and auto-buying system for Telegram Collectible Gifts
"""

import asyncio
import signal
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import click
from src.config import load_settings
from src.utils.logger import setup_logger
from loguru import logger


def _setup(config: str):
    settings = load_settings(config)
    setup_logger(
        log_level=settings.logging.level,
        log_file=settings.logging.file,
        max_size=f"{settings.logging.max_file_size_mb} MB",
        backup_count=settings.logging.backup_count,
        console_output=settings.logging.console_output,
    )
    Path("data").mkdir(exist_ok=True)
    Path("logs").mkdir(exist_ok=True)
    Path("sessions").mkdir(exist_ok=True)
    return settings


@click.group()
def cli():
    """🎁 Telegram Gift Monitor CLI"""
    pass


@cli.command()
@click.option("--config", default="settings.json", help="Path to settings file")
@click.option("--dry-run", is_flag=True, help="Dry-run mode — no actual purchases")
@click.option("--monitor-only", is_flag=True, help="Monitor only, trading disabled")
def start(config: str, dry_run: bool, monitor_only: bool):
    """Start the gift monitor"""
    settings = _setup(config)

    if dry_run:
        settings.trading.auto_confirm = False
        logger.info("DRY RUN mode — no actual purchases will be made")

    if monitor_only:
        settings.trading.enabled = False
        logger.info("MONITOR ONLY mode — trading disabled")

    asyncio.run(_run_manager(settings))


@cli.command()
@click.option("--config", default="settings.json", help="Path to settings file")
@click.option("--account", default=None, help="Account name to authenticate")
def auth(config: str, account: str):
    """Authenticate a Telegram account interactively"""
    settings = _setup(config)

    async def run():
        try:
            from pyrogram import Client
        except ImportError:
            click.echo("❌ pyrogram not installed. Run: pip install pyrogram tgcrypto")
            return

        accounts = settings.telegram_accounts
        if account:
            accounts = [a for a in accounts if a.name == account]

        if not accounts:
            click.echo("❌ No accounts found in settings.json")
            return

        Path("sessions").mkdir(exist_ok=True)
        for acc in accounts:
            click.echo(f"\n🔐 Authenticating: {acc.name} ({acc.phone})")
            try:
                client = Client(
                    name=acc.session_name,
                    api_id=int(acc.api_id),
                    api_hash=acc.api_hash,
                    phone_number=acc.phone,
                    workdir=str(Path("sessions").absolute()),
                )
                await client.start()
                me = await client.get_me()
                click.echo(f"✅ Authenticated as: {me.first_name} (@{me.username})")
                await client.stop()
            except Exception as e:
                click.echo(f"❌ Auth failed for {acc.name}: {e}")

    asyncio.run(run())


@cli.command()
@click.option("--config", default="settings.json", help="Path to settings file")
@click.option("--strategy", default="underpriced", help="Strategy name")
def backtest(config: str, strategy: str):
    """Run backtesting on historical data"""
    settings = _setup(config)

    async def run():
        from src.database.operations import Database
        from src.analytics.backtesting import Backtester

        db = Database(settings.database)
        await db.initialize()
        backtester = Backtester(
            db=db,
            backtest_config=settings.backtesting,
            trading_config=settings.trading,
            analysis_config=settings.analysis,
        )
        result = await backtester.run(strategy_name=strategy)

        profit_sign = "+" if result.total_profit >= 0 else ""
        click.echo(f"\n{'='*50}")
        click.echo(f"BACKTEST: {result.strategy_name.upper()}")
        click.echo(f"{'='*50}")
        click.echo(f"Period:       {result.start_date.date()} → {result.end_date.date()}")
        click.echo(f"Capital:      {result.initial_capital:.2f} → {result.final_capital:.2f} TON")
        click.echo(f"Profit:       {profit_sign}{result.total_profit:.4f} TON ({profit_sign}{result.total_profit_percent:.2f}%)")
        click.echo(f"Trades:       {result.total_trades} ({result.win_count}W/{result.loss_count}L)")
        click.echo(f"Win Rate:     {result.win_rate:.1f}%")
        click.echo(f"Max Drawdown: {result.max_drawdown:.2f}%")
        click.echo(f"Sharpe:       {result.sharpe_ratio:.2f}")
        click.echo(f"Best Trade:   +{result.best_trade:.4f} TON")
        click.echo(f"Worst Trade:  {result.worst_trade:.4f} TON")
        click.echo(f"{'='*50}\n")
        await db.close()

    asyncio.run(run())


@cli.command()
@click.option("--config", default="settings.json", help="Path to settings file")
@click.option("--days", default=30, help="Number of days to show")
def stats(config: str, days: int):
    """Show P&L statistics"""
    settings = _setup(config)

    async def run():
        from src.database.operations import Database
        from src.analytics.statistics import StatisticsEngine

        db = Database(settings.database)
        await db.initialize()
        engine = StatisticsEngine(db)
        summary = await engine.get_pnl_summary(days=days)
        report = await engine.format_pnl_report(summary)
        click.echo(report)

        accounts = await engine.get_account_performance()
        if accounts:
            click.echo("\nAccount Performance:")
            click.echo(f"{'Account':<20} {'Purchases':<12} {'Spent':>10} {'Profit':>10} {'ROI':>10}")
            click.echo("-" * 64)
            for a in accounts:
                sign = "+" if a["roi_percent"] >= 0 else ""
                click.echo(
                    f"{a['account']:<20} {a['purchases']:<12} "
                    f"{a['spent_ton']:>10.4f} {a['profit_ton']:>10.4f} "
                    f"{sign}{a['roi_percent']:>9.2f}%"
                )
        await db.close()

    asyncio.run(run())


@cli.command("validate-config")
@click.option("--config", default="settings.json", help="Path to settings file")
def validate_config(config: str):
    """Validate settings file"""
    try:
        settings = load_settings(config)
        click.echo(f"✅ Config valid: {config}")
        click.echo(f"   Accounts:       {len(settings.telegram_accounts)}")
        click.echo(f"   API IDs:        {[a.api_id for a in settings.telegram_accounts]}")
        click.echo(f"   Trading:        {'ENABLED' if settings.trading.enabled else 'DISABLED'}")
        click.echo(f"   Auto Confirm:   {settings.trading.auto_confirm}")
        click.echo(f"   Database:       {settings.database.type}")
        click.echo(f"   API Port:       {settings.api.port}")
        click.echo(f"   Threshold:      {settings.trading.underpriced_threshold_percent}%")
        click.echo(f"   Daily Limit:    {settings.trading.max_daily_spend_ton} TON")
        bot_ok = bool(settings.notification_bot.bot_token and
                      settings.notification_bot.bot_token != "YOUR_BOT_TOKEN")
        chat_ok = bool(settings.notification_bot.chat_id and
                       settings.notification_bot.chat_id != "YOUR_CHAT_ID")
        click.echo(f"   Bot Token:      {'✅ set' if bot_ok else '⚠️  not set'}")
        click.echo(f"   Chat ID:        {'✅ set' if chat_ok else '⚠️  not set (notifications disabled)'}")
    except Exception as e:
        click.echo(f"❌ Config error: {e}")
        sys.exit(1)


async def _run_manager(settings):
    from src.core.gift_manager import GiftManager

    manager = GiftManager(settings)
    loop = asyncio.get_event_loop()

    def shutdown():
        logger.info("Shutdown signal received — stopping...")
        loop.create_task(manager.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown)
        except NotImplementedError:
            signal.signal(sig, lambda s, f: loop.create_task(manager.stop()))

    try:
        await manager.initialize()
        await manager.start()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
    finally:
        await manager.stop()


if __name__ == "__main__":
    cli()
