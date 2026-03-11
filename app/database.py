from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = "sqlite:///./freefarm.db"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def run_startup_migrations() -> None:
    """Lightweight SQLite-safe migrations for local development."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        table_names = set(inspector.get_table_names())

        if "players" in table_names:
            player_columns = {col["name"] for col in inspector.get_columns("players")}
            if "email" not in player_columns:
                connection.execute(text("ALTER TABLE players ADD COLUMN email VARCHAR"))
            if "email_verified" not in player_columns:
                connection.execute(
                    text("ALTER TABLE players ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT 1")
                )
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_players_email ON players (email)"))

        if "player_profiles" in table_names:
            profile_columns = {col["name"] for col in inspector.get_columns("player_profiles")}
            if "avatar_url" not in profile_columns:
                connection.execute(text("ALTER TABLE player_profiles ADD COLUMN avatar_url VARCHAR NOT NULL DEFAULT ''"))

        if "crop_types" in table_names:
            crop_type_columns = {col["name"] for col in inspector.get_columns("crop_types")}
            if "seed_item_code" not in crop_type_columns:
                connection.execute(text("ALTER TABLE crop_types ADD COLUMN seed_item_code VARCHAR NOT NULL DEFAULT 'seed_basic'"))

