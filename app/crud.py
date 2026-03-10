import os
from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import auth, models


ALLOWED_TRANSACTION_TYPES = {"deposit", "expense"}
ALLOWED_LAND_STATES = {"empty", "plowed", "planted"}
INVENTORY_CAPACITY_LIMIT = 100
DEFAULT_LAND_WIDTH = 3
DEFAULT_LAND_HEIGHT = 3
DEFAULT_SOIL_TYPE = "loam"
DEFAULT_ITEM_CATALOG: list[tuple[str, str, str]] = [
    ("seed_basic", "Basic Seed", "seed"),
    ("water_basic", "Water", "resource"),
    ("fertilizer_basic", "Fertilizer", "resource"),
]
EMAIL_VERIFICATION_ENABLED = os.getenv("EMAIL_VERIFICATION_ENABLED", "false").lower() == "true"


def _is_plot_occupied(state: str) -> bool:
    return state == "planted"


def _validate_land_state(state: str) -> str:
    normalized = state.strip().lower()
    if normalized not in ALLOWED_LAND_STATES:
        raise ValueError("Invalid land state")
    return normalized


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
    for code, name, category in DEFAULT_ITEM_CATALOG:
        db_item = get_item_catalog_by_code(db, code)
        if db_item is None:
            db.add(models.ItemCatalog(code=code, name=name, category=category))
            changed = True
    if changed:
        db.flush()
    return changed


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

        db_inventory = models.Inventory(player_id=db_player.id)
        db_profile = models.PlayerProfile(
            player_id=db_player.id,
            display_name=username,
            avatar_url="",
        )
        db.add(db_inventory)
        db.add(db_profile)
        bootstrap_default_land_plots(db, db_player.id)

        ensure_default_item_catalog(db)
        bootstrap_inventory_items_from_legacy(db, db_inventory)

        db.commit()
        db.refresh(db_player)
        return db_player
    except Exception:
        db.rollback()
        raise


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
    player.balance += amount
    create_wallet_transaction(db, player.id, amount, "deposit")
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


def bootstrap_inventory_items_from_legacy(db: Session, inventory: models.Inventory) -> bool:
    has_items = (
        db.query(models.InventoryItem)
        .filter(models.InventoryItem.inventory_id == inventory.id)
        .first()
        is not None
    )
    if has_items:
        return False

    legacy_items = [
        ("seed_basic", max(0, int(inventory.seeds or 0))),
        ("water_basic", max(0, int(inventory.water or 0))),
        ("fertilizer_basic", max(0, int(inventory.fertilizer or 0))),
    ]

    changed = False
    for code, quantity in legacy_items:
        if quantity <= 0:
            continue

        db_catalog = get_item_catalog_by_code(db, code)
        if db_catalog is None:
            continue

        db.add(
            models.InventoryItem(
                inventory_id=inventory.id,
                item_id=db_catalog.id,
                quantity=quantity,
            )
        )
        changed = True

    return changed


def get_or_create_inventory(db: Session, player_id: int) -> models.Inventory:
    db_inventory = get_inventory_by_player_id(db, player_id)
    created_inventory = False

    if db_inventory is None:
        db_inventory = models.Inventory(player_id=player_id)
        db.add(db_inventory)
        db.flush()
        created_inventory = True

    catalog_changed = ensure_default_item_catalog(db)
    bootstrap_changed = bootstrap_inventory_items_from_legacy(db, db_inventory)

    if created_inventory or catalog_changed or bootstrap_changed:
        db.commit()
        db.refresh(db_inventory)

    return db_inventory


def get_inventory_total_quantity(db: Session, inventory_id: int) -> int:
    total_quantity = (
        db.query(func.coalesce(func.sum(models.InventoryItem.quantity), 0))
        .filter(models.InventoryItem.inventory_id == inventory_id)
        .scalar()
    )
    return int(total_quantity or 0)


def add_item_to_inventory(
    db: Session,
    inventory: models.Inventory,
    item_code: str,
    quantity: int,
) -> None:
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero")

    ensure_default_item_catalog(db)
    db_item = get_item_catalog_by_code(db, item_code)
    if db_item is None:
        raise ValueError("Item code not found")

    current_total = get_inventory_total_quantity(db, inventory.id)
    if current_total + quantity > INVENTORY_CAPACITY_LIMIT:
        raise ValueError("Inventory capacity exceeded")

    db_inventory_item = (
        db.query(models.InventoryItem)
        .filter(
            models.InventoryItem.inventory_id == inventory.id,
            models.InventoryItem.item_id == db_item.id,
        )
        .first()
    )

    if db_inventory_item is None:
        db_inventory_item = models.InventoryItem(
            inventory_id=inventory.id,
            item_id=db_item.id,
            quantity=quantity,
        )
        db.add(db_inventory_item)
    else:
        db_inventory_item.quantity += quantity

    db.commit()
    


def get_inventory_structured(db: Session, inventory: models.Inventory) -> dict:
    rows: list[tuple[models.InventoryItem, models.ItemCatalog]] = (
        db.query(models.InventoryItem, models.ItemCatalog)
        .join(models.ItemCatalog, models.InventoryItem.item_id == models.ItemCatalog.id)
        .filter(models.InventoryItem.inventory_id == inventory.id)
        .order_by(models.ItemCatalog.category.asc(), models.ItemCatalog.name.asc())
        .all()
    )

    grouped: dict[str, list[dict[str, int | str]]] = defaultdict(list)
    total_quantity = 0

    for inv_item, catalog_item in rows:
        total_quantity += inv_item.quantity
        grouped[catalog_item.category].append(
            {
                "code": catalog_item.code,
                "name": catalog_item.name,
                "category": catalog_item.category,
                "quantity": inv_item.quantity,
            }
        )

    categories = [
        {"category": category, "items": items}
        for category, items in grouped.items()
    ]

    return {
        "id": inventory.id,
        "player_id": inventory.player_id,
        "capacity_limit": INVENTORY_CAPACITY_LIMIT,
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
    validated_state = _validate_land_state(state)
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
        is_occupied=_is_plot_occupied(validated_state),
    )
    db.add(db_plot)
    db.commit()
    db.refresh(db_plot)
    return db_plot


def update_land_plot_state(db: Session, land_plot: models.LandPlot, new_state: str) -> models.LandPlot:
    validated_state = _validate_land_state(new_state)

    if validated_state == "planted" and land_plot.is_occupied:
        raise ValueError("Plot is already occupied")

    land_plot.state = validated_state
    land_plot.is_occupied = _is_plot_occupied(validated_state)
    db.commit()
    db.refresh(land_plot)
    return land_plot
