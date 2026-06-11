import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from loguru import logger


@dataclass
class TelegramAccount:
    name: str
    api_id: str
    api_hash: str
    phone: str
    session_name: str
    enabled: bool = True


@dataclass
class NotificationBot:
    bot_token: str
    chat_id: str
    enabled: bool = True


@dataclass
class DatabaseConfig:
    type: str = "sqlite"
    sqlite_path: str = "data/gifts.db"
    postgres_url: str = ""


@dataclass
class MonitoringConfig:
    scan_interval_seconds: int = 5
    market_refresh_interval_seconds: int = 30
    max_concurrent_requests: int = 10
    gift_types: List[str] = field(default_factory=lambda: ["collectible", "nft"])
    track_collections: List[str] = field(default_factory=list)


@dataclass
class TradingConfig:
    enabled: bool = False
    underpriced_threshold_percent: float = 20.0
    max_daily_spend_ton: float = 100.0
    max_daily_purchases: int = 20
    max_single_purchase_ton: float = 10.0
    min_floor_price_ton: float = 0.1
    max_floor_price_ton: float = 1000.0
    duplicate_protection_hours: int = 24
    require_min_sales_count: int = 3
    strategy: str = "underpriced"
    slippage_tolerance_percent: float = 2.0
    auto_confirm: bool = False


@dataclass
class AnalysisConfig:
    floor_price_window_sales: int = 10
    historical_avg_window_days: int = 7
    rarity_weight: float = 0.3
    price_weight: float = 0.5
    volume_weight: float = 0.2
    min_rarity_score: float = 0.0
    max_rarity_score: float = 1.0


@dataclass
class BacktestingConfig:
    start_date: str = "2024-01-01"
    end_date: str = "2024-12-31"
    initial_capital_ton: float = 1000.0
    commission_percent: float = 0.5
    simulate_slippage: bool = True


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "logs/system.log"
    max_file_size_mb: int = 100
    backup_count: int = 5
    console_output: bool = True


@dataclass
class APIConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    enabled: bool = True
    secret_key: str = "change_me"


@dataclass
class Settings:
    telegram_accounts: List[TelegramAccount] = field(default_factory=list)
    notification_bot: NotificationBot = field(default_factory=lambda: NotificationBot("", ""))
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    backtesting: BacktestingConfig = field(default_factory=BacktestingConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    api: APIConfig = field(default_factory=APIConfig)


def load_settings(path: str = "settings.json") -> Settings:
    config_path = Path(path)
    if not config_path.exists():
        logger.warning(f"Settings file not found at {path}, using defaults")
        return Settings()

    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    accounts = [TelegramAccount(**acc) for acc in data.get("telegram_accounts", [])]
    notif_data = data.get("notification_bot", {})
    notification_bot = NotificationBot(**notif_data) if notif_data else NotificationBot("", "")

    settings = Settings(
        telegram_accounts=accounts,
        notification_bot=notification_bot,
        database=DatabaseConfig(**data.get("database", {})),
        monitoring=MonitoringConfig(**data.get("monitoring", {})),
        trading=TradingConfig(**data.get("trading", {})),
        analysis=AnalysisConfig(**data.get("analysis", {})),
        backtesting=BacktestingConfig(**data.get("backtesting", {})),
        logging=LoggingConfig(**data.get("logging", {})),
        api=APIConfig(**data.get("api", {})),
    )

    logger.info(f"Settings loaded from {path}")
    logger.info(f"Accounts: {len(settings.telegram_accounts)}, Trading: {'ENABLED' if settings.trading.enabled else 'DISABLED'}")
    return settings


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings
