import asyncio
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any, Optional
from functools import wraps
from tenacity import retry, stop_after_attempt, wait_exponential


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ton_to_nano(amount: float) -> int:
    return int(Decimal(str(amount)) * Decimal("1000000000"))


def nano_to_ton(amount: int) -> float:
    return float(Decimal(str(amount)) / Decimal("1000000000"))


def format_ton(amount: float, decimals: int = 4) -> str:
    return f"{amount:.{decimals}f} TON"


def format_percent(value: float) -> str:
    return f"{value:+.2f}%"


def calculate_discount_percent(current_price: float, reference_price: float) -> float:
    if reference_price <= 0:
        return 0.0
    return ((reference_price - current_price) / reference_price) * 100


def calculate_profit_percent(buy_price: float, sell_price: float) -> float:
    if buy_price <= 0:
        return 0.0
    return ((sell_price - buy_price) / buy_price) * 100


def generate_gift_id(collection_id: str, gift_number: int) -> str:
    raw = f"{collection_id}:{gift_number}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator == 0:
        return default
    return numerator / denominator


def truncate_float(value: float, decimals: int = 9) -> float:
    d = Decimal(str(value)).quantize(Decimal(10) ** -decimals, rounding=ROUND_DOWN)
    return float(d)


def retry_async(max_attempts: int = 3, wait_min: float = 1, wait_max: float = 10):
    def decorator(func):
        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=1, min=wait_min, max=wait_max),
            reraise=True
        )
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def chunk_list(lst: list, size: int) -> list:
    return [lst[i:i + size] for i in range(0, len(lst), size)]


def flatten(lst: list) -> list:
    return [item for sublist in lst for item in sublist]


def safe_json_loads(data: str, default: Any = None) -> Any:
    try:
        return json.loads(data)
    except (json.JSONDecodeError, TypeError):
        return default


def clamp(value: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(max_val, value))


class RateLimiter:
    def __init__(self, max_calls: int, period: float):
        self.max_calls = max_calls
        self.period = period
        self._calls = []
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = asyncio.get_event_loop().time()
            self._calls = [t for t in self._calls if now - t < self.period]
            if len(self._calls) >= self.max_calls:
                sleep_time = self.period - (now - self._calls[0])
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
            self._calls.append(asyncio.get_event_loop().time())


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, reset_timeout: float = 60):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = "closed"

    def record_success(self):
        self.failure_count = 0
        self.state = "closed"

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = asyncio.get_event_loop().time()
        if self.failure_count >= self.failure_threshold:
            self.state = "open"

    def is_open(self) -> bool:
        if self.state == "open":
            now = asyncio.get_event_loop().time()
            if self.last_failure_time and (now - self.last_failure_time) > self.reset_timeout:
                self.state = "half-open"
                return False
            return True
        return False
