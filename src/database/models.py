from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime,
    Text, ForeignKey, Index, UniqueConstraint, JSON
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def utc_now():
    return datetime.now(timezone.utc)


class GiftCollection(Base):
    __tablename__ = "gift_collections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    collection_id = Column(String(128), unique=True, nullable=False, index=True)
    name = Column(String(256), nullable=False)
    gift_type = Column(String(32), nullable=False, default="collectible")
    total_supply = Column(Integer, nullable=True)
    description = Column(Text, nullable=True)
    thumbnail_url = Column(String(512), nullable=True)
    floor_price_ton = Column(Float, nullable=True)
    last_floor_update = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    gifts = relationship("Gift", back_populates="collection", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<GiftCollection {self.name} (floor={self.floor_price_ton} TON)>"


class Gift(Base):
    __tablename__ = "gifts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    gift_id = Column(String(128), unique=True, nullable=False, index=True)
    collection_id = Column(String(128), ForeignKey("gift_collections.collection_id"), nullable=False)
    gift_number = Column(Integer, nullable=True)
    name = Column(String(256), nullable=False)
    owner_id = Column(String(64), nullable=True)
    current_price_ton = Column(Float, nullable=True)
    is_for_sale = Column(Boolean, default=False)
    rarity_score = Column(Float, nullable=True)
    rarity_rank = Column(Integer, nullable=True)
    supply = Column(Integer, nullable=True)
    attributes_json = Column(JSON, nullable=True)
    thumbnail_url = Column(String(512), nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    first_seen_at = Column(DateTime(timezone=True), default=utc_now)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    collection = relationship("GiftCollection", back_populates="gifts")
    sales = relationship("SaleRecord", back_populates="gift", cascade="all, delete-orphan")
    price_history = relationship("PriceHistory", back_populates="gift", cascade="all, delete-orphan")
    purchases = relationship("PurchaseRecord", back_populates="gift")

    __table_args__ = (
        Index("idx_gift_collection_sale", "collection_id", "is_for_sale"),
        Index("idx_gift_price", "current_price_ton"),
    )

    def __repr__(self):
        return f"<Gift {self.name} #{self.gift_number} ({self.current_price_ton} TON)>"


class SaleRecord(Base):
    __tablename__ = "sale_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    gift_id = Column(String(128), ForeignKey("gifts.gift_id"), nullable=False)
    collection_id = Column(String(128), nullable=False, index=True)
    seller_id = Column(String(64), nullable=True)
    buyer_id = Column(String(64), nullable=True)
    price_ton = Column(Float, nullable=False)
    transaction_hash = Column(String(256), nullable=True, unique=True)
    sold_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    gift = relationship("Gift", back_populates="sales")

    __table_args__ = (
        Index("idx_sale_collection_time", "collection_id", "sold_at"),
        Index("idx_sale_price", "price_ton"),
    )

    def __repr__(self):
        return f"<SaleRecord gift={self.gift_id} price={self.price_ton} TON>"


class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    gift_id = Column(String(128), ForeignKey("gifts.gift_id"), nullable=False)
    price_ton = Column(Float, nullable=False)
    is_for_sale = Column(Boolean, default=False)
    recorded_at = Column(DateTime(timezone=True), default=utc_now)

    gift = relationship("Gift", back_populates="price_history")

    __table_args__ = (
        Index("idx_price_history_gift_time", "gift_id", "recorded_at"),
    )


class PurchaseRecord(Base):
    __tablename__ = "purchase_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    gift_id = Column(String(128), ForeignKey("gifts.gift_id"), nullable=False)
    collection_id = Column(String(128), nullable=False)
    account_name = Column(String(128), nullable=False)
    purchase_price_ton = Column(Float, nullable=False)
    floor_price_at_purchase = Column(Float, nullable=True)
    avg_price_at_purchase = Column(Float, nullable=True)
    discount_percent = Column(Float, nullable=True)
    status = Column(String(32), nullable=False, default="pending")
    transaction_hash = Column(String(256), nullable=True)
    error_message = Column(Text, nullable=True)
    purchased_at = Column(DateTime(timezone=True), default=utc_now)
    sell_price_ton = Column(Float, nullable=True)
    sold_at = Column(DateTime(timezone=True), nullable=True)
    profit_ton = Column(Float, nullable=True)
    profit_percent = Column(Float, nullable=True)

    gift = relationship("Gift", back_populates="purchases")

    __table_args__ = (
        Index("idx_purchase_account_time", "account_name", "purchased_at"),
        Index("idx_purchase_status", "status"),
    )

    def __repr__(self):
        return f"<Purchase gift={self.gift_id} price={self.purchase_price_ton} TON status={self.status}>"


class DailyLimit(Base):
    __tablename__ = "daily_limits"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_name = Column(String(128), nullable=False)
    date = Column(String(10), nullable=False)
    total_spent_ton = Column(Float, default=0.0)
    purchase_count = Column(Integer, default=0)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    __table_args__ = (
        UniqueConstraint("account_name", "date", name="uq_daily_limit_account_date"),
    )


class OpportunityLog(Base):
    __tablename__ = "opportunity_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    gift_id = Column(String(128), nullable=False)
    collection_id = Column(String(128), nullable=False)
    current_price_ton = Column(Float, nullable=False)
    floor_price_ton = Column(Float, nullable=True)
    avg_price_ton = Column(Float, nullable=True)
    discount_percent = Column(Float, nullable=False)
    rarity_score = Column(Float, nullable=True)
    action_taken = Column(String(32), default="notified")
    details_json = Column(JSON, nullable=True)
    discovered_at = Column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        Index("idx_opportunity_time", "discovered_at"),
        Index("idx_opportunity_discount", "discount_percent"),
    )


class MarketStats(Base):
    __tablename__ = "market_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    collection_id = Column(String(128), nullable=False, index=True)
    floor_price_ton = Column(Float, nullable=True)
    avg_price_ton = Column(Float, nullable=True)
    volume_24h_ton = Column(Float, nullable=True)
    sales_count_24h = Column(Integer, nullable=True)
    listings_count = Column(Integer, nullable=True)
    recorded_at = Column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        Index("idx_market_stats_collection_time", "collection_id", "recorded_at"),
    )
