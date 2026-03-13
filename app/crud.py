import os
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import auth, models


ALLOWED_TRANSACTION_TYPES = {"deposit", "expense"}
ALLOWED_LAND_STATES = {"empty", "plowed", "planted"}
ALLOWED_CROP_STATES = {"planted", "growing", "ready", "harvested"}
STORAGE_CAPACITY_LIMIT = 300
DEFAULT_LAND_WIDTH = 3
DEFAULT_LAND_HEIGHT = 3
DEFAULT_FARM_SIZE = DEFAULT_LAND_WIDTH
MAX_FARM_SIZE = 10
LAND_EXPANSION_BASE_PRICE = 50.0
LAND_EXPANSION_PRICE_GROWTH_FACTOR = 2.0
LAND_WEEKLY_TAX_PER_EXTRA_PLOT = 2.0
LAND_TAX_INTERVAL_DAYS = 7
DEFAULT_SOIL_TYPE = "loam"
DEFAULT_ITEM_CATALOG: list[tuple[str, str, str, float]] = [
    ("seed_wheat", "Semente de Trigo", "seed", 2.0),
    ("seed_corn", "Semente de Milho", "seed", 2.5),
    ("seed_soy", "Semente de Soja", "seed", 2.25),
    ("wheat", "Trigo", "crop", 6.0),
    ("corn", "Milho", "crop", 8.0),
    ("soy", "Soja", "crop", 7.0),
    ("flour", "Farinha", "processed_good", 10.0),
    ("bread", "Pao", "processed_good", 18.0),
    ("feed", "Racao", "processed_good", 12.0),
    ("chicken", "Galinha", "livestock", 25.0),
    ("eggs", "Ovos", "animal_product", 6.0),
    ("ethanol", "Etanol", "fuel", 15.0),
    ("oil", "Oleo", "fuel", 12.0),
    ("biodiesel", "Biodiesel", "fuel", 20.0),
    ("workers", "Trabalhadores", "support", 30.0),
    ("machines", "Maquinas", "support", 60.0),
    ("manure", "Esterco", "fertility", 4.0),
    ("fertilizer", "Fertilizante", "fertility", 9.0),
    ("water_basic", "Agua", "resource", 1.0),
    ("fertilizer_basic", "Fertilizante Basico", "resource", 5.0),
    ("seed_basic", "Semente Legada", "legacy", 2.0),
]
LEVEL_THRESHOLDS = [0.0, 150.0, 300.0, 600.0, 1000.0, 1600.0, 2500.0, 4000.0, 6500.0, 10000.0]
PROGRESSION_UNLOCKS: list[tuple[int, str]] = [
    (1, "base_farm"),
    (2, "wheat_processing"),
    (3, "corn_processing"),
    (4, "soy_processing"),
    (5, "automation_foundation"),
    (6, "advanced_logistics"),
    (8, "industrial_chain"),
    (10, "market_mastery"),
]
DEFAULT_CROP_TYPES: list[tuple[str, str, int, int, float, str, str]] = [
    ("wheat", "Trigo", 480, 2, 6.0, "seed_wheat", "wheat"),
    ("corn", "Milho", 600, 3, 8.0, "seed_corn", "corn"),
    ("soy", "Soja", 720, 2, 7.0, "seed_soy", "soy"),
]
SUPPORTED_CROP_TYPE_CODES = {crop_type[0] for crop_type in DEFAULT_CROP_TYPES}
EMAIL_VERIFICATION_ENABLED = os.getenv("EMAIL_VERIFICATION_ENABLED", "false").lower() == "true"


def _is_plot_occupied(state: str) -> bool:
    return state == "planted"


def _validate_land_state(state: str) -> str:
    normalized = state.strip().lower()
    if normalized not in ALLOWED_LAND_STATES:
        raise ValueError("Invalid land state")
    return normalized


def _validate_player_managed_land_state(state: str) -> str:
    normalized = _validate_land_state(state)
    if normalized == "planted":
        raise ValueError("Planted state is managed by crop actions only")
    return normalized




def _utcnow() -> datetime:
    return datetime.utcnow()


def _round_wealth(value: float) -> float:
    return round(float(value), 2)


def get_level_from_max_wealth_xp(max_wealth_xp: float) -> int:
    level = 1
    for index, threshold in enumerate(LEVEL_THRESHOLDS, start=1):
        if max_wealth_xp >= threshold:
            level = index
    return level


def get_next_level_threshold(level: int) -> float | None:
    if level >= len(LEVEL_THRESHOLDS):
        return None
    return LEVEL_THRESHOLDS[level]


def get_unlocked_features(level: int) -> list[str]:
    return [feature for required_level, feature in PROGRESSION_UNLOCKS if level >= required_level]


def _compute_storage_wealth(db: Session, storage_id: int) -> float:
    total = (
        db.query(func.coalesce(func.sum(models.StorageItem.quantity * models.ItemCatalog.wealth_value), 0.0))
        .join(models.ItemCatalog, models.StorageItem.item_id == models.ItemCatalog.id)
        .filter(models.StorageItem.storage_id == storage_id)
        .scalar()
    )
    return _round_wealth(total or 0.0)


def _compute_planted_crops_wealth(db: Session, player_id: int) -> float:
    total = (
        db.query(func.coalesce(func.sum(models.CropType.base_value * models.CropType.yield_quantity), 0.0))
        .select_from(models.PlayerCrop)
        .join(models.CropType, models.PlayerCrop.crop_type_id == models.CropType.id)
        .filter(models.PlayerCrop.player_id == player_id)
        .scalar()
    )
    return _round_wealth(total or 0.0)


def sync_player_wealth_stats(db: Session, player: models.Player) -> models.PlayerStats:
    db.flush()
    db_stats = get_stats_by_player_id(db, player.id)
    if db_stats is None:
        db_stats = models.PlayerStats(player_id=player.id, last_land_tax_at=_utcnow())
        db.add(db_stats)
        db.flush()

    db_storage = get_or_create_storage(db, player.id, commit=False)
    migrate_inventory_items_to_storage(db, player.id, db_storage)

    db_storage = get_storage_by_player_id(db, player.id)
    if db_storage is None:
        db_storage = models.Storage(player_id=player.id, capacity_limit=STORAGE_CAPACITY_LIMIT)
        db.add(db_storage)
        db.flush()

    balance_wealth = _round_wealth(player.balance)
    storage_wealth = _compute_storage_wealth(db, db_storage.id)
    planted_crops_wealth = _compute_planted_crops_wealth(db, player.id)
    wealth_xp = _round_wealth(balance_wealth + storage_wealth + planted_crops_wealth)

    db_stats.wealth_xp = wealth_xp
    db_stats.max_wealth_xp = _round_wealth(max(db_stats.max_wealth_xp, wealth_xp))
    db_stats.level = get_level_from_max_wealth_xp(db_stats.max_wealth_xp)
    db.flush()
    return db_stats


def build_progression_response(db: Session, player: models.Player, stats: models.PlayerStats) -> dict:
    db_storage = get_or_create_storage(db, player.id)
    storage_wealth = _compute_storage_wealth(db, db_storage.id)
    planted_crops_wealth = _compute_planted_crops_wealth(db, player.id)
    balance_wealth = _round_wealth(player.balance)

    land_economy = sync_land_tax_state(db, player, apply_due_tax=False, commit=False)

    return {
        "player_id": player.id,
        "username": player.username,
        "wealth_xp": _round_wealth(stats.wealth_xp),
        "max_wealth_xp": _round_wealth(stats.max_wealth_xp),
        "level": stats.level,
        "next_level_xp": get_next_level_threshold(stats.level),
        "unlocked_features": get_unlocked_features(stats.level),
        "breakdown": {
            "balance_wealth": balance_wealth,
            "storage_wealth": storage_wealth,
            "planted_crops_wealth": planted_crops_wealth,
            "total_wealth_xp": _round_wealth(balance_wealth + storage_wealth + planted_crops_wealth),
        },
        "farm_size": land_economy["farm_size"],
        "next_expansion_size": land_economy["next_expansion_size"],
        "next_expansion_price": land_economy["next_expansion_price"],
        "weekly_land_tax": land_economy["weekly_land_tax"],
        "land_tax_due_now": land_economy["land_tax_due_now"],
    }


def _compute_crop_growth_metrics(player_crop: models.PlayerCrop) -> tuple[str, int, int]:
    growth_time_seconds = max(0, int(player_crop.crop_type.growth_time_seconds))
    elapsed_growth_seconds = max(0, int((_utcnow() - player_crop.planted_at).total_seconds()))

    if player_crop.state == "harvested":
        return "harvested", elapsed_growth_seconds, 0

    if growth_time_seconds == 0 or elapsed_growth_seconds >= growth_time_seconds:
        return "ready", elapsed_growth_seconds, 0

    if elapsed_growth_seconds >= growth_time_seconds // 2:
        return "growing", elapsed_growth_seconds, growth_time_seconds - elapsed_growth_seconds

    return "planted", elapsed_growth_seconds, growth_time_seconds - elapsed_growth_seconds


def sync_player_crop_state(db: Session, player_crop: models.PlayerCrop) -> models.PlayerCrop:
    if player_crop.state == "harvested":
        return player_crop

    expected_state, _elapsed_growth_seconds, _seconds_until_ready = _compute_crop_growth_metrics(player_crop)
    if player_crop.state != expected_state:
        player_crop.state = expected_state
        db.commit()
        db.refresh(player_crop)
    return player_crop


def sync_player_crop_states(db: Session, player_crops: list[models.PlayerCrop]) -> list[models.PlayerCrop]:
    changed = False
    for player_crop in player_crops:
        if player_crop.state == "harvested":
            continue
        expected_state, _elapsed_growth_seconds, _seconds_until_ready = _compute_crop_growth_metrics(player_crop)
        if player_crop.state != expected_state:
            player_crop.state = expected_state
            changed = True

    if changed:
        db.commit()
        for player_crop in player_crops:
            db.refresh(player_crop)

    return player_crops


def get_player_by_username(db: Session, username: str) -> models.Player | None:
    return db.query(models.Player).filter(models.Player.username == username).first()


def get_player_by_email(db: Session, email: str) -> models.Player | None:
    return db.query(models.Player).filter(models.Player.email == email).first()


def get_player_by_login_identifier(db: Session, identifier: str) -> models.Player | None:
    db_player = get_player_by_username(db, identifier)
    if db_player is not None:
        return db_player

    normalized_identifier = identifier.strip().lower()
    return get_player_by_email(db, normalized_identifier)


def get_item_catalog_by_code(db: Session, code: str) -> models.ItemCatalog | None:
    return db.query(models.ItemCatalog).filter(models.ItemCatalog.code == code).first()


def ensure_default_item_catalog(db: Session) -> bool:
    changed = False
    for code, name, category, wealth_value in DEFAULT_ITEM_CATALOG:
        db_item = get_item_catalog_by_code(db, code)
        if db_item is None:
            db.add(models.ItemCatalog(code=code, name=name, category=category, wealth_value=wealth_value))
            changed = True
            continue

        if db_item.name != name:
            db_item.name = name
            changed = True
        if db_item.category != category:
            db_item.category = category
            changed = True
        if db_item.wealth_value != wealth_value:
            db_item.wealth_value = wealth_value
            changed = True
    if changed:
        db.flush()
    return changed




def get_crop_type_by_code(db: Session, code: str) -> models.CropType | None:
    normalized_code = code.strip().lower()
    if normalized_code not in SUPPORTED_CROP_TYPE_CODES:
        return None
    return db.query(models.CropType).filter(models.CropType.code == normalized_code).first()


def ensure_default_crop_types(db: Session) -> bool:
    changed = False
    for code, name, growth_time_seconds, yield_quantity, base_value, seed_item_code, product_item_code in DEFAULT_CROP_TYPES:
        db_crop_type = get_crop_type_by_code(db, code)
        if db_crop_type is None:
            db.add(
                models.CropType(
                    code=code,
                    name=name,
                    growth_time_seconds=growth_time_seconds,
                    yield_quantity=yield_quantity,
                    base_value=base_value,
                    seed_item_code=seed_item_code,
                    product_item_code=product_item_code,
                )
            )
            changed = True
            continue

        if db_crop_type.name != name:
            db_crop_type.name = name
            changed = True
        if db_crop_type.growth_time_seconds != growth_time_seconds:
            db_crop_type.growth_time_seconds = growth_time_seconds
            changed = True
        if db_crop_type.yield_quantity != yield_quantity:
            db_crop_type.yield_quantity = yield_quantity
            changed = True
        if db_crop_type.base_value != base_value:
            db_crop_type.base_value = base_value
            changed = True
        if db_crop_type.seed_item_code != seed_item_code:
            db_crop_type.seed_item_code = seed_item_code
            changed = True
        if db_crop_type.product_item_code != product_item_code:
            db_crop_type.product_item_code = product_item_code
            changed = True
    if changed:
        db.flush()
    return changed




def _distribute_legacy_seed_quantity(quantity: int) -> list[tuple[str, int]]:
    seed_codes = ["seed_wheat", "seed_corn", "seed_soy"]
    base_quantity = quantity // len(seed_codes)
    remainder = quantity % len(seed_codes)
    distributed: list[tuple[str, int]] = []

    for index, seed_code in enumerate(seed_codes):
        allocated_quantity = base_quantity + (1 if index < remainder else 0)
        if allocated_quantity > 0:
            distributed.append((seed_code, allocated_quantity))

    return distributed


def _upsert_inventory_item_quantity(
    db: Session,
    inventory_id: int,
    item_code: str,
    quantity: int,
) -> None:
    if quantity <= 0:
        return

    db.flush()
    db_item = get_item_catalog_by_code(db, item_code)
    if db_item is None:
        raise ValueError("Item code not found")

    db_inventory_item = (
        db.query(models.InventoryItem)
        .filter(
            models.InventoryItem.inventory_id == inventory_id,
            models.InventoryItem.item_id == db_item.id,
        )
        .first()
    )
    if db_inventory_item is None:
        db.add(models.InventoryItem(inventory_id=inventory_id, item_id=db_item.id, quantity=quantity))
        return

    db_inventory_item.quantity += quantity


def _upsert_storage_item_quantity(
    db: Session,
    storage_id: int,
    item_code: str,
    quantity: int,
) -> None:
    if quantity <= 0:
        return

    db.flush()
    db_item = get_item_catalog_by_code(db, item_code)
    if db_item is None:
        raise ValueError("Item code not found")

    db_storage_item = (
        db.query(models.StorageItem)
        .filter(
            models.StorageItem.storage_id == storage_id,
            models.StorageItem.item_id == db_item.id,
        )
        .first()
    )
    if db_storage_item is None:
        db.add(models.StorageItem(storage_id=storage_id, item_id=db_item.id, quantity=quantity))
        return

    db_storage_item.quantity += quantity


def upgrade_legacy_seed_inventory(db: Session, inventory: models.Inventory) -> bool:
    legacy_seed_catalog = get_item_catalog_by_code(db, "seed_basic")
    if legacy_seed_catalog is None:
        return False

    legacy_seed_item = (
        db.query(models.InventoryItem)
        .filter(
            models.InventoryItem.inventory_id == inventory.id,
            models.InventoryItem.item_id == legacy_seed_catalog.id,
        )
        .first()
    )
    if legacy_seed_item is None or legacy_seed_item.quantity <= 0:
        return False

    specific_seed_total = 0
    for seed_code in ("seed_wheat", "seed_corn", "seed_soy"):
        db_seed_catalog = get_item_catalog_by_code(db, seed_code)
        if db_seed_catalog is None:
            continue
        db_seed_item = (
            db.query(models.InventoryItem)
            .filter(
                models.InventoryItem.inventory_id == inventory.id,
                models.InventoryItem.item_id == db_seed_catalog.id,
            )
            .first()
        )
        if db_seed_item is not None:
            specific_seed_total += db_seed_item.quantity

    if specific_seed_total == 0:
        for seed_code, quantity in _distribute_legacy_seed_quantity(legacy_seed_item.quantity):
            _upsert_inventory_item_quantity(db, inventory.id, seed_code, quantity)

    db.flush()
    db.delete(legacy_seed_item)
    return True


def create_player(db: Session, username: str, email: str, password: str) -> models.Player:
    normalized_email = email.strip().lower()
    hashed_password = auth.hash_password(password)
    db_player = models.Player(
        username=username,
        email=normalized_email,
        email_verified=not EMAIL_VERIFICATION_ENABLED,
        hashed_password=hashed_password,
    )

    try:
        db.add(db_player)
        db.flush()

        db_storage = models.Storage(player_id=db_player.id, capacity_limit=STORAGE_CAPACITY_LIMIT)
        db_profile = models.PlayerProfile(
            player_id=db_player.id,
            display_name=username,
            avatar_url="",
        )
        db_stats = models.PlayerStats(player_id=db_player.id, last_land_tax_at=_utcnow())
        db.add(db_storage)
        db.add(db_profile)
        db.add(db_stats)
        db.flush()
        bootstrap_default_land_plots(db, db_player.id)

        ensure_default_item_catalog(db)
        ensure_default_crop_types(db)
        bootstrap_storage_items_from_legacy_defaults(db, db_storage)
        sync_player_wealth_stats(db, db_player)

        db.commit()
        db.refresh(db_player)
        return db_player
    except Exception:
        db.rollback()
        raise



def get_profile_by_player_id(db: Session, player_id: int) -> models.PlayerProfile | None:
    return db.query(models.PlayerProfile).filter(models.PlayerProfile.player_id == player_id).first()


def get_stats_by_player_id(db: Session, player_id: int) -> models.PlayerStats | None:
    return db.query(models.PlayerStats).filter(models.PlayerStats.player_id == player_id).first()


def get_or_create_player_profile(db: Session, player: models.Player) -> tuple[models.PlayerProfile, models.PlayerStats]:
    db_profile = get_profile_by_player_id(db, player.id)
    db_stats = get_stats_by_player_id(db, player.id)
    changed = False

    if db_profile is None:
        db_profile = models.PlayerProfile(
            player_id=player.id,
            display_name=player.username,
            avatar_url="",
        )
        db.add(db_profile)
        changed = True

    if db_stats is None:
        db_stats = models.PlayerStats(player_id=player.id, last_land_tax_at=_utcnow())
        db.add(db_stats)
        changed = True

    if changed:
        db.commit()
        db.refresh(db_profile)
        db.refresh(db_stats)

    return db_profile, db_stats


def build_player_profile_response(
    player: models.Player,
    profile: models.PlayerProfile,
    stats: models.PlayerStats,
) -> dict:
    return {
        "player_id": player.id,
        "username": player.username,
        "email": player.email,
        "display_name": profile.display_name,
        "avatar_url": profile.avatar_url,
        "created_at": profile.created_at,
        "stats": {
            "games_played": stats.games_played,
            "crops_planted": stats.crops_planted,
            "crops_harvested": stats.crops_harvested,
            "total_earnings": stats.total_earnings,
            "total_expenses": stats.total_expenses,
            "wealth_xp": _round_wealth(stats.wealth_xp),
            "max_wealth_xp": _round_wealth(stats.max_wealth_xp),
            "level": stats.level,
        },
    }


def update_player_profile(
    db: Session,
    profile: models.PlayerProfile,
    display_name: str | None = None,
    avatar_url: str | None = None,
) -> models.PlayerProfile:
    if display_name is not None:
        profile.display_name = display_name
    if avatar_url is not None:
        profile.avatar_url = avatar_url

    db.commit()
    db.refresh(profile)
    return profile

def create_wallet_transaction(
    db: Session,
    player_id: int,
    amount: float,
    transaction_type: str,
) -> models.WalletTransaction:
    if transaction_type not in ALLOWED_TRANSACTION_TYPES:
        raise ValueError(f"Invalid transaction type: {transaction_type}")

    db_transaction = models.WalletTransaction(
        player_id=player_id,
        amount=amount,
        transaction_type=transaction_type,
    )
    db.add(db_transaction)
    return db_transaction


def deposit_balance(db: Session, player: models.Player, amount: float) -> models.Player:
    sync_land_tax_state(db, player, apply_due_tax=True, commit=False)
    player.balance += amount
    create_wallet_transaction(db, player.id, amount, "deposit")

    db_stats = get_stats_by_player_id(db, player.id)
    if db_stats is not None:
        db_stats.total_earnings += amount

    sync_player_wealth_stats(db, player)
    db.commit()
    db.refresh(player)
    return player


def get_wallet_history_by_player_id(
    db: Session,
    player_id: int,
    limit: int = 20,
    offset: int = 0,
) -> list[models.WalletTransaction]:
    return (
        db.query(models.WalletTransaction)
        .filter(models.WalletTransaction.player_id == player_id)
        .order_by(models.WalletTransaction.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_inventory_by_player_id(db: Session, player_id: int) -> models.Inventory | None:
    return db.query(models.Inventory).filter(models.Inventory.player_id == player_id).first()


def get_storage_by_player_id(db: Session, player_id: int) -> models.Storage | None:
    return db.query(models.Storage).filter(models.Storage.player_id == player_id).first()


def bootstrap_storage_items_from_legacy_defaults(db: Session, storage: models.Storage) -> bool:
    has_items = (
        db.query(models.StorageItem)
        .filter(models.StorageItem.storage_id == storage.id)
        .first()
        is not None
    )
    if has_items:
        return False

    legacy_items = [
        *_distribute_legacy_seed_quantity(10),
        ("water_basic", 5),
        ("fertilizer_basic", 3),
    ]

    changed = False
    for code, quantity in legacy_items:
        if quantity <= 0:
            continue
        _upsert_storage_item_quantity(db, storage.id, code, quantity)
        changed = True

    return changed


def migrate_inventory_items_to_storage(
    db: Session,
    player_id: int,
    storage: models.Storage | None = None,
) -> bool:
    db_inventory = get_inventory_by_player_id(db, player_id)
    if db_inventory is None:
        return False

    db_storage = storage or get_storage_by_player_id(db, player_id)
    if db_storage is None:
        db_storage = models.Storage(player_id=player_id, capacity_limit=STORAGE_CAPACITY_LIMIT)
        db.add(db_storage)
        db.flush()

    rows = (
        db.query(models.InventoryItem, models.ItemCatalog)
        .join(models.ItemCatalog, models.InventoryItem.item_id == models.ItemCatalog.id)
        .filter(models.InventoryItem.inventory_id == db_inventory.id)
        .all()
    )

    changed = False
    inventory_items_to_delete: list[models.InventoryItem] = []
    if rows:
        for inventory_item, catalog_item in rows:
            inventory_items_to_delete.append(inventory_item)
            if inventory_item.quantity <= 0:
                continue
            _upsert_storage_item_quantity(db, db_storage.id, catalog_item.code, inventory_item.quantity)
            changed = True

        db.flush()
        for inventory_item in inventory_items_to_delete:
            db.delete(inventory_item)

    if not rows:
        legacy_items = [
            *_distribute_legacy_seed_quantity(max(0, int(db_inventory.seeds or 0))),
            ("water_basic", max(0, int(db_inventory.water or 0))),
            ("fertilizer_basic", max(0, int(db_inventory.fertilizer or 0))),
        ]
        for item_code, quantity in legacy_items:
            if quantity <= 0:
                continue
            _upsert_storage_item_quantity(db, db_storage.id, item_code, quantity)
            changed = True

    if changed:
        db_inventory.seeds = 0
        db_inventory.water = 0
        db_inventory.fertilizer = 0

    return changed


def get_or_create_storage(db: Session, player_id: int, *, commit: bool = True) -> models.Storage:
    db_storage = get_storage_by_player_id(db, player_id)
    created = False
    if db_storage is None:
        db_storage = models.Storage(player_id=player_id, capacity_limit=STORAGE_CAPACITY_LIMIT)
        db.add(db_storage)
        db.flush()
        created = True

    catalog_changed = ensure_default_item_catalog(db)
    crop_types_changed = ensure_default_crop_types(db)
    migrated_inventory_changed = migrate_inventory_items_to_storage(db, player_id, db_storage)
    bootstrap_changed = False
    if created and not migrated_inventory_changed:
        bootstrap_changed = bootstrap_storage_items_from_legacy_defaults(db, db_storage)

    if commit and (created or catalog_changed or crop_types_changed or bootstrap_changed or migrated_inventory_changed):
        db.commit()
        db.refresh(db_storage)

    return db_storage


def get_storage_total_quantity(db: Session, storage_id: int) -> int:
    total_quantity = (
        db.query(func.coalesce(func.sum(models.StorageItem.quantity), 0))
        .filter(models.StorageItem.storage_id == storage_id)
        .scalar()
    )
    return int(total_quantity or 0)


def get_storage_item_quantity(db: Session, storage: models.Storage, item_code: str) -> int:
    db_item = get_item_catalog_by_code(db, item_code)
    if db_item is None:
        return 0

    db_storage_item = (
        db.query(models.StorageItem)
        .filter(
            models.StorageItem.storage_id == storage.id,
            models.StorageItem.item_id == db_item.id,
        )
        .first()
    )
    return int(db_storage_item.quantity if db_storage_item is not None else 0)


def add_item_to_storage(
    db: Session,
    storage: models.Storage,
    item_code: str,
    quantity: int,
    *,
    commit: bool = True,
) -> None:
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero")

    ensure_default_item_catalog(db)
    current_total = get_storage_total_quantity(db, storage.id)
    if current_total + quantity > storage.capacity_limit:
        raise ValueError("Storage capacity exceeded")

    _upsert_storage_item_quantity(db, storage.id, item_code, quantity)

    if commit:
        db_player = db.query(models.Player).filter(models.Player.id == storage.player_id).first()
        if db_player is not None:
            sync_player_wealth_stats(db, db_player)
        db.commit()


def add_item_to_inventory(
    db: Session,
    inventory: models.Inventory,
    item_code: str,
    quantity: int,
    *,
    commit: bool = True,
) -> None:
    db_player = db.query(models.Player).filter(models.Player.id == inventory.player_id).first()
    if db_player is None:
        raise ValueError("Player not found")

    db_storage = get_or_create_storage(db, db_player.id, commit=False)
    add_item_to_storage(db, db_storage, item_code, quantity, commit=commit)


def remove_item_from_storage(
    db: Session,
    storage: models.Storage,
    item_code: str,
    quantity: int,
) -> None:
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero")

    db_item = get_item_catalog_by_code(db, item_code)
    if db_item is None:
        raise ValueError("Item code not found")

    db_storage_item = (
        db.query(models.StorageItem)
        .filter(
            models.StorageItem.storage_id == storage.id,
            models.StorageItem.item_id == db_item.id,
        )
        .first()
    )
    if db_storage_item is None or db_storage_item.quantity < quantity:
        raise ValueError("Not enough items in storage")

    db_storage_item.quantity -= quantity
    if db_storage_item.quantity == 0:
        db.delete(db_storage_item)


def list_crop_types(db: Session) -> list[models.CropType]:
    ensure_default_crop_types(db)
    return (
        db.query(models.CropType)
        .filter(models.CropType.code.in_(SUPPORTED_CROP_TYPE_CODES))
        .order_by(models.CropType.name.asc())
        .all()
    )


def list_player_crops(db: Session, player_id: int) -> list[models.PlayerCrop]:
    player_crops = (
        db.query(models.PlayerCrop)
        .filter(models.PlayerCrop.player_id == player_id)
        .order_by(models.PlayerCrop.planted_at.desc())
        .all()
    )
    return sync_player_crop_states(db, player_crops)


def get_player_crop_by_id_for_player(db: Session, player_id: int, crop_id: int) -> models.PlayerCrop | None:
    db_player_crop = (
        db.query(models.PlayerCrop)
        .filter(models.PlayerCrop.player_id == player_id, models.PlayerCrop.id == crop_id)
        .first()
    )
    if db_player_crop is None:
        return None
    return sync_player_crop_state(db, db_player_crop)


def build_player_crop_response(player_crop: models.PlayerCrop) -> dict:
    state, elapsed_growth_seconds, seconds_until_ready = _compute_crop_growth_metrics(player_crop)
    return {
        "id": player_crop.id,
        "player_id": player_crop.player_id,
        "crop_type_code": player_crop.crop_type.code,
        "crop_type_name": player_crop.crop_type.name,
        "product_item_code": player_crop.crop_type.product_item_code,
        "land_plot_id": player_crop.land_plot_id,
        "planted_at": player_crop.planted_at,
        "state": state,
        "growth_time_seconds": player_crop.crop_type.growth_time_seconds,
        "elapsed_growth_seconds": elapsed_growth_seconds,
        "seconds_until_ready": seconds_until_ready,
        "is_ready": state == "ready",
    }


def build_land_plot_crop_response(player_crop: models.PlayerCrop) -> dict:
    crop_response = build_player_crop_response(player_crop)
    return {
        "id": crop_response["id"],
        "crop_type_code": crop_response["crop_type_code"],
        "crop_type_name": crop_response["crop_type_name"],
        "product_item_code": crop_response["product_item_code"],
        "planted_at": crop_response["planted_at"],
        "state": crop_response["state"],
        "growth_time_seconds": crop_response["growth_time_seconds"],
        "elapsed_growth_seconds": crop_response["elapsed_growth_seconds"],
        "seconds_until_ready": crop_response["seconds_until_ready"],
        "is_ready": crop_response["is_ready"],
    }


def build_land_plot_response(db: Session, land_plot: models.LandPlot) -> dict:
    crop_payload = None
    if land_plot.is_occupied and land_plot.crop is not None and land_plot.crop.state != "harvested":
        synced_crop = sync_player_crop_state(db, land_plot.crop)
        crop_payload = build_land_plot_crop_response(synced_crop)

    return {
        "id": land_plot.id,
        "player_id": land_plot.player_id,
        "x": land_plot.x,
        "y": land_plot.y,
        "soil_type": land_plot.soil_type,
        "state": land_plot.state,
        "is_occupied": land_plot.is_occupied,
        "created_at": land_plot.created_at,
        "updated_at": land_plot.updated_at,
        "crop": crop_payload,
    }


def get_land_grid_dimensions(land_plots: list[models.LandPlot]) -> tuple[int, int]:
    if not land_plots:
        return 0, 0

    x_values = [land_plot.x for land_plot in land_plots]
    y_values = [land_plot.y for land_plot in land_plots]
    return (max(x_values) - min(x_values)) + 1, (max(y_values) - min(y_values)) + 1


def get_current_farm_size(land_plots: list[models.LandPlot]) -> int:
    width, height = get_land_grid_dimensions(land_plots)
    return max(DEFAULT_FARM_SIZE, width, height)


def get_next_farm_size(current_farm_size: int) -> int | None:
    if current_farm_size >= MAX_FARM_SIZE:
        return None
    return current_farm_size + 1


def get_land_expansion_price_for_size(current_farm_size: int) -> float | None:
    if current_farm_size >= MAX_FARM_SIZE:
        return None
    growth_step = max(0, current_farm_size - DEFAULT_FARM_SIZE)
    return _round_wealth(LAND_EXPANSION_BASE_PRICE * (LAND_EXPANSION_PRICE_GROWTH_FACTOR**growth_step))


def get_weekly_land_tax_for_size(farm_size: int) -> float:
    extra_plots = max(0, (farm_size * farm_size) - (DEFAULT_FARM_SIZE * DEFAULT_FARM_SIZE))
    return _round_wealth(extra_plots * LAND_WEEKLY_TAX_PER_EXTRA_PLOT)


def _get_land_tax_weeks_due(last_land_tax_at: datetime | None, now: datetime) -> int:
    if last_land_tax_at is None:
        return 0
    elapsed = now - last_land_tax_at
    return max(0, elapsed.days // LAND_TAX_INTERVAL_DAYS)


def sync_land_tax_state(
    db: Session,
    player: models.Player,
    *,
    apply_due_tax: bool = False,
    commit: bool = False,
) -> dict:
    land_plots = get_or_create_land_plots(db, player.id)
    farm_size = get_current_farm_size(land_plots)
    weekly_tax = get_weekly_land_tax_for_size(farm_size)
    next_expansion_size = get_next_farm_size(farm_size)
    next_expansion_price = get_land_expansion_price_for_size(farm_size)
    now = _utcnow()

    db_stats = get_stats_by_player_id(db, player.id)
    if db_stats is None:
        db_stats = models.PlayerStats(player_id=player.id, last_land_tax_at=now)
        db.add(db_stats)
        db.flush()
    elif db_stats.last_land_tax_at is None:
        db_stats.last_land_tax_at = now
        db.flush()

    land_tax_weeks_due = _get_land_tax_weeks_due(db_stats.last_land_tax_at, now)
    tax_due_now = _round_wealth(weekly_tax * land_tax_weeks_due)

    if apply_due_tax and land_tax_weeks_due > 0 and tax_due_now > 0:
        player.balance = _round_wealth(player.balance - tax_due_now)
        create_wallet_transaction(db, player.id, tax_due_now, "expense")
        db_stats.total_expenses = _round_wealth(db_stats.total_expenses + tax_due_now)
        db_stats.last_land_tax_at = db_stats.last_land_tax_at + timedelta(days=land_tax_weeks_due * LAND_TAX_INTERVAL_DAYS)
        sync_player_wealth_stats(db, player)
        land_tax_weeks_due = _get_land_tax_weeks_due(db_stats.last_land_tax_at, now)
        tax_due_now = _round_wealth(weekly_tax * land_tax_weeks_due)
        if commit:
            db.commit()
            db.refresh(player)
            db.refresh(db_stats)
    elif apply_due_tax and land_tax_weeks_due > 0:
        db_stats.last_land_tax_at = db_stats.last_land_tax_at + timedelta(days=land_tax_weeks_due * LAND_TAX_INTERVAL_DAYS)
        if commit:
            db.commit()
            db.refresh(db_stats)

    next_land_tax_at = None
    if db_stats.last_land_tax_at is not None:
        next_land_tax_at = db_stats.last_land_tax_at + timedelta(days=LAND_TAX_INTERVAL_DAYS)

    return {
        "farm_size": farm_size,
        "max_farm_size": MAX_FARM_SIZE,
        "next_expansion_size": next_expansion_size,
        "next_expansion_price": next_expansion_price,
        "weekly_land_tax": weekly_tax,
        "land_tax_weeks_due": land_tax_weeks_due,
        "land_tax_due_now": tax_due_now,
        "next_land_tax_at": next_land_tax_at,
    }


def build_land_grid_response(db: Session, player: models.Player, land_plots: list[models.LandPlot]) -> dict:
    width, height = get_land_grid_dimensions(land_plots)
    occupied_plots = sum(1 for land_plot in land_plots if land_plot.is_occupied)
    land_economy = sync_land_tax_state(db, player, apply_due_tax=False, commit=False)

    return {
        "player_id": player.id,
        "total_plots": len(land_plots),
        "occupied_plots": occupied_plots,
        "width": width,
        "height": height,
        "farm_size": land_economy["farm_size"],
        "max_farm_size": land_economy["max_farm_size"],
        "next_expansion_size": land_economy["next_expansion_size"],
        "next_expansion_price": land_economy["next_expansion_price"],
        "weekly_land_tax": land_economy["weekly_land_tax"],
        "land_tax_weeks_due": land_economy["land_tax_weeks_due"],
        "land_tax_due_now": land_economy["land_tax_due_now"],
        "next_land_tax_at": land_economy["next_land_tax_at"],
        "plots": [build_land_plot_response(db, land_plot) for land_plot in land_plots],
    }


def plant_crop(
    db: Session,
    player: models.Player,
    crop_type_code: str,
    plot_id: int,
) -> models.PlayerCrop:
    db_storage = get_or_create_storage(db, player.id)
    db_plot = get_land_plot_by_id_for_player(db, player.id, plot_id)
    if db_plot is None:
        raise ValueError("Land plot not found")
    if db_plot.is_occupied or db_plot.state not in {"empty", "plowed"}:
        raise ValueError("Land plot is not available for planting")

    db_crop_type = get_crop_type_by_code(db, crop_type_code.strip().lower())
    if db_crop_type is None:
        raise ValueError("Crop type not found")

    remove_item_from_storage(db, db_storage, db_crop_type.seed_item_code, 1)

    db_stats = get_stats_by_player_id(db, player.id)
    if db_stats is not None:
        db_stats.crops_planted += 1

    db_player_crop = models.PlayerCrop(
        player_id=player.id,
        crop_type_id=db_crop_type.id,
        land_plot_id=db_plot.id,
        state="planted",
    )
    db_plot.state = "planted"
    db_plot.is_occupied = True
    db.add(db_player_crop)
    sync_player_wealth_stats(db, player)
    db.commit()
    db.refresh(db_player_crop)
    return db_player_crop


def harvest_crop(db: Session, player: models.Player, crop_id: int) -> tuple[dict, dict]:
    db_player_crop = get_player_crop_by_id_for_player(db, player.id, crop_id)
    if db_player_crop is None:
        raise ValueError("Crop not found")

    if db_player_crop.state != "ready":
        raise ValueError("Crop is not ready for harvest")

    db_storage = get_or_create_storage(db, player.id)
    add_item_to_storage(
        db,
        db_storage,
        db_player_crop.crop_type.product_item_code,
        db_player_crop.crop_type.yield_quantity,
        commit=False,
    )

    db_plot = db_player_crop.land_plot
    db_player_crop.state = "harvested"
    harvested_crop_response = build_player_crop_response(db_player_crop)
    db_plot.state = "empty"
    db_plot.is_occupied = False
    db.delete(db_player_crop)

    db_stats = get_stats_by_player_id(db, player.id)
    if db_stats is not None:
        db_stats.crops_harvested += 1

    sync_player_wealth_stats(db, player)
    db.commit()
    db.refresh(db_plot)
    db.refresh(db_storage)

    return harvested_crop_response, get_storage_structured(db, db_storage)


def get_player_progression(db: Session, player: models.Player) -> dict:
    sync_land_tax_state(db, player, apply_due_tax=True, commit=False)
    db_stats = sync_player_wealth_stats(db, player)
    db.commit()
    db.refresh(player)
    db.refresh(db_stats)
    return build_progression_response(db, player, db_stats)


def get_inventory_structured(db: Session, inventory: models.Inventory) -> dict:
    db_storage = get_or_create_storage(db, inventory.player_id)
    return get_storage_structured(db, db_storage)


def get_storage_structured(db: Session, storage: models.Storage) -> dict:
    rows: list[tuple[models.StorageItem, models.ItemCatalog]] = (
        db.query(models.StorageItem, models.ItemCatalog)
        .join(models.ItemCatalog, models.StorageItem.item_id == models.ItemCatalog.id)
        .filter(models.StorageItem.storage_id == storage.id)
        .order_by(models.ItemCatalog.category.asc(), models.ItemCatalog.name.asc())
        .all()
    )

    grouped: dict[str, list[dict[str, int | str]]] = defaultdict(list)
    total_quantity = 0

    for storage_item, catalog_item in rows:
        total_quantity += storage_item.quantity
        grouped[catalog_item.category].append(
            {
                "code": catalog_item.code,
                "name": catalog_item.name,
                "category": catalog_item.category,
                "quantity": storage_item.quantity,
            }
        )

    categories = [
        {"category": category, "items": items}
        for category, items in grouped.items()
    ]

    return {
        "id": storage.id,
        "player_id": storage.player_id,
        "capacity_limit": storage.capacity_limit,
        "total_quantity": total_quantity,
        "categories": categories,
    }


def get_land_plot_by_coordinates(db: Session, player_id: int, x: int, y: int) -> models.LandPlot | None:
    return (
        db.query(models.LandPlot)
        .filter(models.LandPlot.player_id == player_id, models.LandPlot.x == x, models.LandPlot.y == y)
        .first()
    )


def get_land_plot_by_id_for_player(db: Session, player_id: int, plot_id: int) -> models.LandPlot | None:
    return (
        db.query(models.LandPlot)
        .filter(models.LandPlot.player_id == player_id, models.LandPlot.id == plot_id)
        .first()
    )


def list_land_plots_by_player_id(db: Session, player_id: int) -> list[models.LandPlot]:
    return (
        db.query(models.LandPlot)
        .filter(models.LandPlot.player_id == player_id)
        .order_by(models.LandPlot.y.asc(), models.LandPlot.x.asc())
        .all()
    )


def expand_land_grid(
    db: Session,
    player: models.Player,
    soil_type: str = DEFAULT_SOIL_TYPE,
) -> dict:
    normalized_soil_type = soil_type.strip().lower()
    if not normalized_soil_type:
        raise ValueError("Invalid soil type")

    land_plots = get_or_create_land_plots(db, player.id)
    current_farm_size = get_current_farm_size(land_plots)
    next_farm_size = get_next_farm_size(current_farm_size)
    if next_farm_size is None:
        raise ValueError("Farm already reached the maximum size")

    land_economy = sync_land_tax_state(db, player, apply_due_tax=True, commit=False)
    expansion_price = land_economy["next_expansion_price"]
    if expansion_price is None:
        raise ValueError("Farm already reached the maximum size")
    if player.balance < expansion_price:
        raise ValueError("Insufficient balance for expansion")

    existing_coordinates = {(plot.x, plot.y) for plot in land_plots}
    new_plots: list[models.LandPlot] = []
    for y in range(next_farm_size):
        for x in range(next_farm_size):
            if (x, y) in existing_coordinates:
                continue
            db_plot = models.LandPlot(
                player_id=player.id,
                x=x,
                y=y,
                soil_type=normalized_soil_type,
                state="empty",
                is_occupied=False,
            )
            db.add(db_plot)
            new_plots.append(db_plot)

    if not new_plots:
        raise ValueError("No new plots available for the next farm tier")

    player.balance = _round_wealth(player.balance - expansion_price)
    create_wallet_transaction(db, player.id, expansion_price, "expense")

    db_stats = get_stats_by_player_id(db, player.id)
    if db_stats is not None:
        db_stats.total_expenses = _round_wealth(db_stats.total_expenses + expansion_price)

    sync_player_wealth_stats(db, player)
    db.commit()
    db.refresh(player)
    for plot in new_plots:
        db.refresh(plot)

    updated_land_plots = list_land_plots_by_player_id(db, player.id)
    updated_land_economy = sync_land_tax_state(db, player, apply_due_tax=False, commit=False)
    return {
        "previous_farm_size": current_farm_size,
        "new_farm_size": updated_land_economy["farm_size"],
        "price_paid": expansion_price,
        "weekly_land_tax": updated_land_economy["weekly_land_tax"],
        "balance": player.balance,
        "plots_added": len(new_plots),
        "added_plots": [build_land_plot_response(db, plot) for plot in new_plots],
        "grid": build_land_grid_response(db, player, updated_land_plots),
    }


def bootstrap_default_land_plots(
    db: Session,
    player_id: int,
    width: int = DEFAULT_LAND_WIDTH,
    height: int = DEFAULT_LAND_HEIGHT,
) -> bool:
    has_plots = (
        db.query(models.LandPlot)
        .filter(models.LandPlot.player_id == player_id)
        .first()
        is not None
    )
    if has_plots:
        return False

    for y in range(height):
        for x in range(width):
            db.add(
                models.LandPlot(
                    player_id=player_id,
                    x=x,
                    y=y,
                    soil_type=DEFAULT_SOIL_TYPE,
                    state="empty",
                    is_occupied=False,
                )
            )
    return True


def get_or_create_land_plots(db: Session, player_id: int) -> list[models.LandPlot]:
    created_default = bootstrap_default_land_plots(db, player_id)
    if created_default:
        db.commit()

    return list_land_plots_by_player_id(db, player_id)


def create_land_plot(
    db: Session,
    player_id: int,
    x: int,
    y: int,
    soil_type: str = DEFAULT_SOIL_TYPE,
    state: str = "empty",
) -> models.LandPlot:
    validated_state = _validate_player_managed_land_state(state)
    normalized_soil_type = soil_type.strip().lower()
    if not normalized_soil_type:
        raise ValueError("Invalid soil type")

    db_plot = get_land_plot_by_coordinates(db, player_id, x, y)
    if db_plot is not None:
        raise ValueError("Plot coordinates already in use")

    db_plot = models.LandPlot(
        player_id=player_id,
        x=x,
        y=y,
        soil_type=normalized_soil_type,
        state=validated_state,
        is_occupied=False,
    )
    db.add(db_plot)
    db.commit()
    db.refresh(db_plot)
    return db_plot


def update_land_plot_state(db: Session, land_plot: models.LandPlot, new_state: str) -> models.LandPlot:
    validated_state = _validate_player_managed_land_state(new_state)

    if land_plot.is_occupied or (land_plot.crop is not None and land_plot.crop.state != "harvested"):
        raise ValueError("Occupied plots cannot be changed manually")

    land_plot.state = validated_state
    land_plot.is_occupied = False
    db.commit()
    db.refresh(land_plot)
    return land_plot
