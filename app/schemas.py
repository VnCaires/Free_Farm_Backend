from datetime import datetime

from pydantic import BaseModel, Field


class PlayerCreate(BaseModel):
    username: str
    password: str


class PlayerLogin(BaseModel):
    username: str
    password: str


class WalletDepositRequest(BaseModel):
    amount: float = Field(gt=0)


class WalletTransactionResponse(BaseModel):
    id: int
    transaction_type: str
    amount: float
    created_at: datetime

    class Config:
        from_attributes = True


class InventoryResponse(BaseModel):
    id: int
    player_id: int
    seeds: int
    water: int
    fertilizer: int

    class Config:
        from_attributes = True


class PlayerResponse(BaseModel):
    id: int
    username: str
    balance: float

    class Config:
        from_attributes = True
