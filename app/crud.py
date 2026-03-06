from sqlalchemy.orm import Session

from . import auth, models


ALLOWED_TRANSACTION_TYPES = {"deposit", "expense"}


def get_player_by_username(db: Session, username: str) -> models.Player | None:
    return db.query(models.Player).filter(models.Player.username == username).first()


def create_player(db: Session, username: str, password: str) -> models.Player:
    hashed_password = auth.hash_password(password)
    db_player = models.Player(
        username=username,
        hashed_password=hashed_password
    )

    try:
        db.add(db_player)
        db.flush()

        db_inventory = models.Inventory(player_id=db_player.id)
        db.add(db_inventory)

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


def get_or_create_inventory(db: Session, player_id: int) -> models.Inventory:
    db_inventory = get_inventory_by_player_id(db, player_id)
    if db_inventory is not None:
        return db_inventory

    db_inventory = models.Inventory(player_id=player_id)
    db.add(db_inventory)
    db.commit()
    db.refresh(db_inventory)
    return db_inventory
