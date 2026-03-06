from collections.abc import Generator

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from . import auth, crud, database, models, schemas

models.Base.metadata.create_all(bind=database.engine)

app = FastAPI()


def get_db() -> Generator[Session, None, None]:
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.post("/register", response_model=schemas.PlayerResponse)
def register(player: schemas.PlayerCreate, db: Session = Depends(get_db)):
    db_player = crud.get_player_by_username(db, player.username)
    if db_player is not None:
        raise HTTPException(status_code=400, detail="Username already registered")

    return crud.create_player(db, player.username, player.password)


@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    db_player = crud.get_player_by_username(db, form_data.username)

    if db_player is None:
        raise HTTPException(status_code=400, detail="Invalid credentials")

    if not auth.verify_password(form_data.password, db_player.hashed_password):
        raise HTTPException(status_code=400, detail="Invalid credentials")

    access_token = auth.create_access_token(data={"sub": db_player.username})
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("/me", response_model=schemas.PlayerResponse)
def get_me(username: str = Depends(auth.get_current_username), db: Session = Depends(get_db)):
    db_player = crud.get_player_by_username(db, username)

    if db_player is None:
        raise HTTPException(status_code=404, detail="Player not found")

    return db_player


@app.post("/wallet/deposit", response_model=schemas.PlayerResponse)
def wallet_deposit(
    deposit: schemas.WalletDepositRequest,
    username: str = Depends(auth.get_current_username),
    db: Session = Depends(get_db),
):
    db_player = crud.get_player_by_username(db, username)

    if db_player is None:
        raise HTTPException(status_code=404, detail="Player not found")

    return crud.deposit_balance(db, db_player, deposit.amount)


@app.get("/wallet/history", response_model=list[schemas.WalletTransactionResponse])
def wallet_history(
    username: str = Depends(auth.get_current_username),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    db_player = crud.get_player_by_username(db, username)

    if db_player is None:
        raise HTTPException(status_code=404, detail="Player not found")

    return crud.get_wallet_history_by_player_id(db, db_player.id, limit=limit, offset=offset)


@app.get("/inventory/me", response_model=schemas.InventoryResponse)
def get_my_inventory(username: str = Depends(auth.get_current_username), db: Session = Depends(get_db)):
    db_player = crud.get_player_by_username(db, username)
    if db_player is None:
        raise HTTPException(status_code=404, detail="Player not found")

    db_inventory = crud.get_or_create_inventory(db, db_player.id)
    return db_inventory
