"""
Database models for Cargo Telegram Bot
"""
from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, ForeignKey, Integer, String,
    Text, ARRAY, UniqueConstraint
)
from sqlalchemy.types import DECIMAL
from sqlalchemy.dialects.postgresql import BIGINT, JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class CargoStatus(PyEnum):
    """Yuk holati turlari"""
    PENDING = "pending"
    IN_TRANSIT = "in_transit"
    ARRIVED = "arrived"
    READY = "ready"
    DELIVERED = "delivered"


class Client(Base):
    """Mijozlar jadvali"""
    __tablename__ = "clients"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    telegram_id = Column(BIGINT, unique=True, nullable=True, index=True)
    phone_number = Column(String(20), unique=True, nullable=False, index=True)
    # "48392" (oddiy mijoz) yoki "MS48392" (alohida klient) — bot/utils/cargo_id_gen.py
    cargo_id = Column(String(10), unique=True, nullable=True, index=True)
    full_name = Column(String(255), nullable=True)
    language = Column(String(5), default="uz", nullable=False)
    # Agent (alohida klient) — mijoz kim nomidan ro'yxatga olingan.
    # NULL = oddiy mijoz. Qarang: bot/utils/agents.py
    agent_id = Column(
        BIGINT,
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by = Column(BIGINT, nullable=False)

    # Munosabat
    shipments = relationship("Shipment", back_populates="client", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Client(id={self.id}, cargo_id='{self.cargo_id}', phone='{self.phone_number}')>"


class Shipment(Base):
    """Yuklar jadvali"""
    __tablename__ = "shipments"

    id = Column(BIGINT, primary_key=True, autoincrement=True)
    client_id = Column(BIGINT, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    description = Column(Text, nullable=False)
    weight_kg = Column(DECIMAL(10, 2), nullable=True)
    cargo_weight_kg = Column(DECIMAL(10, 2), nullable=True)
    price = Column(DECIMAL(12, 2), nullable=True)
    currency = Column(String(5), nullable=True)
    photo_file_id = Column(Text, nullable=True)
    status = Column(
        Enum(CargoStatus, name="cargo_status", values_callable=lambda x: [e.value for e in x]),
        default=CargoStatus.PENDING,
        nullable=False,
        index=True,
    )
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(BIGINT, nullable=False)

    # Munosabat
    client = relationship("Client", back_populates="shipments")

    def __repr__(self):
        return f"<Shipment(id={self.id}, cargo_id='{self.client.cargo_id if self.client else None}', status='{self.status}')>"


class GroupCategory(Base):
    """Guruh kategoriyalari (masalan: Erkaklar kiyimi, Ayollar kiyimi)"""
    __tablename__ = "group_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name_uz = Column(String(255), nullable=False)
    name_ru = Column(String(255), nullable=False)
    name_tr = Column(String(255), nullable=False)
    emoji = Column(String(10), nullable=False, default="📂")
    is_active = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)

    groups = relationship("Group", back_populates="category", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<GroupCategory(id={self.id}, name_uz='{self.name_uz}')>"


class Group(Base):
    """Savdo guruhlari jadvali (kategoriya ichida)"""
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category_id = Column(Integer, ForeignKey("group_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    name_uz = Column(String(255), nullable=False)
    name_ru = Column(String(255), nullable=False)
    name_tr = Column(String(255), nullable=False)
    telegram_link = Column(Text, nullable=False)
    emoji = Column(String(10), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)

    category = relationship("GroupCategory", back_populates="groups")

    def __repr__(self):
        return f"<Group(id={self.id}, name_uz='{self.name_uz}', category_id={self.category_id})>"


class CompanyInfo(Base):
    """Kompaniya ma'lumotlari jadvali"""
    __tablename__ = "company_info"

    id = Column(Integer, primary_key=True, autoincrement=True)
    address_uz = Column(Text, nullable=False)
    address_ru = Column(Text, nullable=False)
    address_tr = Column(Text, nullable=False)
    address_cn = Column(Text, nullable=True)  # Xitoy manzili
    phone_numbers = Column(ARRAY(String), nullable=False)
    phone_numbers_cn = Column(ARRAY(String), nullable=True)  # Xitoy telefon raqamlari
    telegram_account = Column(String(255), nullable=False)
    working_hours = Column(String(255), nullable=False)

    def __repr__(self):
        return f"<CompanyInfo(id={self.id}, telegram_account='{self.telegram_account}')>"
