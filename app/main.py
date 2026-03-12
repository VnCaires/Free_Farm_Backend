from collections.abc import Generator

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import Session

from . import auth, crud, database, models, schemas

database.run_startup_migrations()
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

    db_player = crud.get_player_by_email(db, player.email)
    if db_player is not None:
        raise HTTPException(status_code=400, detail="Email already registered")

    return crud.create_player(db, player.username, player.email, player.password)


@app.post("/login", response_model=schemas.TokenResponse)
def login(
    form_data: auth.OAuth2IdentifierRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> schemas.TokenResponse:
    db_player = crud.get_player_by_login_identifier(db, form_data.username)

    if db_player is None:
        raise HTTPException(status_code=400, detail="Invalid credentials")

    if not auth.verify_password(form_data.password, db_player.hashed_password):
        raise HTTPException(status_code=400, detail="Invalid credentials")

    access_token, _access_jti, _access_expiry = auth.create_access_token(data={"sub": db_player.username})
    refresh_token, refresh_jti, refresh_expiry = auth.create_refresh_token(data={"sub": db_player.username})
    auth.store_refresh_session(db, db_player.id, refresh_jti, refresh_expiry)

    return schemas.TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
    )


@app.post("/token/refresh", response_model=schemas.TokenResponse)
def refresh_token(payload: schemas.RefreshTokenRequest, db: Session = Depends(get_db)):
    refresh_payload = auth.decode_token(payload.refresh_token, expected_type="refresh")
    refresh_username = refresh_payload["sub"]
    refresh_jti = refresh_payload["jti"]

    db_player = crud.get_player_by_username(db, refresh_username)
    if db_player is None:
        raise HTTPException(status_code=401, detail="Invalid token")

    access_token, _access_jti, _access_expiry = auth.create_access_token(data={"sub": db_player.username})
    new_refresh_token, new_refresh_jti, new_refresh_expiry = auth.create_refresh_token(
        data={"sub": db_player.username}
    )
    auth.rotate_refresh_session(
        db,
        player_id=db_player.id,
        old_jti=refresh_jti,
        new_jti=new_refresh_jti,
        new_expires_at=new_refresh_expiry,
    )

    return schemas.TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
    )


@app.post("/logout")
def logout(
    payload: schemas.LogoutRequest,
    token_payload: dict = Depends(auth.get_current_token_payload),
    db: Session = Depends(get_db),
):
    username = token_payload["sub"]
    access_jti = token_payload["jti"]
    access_expiry = auth.get_token_expiry(token_payload)

    refresh_payload = auth.decode_token(payload.refresh_token, expected_type="refresh")
    refresh_username = refresh_payload["sub"]
    refresh_jti = refresh_payload["jti"]

    if refresh_username != username:
        raise HTTPException(status_code=401, detail="Invalid token")

    db_player = crud.get_player_by_username(db, username)
    if db_player is None:
        raise HTTPException(status_code=401, detail="Invalid token")

    auth.revoke_refresh_session(db, db_player.id, refresh_jti)
    auth.revoke_access_token(db, access_jti, access_expiry)

    return {"detail": "Logged out"}


@app.get("/me", response_model=schemas.PlayerResponse)
def get_me(username: str = Depends(auth.get_current_username), db: Session = Depends(get_db)):
    db_player = crud.get_player_by_username(db, username)

    if db_player is None:
        raise HTTPException(status_code=404, detail="Player not found")

    return db_player


@app.get("/profile/me", response_model=schemas.PlayerProfileResponse)
def get_my_profile(username: str = Depends(auth.get_current_username), db: Session = Depends(get_db)):
    db_player = crud.get_player_by_username(db, username)
    if db_player is None:
        raise HTTPException(status_code=404, detail="Player not found")

    db_profile, db_stats = crud.get_or_create_player_profile(db, db_player)
    db_stats = crud.sync_player_wealth_stats(db, db_player)
    db.commit()
    return crud.build_player_profile_response(db_player, db_profile, db_stats)


@app.patch("/profile/me", response_model=schemas.PlayerProfileResponse)
def update_my_profile(
    payload: schemas.PlayerProfileUpdateRequest,
    username: str = Depends(auth.get_current_username),
    db: Session = Depends(get_db),
):
    db_player = crud.get_player_by_username(db, username)
    if db_player is None:
        raise HTTPException(status_code=404, detail="Player not found")

    db_profile, db_stats = crud.get_or_create_player_profile(db, db_player)
    crud.update_player_profile(
        db,
        db_profile,
        display_name=payload.display_name,
        avatar_url=payload.avatar_url,
    )
    db_stats = crud.sync_player_wealth_stats(db, db_player)
    db.commit()
    return crud.build_player_profile_response(db_player, db_profile, db_stats)


@app.get("/progression/me", response_model=schemas.ProgressionResponse)
def get_my_progression(username: str = Depends(auth.get_current_username), db: Session = Depends(get_db)):
    db_player = crud.get_player_by_username(db, username)
    if db_player is None:
        raise HTTPException(status_code=404, detail="Player not found")

    return crud.get_player_progression(db, db_player)


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


@app.get("/inventory/me", response_model=schemas.StorageResponse)
def get_my_inventory(username: str = Depends(auth.get_current_username), db: Session = Depends(get_db)):
    db_player = crud.get_player_by_username(db, username)
    if db_player is None:
        raise HTTPException(status_code=404, detail="Player not found")

    db_storage = crud.get_or_create_storage(db, db_player.id)
    return crud.get_storage_structured(db, db_storage)


@app.post("/inventory/items/add", response_model=schemas.StorageResponse)
def add_inventory_item(
    payload: schemas.InventoryAddItemRequest,
    username: str = Depends(auth.get_current_username),
    db: Session = Depends(get_db),
):
    db_player = crud.get_player_by_username(db, username)
    if db_player is None:
        raise HTTPException(status_code=404, detail="Player not found")

    db_storage = crud.get_or_create_storage(db, db_player.id)

    try:
        crud.add_item_to_storage(db, db_storage, payload.item_code, payload.quantity)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return crud.get_storage_structured(db, db_storage)


@app.get("/storage/me", response_model=schemas.StorageResponse)
def get_my_storage(username: str = Depends(auth.get_current_username), db: Session = Depends(get_db)):
    db_player = crud.get_player_by_username(db, username)
    if db_player is None:
        raise HTTPException(status_code=404, detail="Player not found")

    db_storage = crud.get_or_create_storage(db, db_player.id)
    return crud.get_storage_structured(db, db_storage)


@app.get("/crops/types", response_model=list[schemas.CropTypeResponse])
def get_crop_types(db: Session = Depends(get_db)):
    return crud.list_crop_types(db)


@app.post("/crops/plant", response_model=schemas.PlayerCropResponse)
def plant_crop(
    payload: schemas.PlantCropRequest,
    username: str = Depends(auth.get_current_username),
    db: Session = Depends(get_db),
):
    db_player = crud.get_player_by_username(db, username)
    if db_player is None:
        raise HTTPException(status_code=404, detail="Player not found")

    try:
        db_player_crop = crud.plant_crop(db, db_player, payload.crop_type_code, payload.plot_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return crud.build_player_crop_response(db_player_crop)


@app.get("/crops/me", response_model=list[schemas.PlayerCropResponse])
def get_my_crops(username: str = Depends(auth.get_current_username), db: Session = Depends(get_db)):
    db_player = crud.get_player_by_username(db, username)
    if db_player is None:
        raise HTTPException(status_code=404, detail="Player not found")

    return [crud.build_player_crop_response(player_crop) for player_crop in crud.list_player_crops(db, db_player.id)]


@app.get("/crops/{crop_id}/state", response_model=schemas.PlayerCropResponse)
def get_my_crop_state(
    crop_id: int,
    username: str = Depends(auth.get_current_username),
    db: Session = Depends(get_db),
):
    db_player = crud.get_player_by_username(db, username)
    if db_player is None:
        raise HTTPException(status_code=404, detail="Player not found")

    db_player_crop = crud.get_player_crop_by_id_for_player(db, db_player.id, crop_id)
    if db_player_crop is None:
        raise HTTPException(status_code=404, detail="Crop not found")

    return crud.build_player_crop_response(db_player_crop)


@app.post("/crops/{crop_id}/harvest", response_model=schemas.HarvestCropResponse)
def harvest_my_crop(
    crop_id: int,
    username: str = Depends(auth.get_current_username),
    db: Session = Depends(get_db),
):
    db_player = crud.get_player_by_username(db, username)
    if db_player is None:
        raise HTTPException(status_code=404, detail="Player not found")

    try:
        harvested_crop, storage = crud.harvest_crop(db, db_player, crop_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"crop": harvested_crop, "storage": storage}


@app.get("/land/me", response_model=schemas.LandGridResponse)
def get_my_land(username: str = Depends(auth.get_current_username), db: Session = Depends(get_db)):
    db_player = crud.get_player_by_username(db, username)
    if db_player is None:
        raise HTTPException(status_code=404, detail="Player not found")

    land_plots = crud.get_or_create_land_plots(db, db_player.id)
    return crud.build_land_grid_response(db, db_player.id, land_plots)


@app.post("/land/plots", response_model=schemas.LandPlotResponse)
def create_land_plot(
    payload: schemas.LandPlotCreateRequest,
    username: str = Depends(auth.get_current_username),
    db: Session = Depends(get_db),
):
    db_player = crud.get_player_by_username(db, username)
    if db_player is None:
        raise HTTPException(status_code=404, detail="Player not found")

    try:
        return crud.create_land_plot(
            db=db,
            player_id=db_player.id,
            x=payload.x,
            y=payload.y,
            soil_type=payload.soil_type,
            state=payload.state,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/land/plots/{plot_id}/state", response_model=schemas.LandPlotResponse)
def update_land_plot_state(
    plot_id: int,
    payload: schemas.LandPlotStateUpdateRequest,
    username: str = Depends(auth.get_current_username),
    db: Session = Depends(get_db),
):
    db_player = crud.get_player_by_username(db, username)
    if db_player is None:
        raise HTTPException(status_code=404, detail="Player not found")

    db_plot = crud.get_land_plot_by_id_for_player(db, db_player.id, plot_id)
    if db_plot is None:
        raise HTTPException(status_code=404, detail="Land plot not found")

    try:
        return crud.update_land_plot_state(db, db_plot, payload.state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
