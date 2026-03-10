from datetime import datetime

from pydantic import BaseModel, Field, validator


class PlayerCreate(BaseModel):
    username: str
    email: str
    password: str

    @validator("email")
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Invalid email")
        return normalized


class PlayerLogin(BaseModel):
    username: str
    password: str


class WalletDepositRequest(BaseModel):
    amount: float = Field(gt=0)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class WalletTransactionResponse(BaseModel):
    id: int
    transaction_type: str
    amount: float
    created_at: datetime

    class Config:
        from_attributes = True


class InventoryAddItemRequest(BaseModel):
    item_code: str
    quantity: int = Field(gt=0)


class InventoryItemResponse(BaseModel):
    code: str
    name: str
    category: str
    quantity: int


class InventoryCategoryResponse(BaseModel):
    category: str
    items: list[InventoryItemResponse]


class InventoryResponse(BaseModel):
    id: int
    player_id: int
    capacity_limit: int
    total_quantity: int
    categories: list[InventoryCategoryResponse]


class LandPlotCreateRequest(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    soil_type: str = "loam"
    state: str = "empty"


class LandPlotStateUpdateRequest(BaseModel):
    state: str


class LandPlotResponse(BaseModel):
    id: int
    player_id: int
    x: int
    y: int
    soil_type: str
    state: str
    is_occupied: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class LandGridResponse(BaseModel):
    player_id: int
    total_plots: int
    plots: list[LandPlotResponse]


class PlayerResponse(BaseModel):
    id: int
    username: str
    email: str | None
    email_verified: bool
    balance: float

    class Config:
        from_attributes = True
