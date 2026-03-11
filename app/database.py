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

        if "item_catalog" in table_names:
            item_catalog_columns = {col["name"] for col in inspector.get_columns("item_catalog")}
            if "wealth_value" not in item_catalog_columns:
                connection.execute(text("ALTER TABLE item_catalog ADD COLUMN wealth_value FLOAT NOT NULL DEFAULT 0"))

        if "player_stats" in table_names:
            player_stats_columns = {col["name"] for col in inspector.get_columns("player_stats")}
            if "wealth_xp" not in player_stats_columns:
                connection.execute(text("ALTER TABLE player_stats ADD COLUMN wealth_xp FLOAT NOT NULL DEFAULT 0"))
            if "max_wealth_xp" not in player_stats_columns:
                connection.execute(text("ALTER TABLE player_stats ADD COLUMN max_wealth_xp FLOAT NOT NULL DEFAULT 0"))
            if "level" not in player_stats_columns:
                connection.execute(text("ALTER TABLE player_stats ADD COLUMN level INTEGER NOT NULL DEFAULT 1"))

        if "crop_types" in table_names:
            crop_type_columns = {col["name"] for col in inspector.get_columns("crop_types")}
            if "seed_item_code" not in crop_type_columns:
                connection.execute(text("ALTER TABLE crop_types ADD COLUMN seed_item_code VARCHAR NOT NULL DEFAULT 'seed_wheat'"))
            if "product_item_code" not in crop_type_columns:
                connection.execute(text("ALTER TABLE crop_types ADD COLUMN product_item_code VARCHAR NOT NULL DEFAULT 'wheat'"))

