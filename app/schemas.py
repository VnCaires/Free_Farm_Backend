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


class StorageResponse(BaseModel):
    id: int
    player_id: int
    capacity_limit: int
    total_quantity: int
    categories: list[InventoryCategoryResponse]


class StorageTransferRequest(BaseModel):
    item_code: str
    quantity: int = Field(gt=0)


class PlayerStatsResponse(BaseModel):
    games_played: int
    crops_planted: int
    crops_harvested: int
    total_earnings: float
    total_expenses: float
    wealth_xp: float
    max_wealth_xp: float
    level: int

    class Config:
        from_attributes = True


class ProgressionBreakdownResponse(BaseModel):
    balance_wealth: float
    storage_wealth: float
    planted_crops_wealth: float
    total_wealth_xp: float


class ProgressionResponse(BaseModel):
    player_id: int
    username: str
    wealth_xp: float
    max_wealth_xp: float
    level: int
    next_level_xp: float | None
    unlocked_features: list[str]
    breakdown: ProgressionBreakdownResponse
    farm_size: int
    next_expansion_size: int | None
    next_expansion_price: float | None
    weekly_land_tax: float
    land_tax_due_now: float


class PlayerProfileResponse(BaseModel):
    player_id: int
    username: str
    email: str | None
    display_name: str
    avatar_url: str
    created_at: datetime
    stats: PlayerStatsResponse


class PlayerProfileUpdateRequest(BaseModel):
    display_name: str | None = None
    avatar_url: str | None = None

    class Config:
        extra = "forbid"

    @validator("display_name")
    def validate_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("Display name cannot be empty")
        if len(normalized) > 30:
            raise ValueError("Display name cannot be longer than 30 characters")
        return normalized

    @validator("avatar_url")
    def validate_avatar_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if len(normalized) > 255:
            raise ValueError("Avatar URL cannot be longer than 255 characters")
        return normalized




class CropTypeResponse(BaseModel):
    id: int
    code: str
    name: str
    growth_time_seconds: int
    yield_quantity: int
    base_value: float
    seed_item_code: str
    product_item_code: str

    class Config:
        from_attributes = True


class PlantCropRequest(BaseModel):
    crop_type_code: str
    plot_id: int = Field(gt=0)


class PlayerCropResponse(BaseModel):
    id: int
    player_id: int
    crop_type_code: str
    crop_type_name: str
    product_item_code: str
    land_plot_id: int
    planted_at: datetime
    state: str
    growth_time_seconds: int
    elapsed_growth_seconds: int
    seconds_until_ready: int
    is_ready: bool


class LandPlotCropResponse(BaseModel):
    id: int
    crop_type_code: str
    crop_type_name: str
    product_item_code: str
    planted_at: datetime
    state: str
    growth_time_seconds: int
    elapsed_growth_seconds: int
    seconds_until_ready: int
    is_ready: bool


class HarvestCropResponse(BaseModel):
    crop: PlayerCropResponse
    storage: StorageResponse


class LandPlotCreateRequest(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    soil_type: str = "loam"
    state: str = "empty"


class LandExpansionRequest(BaseModel):
    soil_type: str = "loam"


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
    crop: LandPlotCropResponse | None = None

    class Config:
        from_attributes = True


class LandGridResponse(BaseModel):
    player_id: int
    total_plots: int
    occupied_plots: int
    width: int
    height: int
    farm_size: int
    max_farm_size: int
    next_expansion_size: int | None
    next_expansion_price: float | None
    weekly_land_tax: float
    land_tax_weeks_due: int
    land_tax_due_now: float
    next_land_tax_at: datetime | None
    plots: list[LandPlotResponse]


class LandExpansionResponse(BaseModel):
    previous_farm_size: int
    new_farm_size: int
    price_paid: float
    weekly_land_tax: float
    balance: float
    plots_added: int
    added_plots: list[LandPlotResponse]
    grid: LandGridResponse


class PlayerResponse(BaseModel):
    id: int
    username: str
    email: str | None
    email_verified: bool
    balance: float

    class Config:
        from_attributes = True

