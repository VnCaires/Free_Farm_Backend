from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String)
    balance: Mapped[float] = mapped_column(Float, default=100.0)
    inventory: Mapped["Inventory"] = relationship(back_populates="player", uselist=False)
    wallet_transactions: Mapped[list["WalletTransaction"]] = relationship(back_populates="player")


class Inventory(Base):
    __tablename__ = "inventories"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), unique=True, index=True)
    seeds: Mapped[int] = mapped_column(Integer, default=10)
    water: Mapped[int] = mapped_column(Integer, default=5)
    fertilizer: Mapped[int] = mapped_column(Integer, default=3)
    player: Mapped[Player] = relationship(back_populates="inventory")


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    transaction_type: Mapped[str] = mapped_column(String, index=True)
    amount: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    player: Mapped[Player] = relationship(back_populates="wallet_transactions")
