# Database Diagram

Source of truth: [`app/models.py`](../app/models.py)

```mermaid
erDiagram
    PLAYERS {
        int id PK
        string username UK
        string email UK "nullable"
        boolean email_verified
        string hashed_password
        float balance
    }

    INVENTORIES {
        int id PK
        int player_id FK,UK
        int seeds
        int water
        int fertilizer
    }

    ITEM_CATALOG {
        int id PK
        string code UK
        string name
        string category
    }

    INVENTORY_ITEMS {
        int id PK
        int inventory_id FK
        int item_id FK
        int quantity
    }

    WALLET_TRANSACTIONS {
        int id PK
        int player_id FK
        string transaction_type
        float amount
        datetime created_at
    }

    PLAYER_PROFILES {
        int id PK
        int player_id FK,UK
        string display_name
        string avatar_url
        datetime created_at
    }

    PLAYER_STATS {
        int id PK
        int player_id FK,UK
        int games_played
        int crops_planted
        int crops_harvested
        float total_earnings
        float total_expenses
    }

    CROP_TYPES {
        int id PK
        string code UK
        string name UK
        int growth_time_seconds
        int yield_quantity
        float base_value
        string seed_item_code
    }

    PLAYER_CROPS {
        int id PK
        int player_id FK
        int crop_type_id FK
        int land_plot_id FK,UK
        datetime planted_at
        string state
    }

    REFRESH_SESSIONS {
        int id PK
        int player_id FK
        string jti UK
        datetime expires_at
        datetime revoked_at "nullable"
        datetime created_at
    }

    REVOKED_ACCESS_TOKENS {
        int id PK
        string jti UK
        datetime expires_at
        datetime revoked_at
    }

    LAND_PLOTS {
        int id PK
        int player_id FK
        int x
        int y
        string soil_type
        string state
        boolean is_occupied
        datetime created_at
        datetime updated_at
    }

    PLAYERS ||--|| INVENTORIES : has
    PLAYERS ||--|| PLAYER_PROFILES : has
    PLAYERS ||--|| PLAYER_STATS : has
    PLAYERS ||--o{ PLAYER_CROPS : plants
    PLAYERS ||--o{ WALLET_TRANSACTIONS : records
    PLAYERS ||--o{ REFRESH_SESSIONS : owns
    PLAYERS ||--o{ LAND_PLOTS : owns
    INVENTORIES ||--o{ INVENTORY_ITEMS : contains
    ITEM_CATALOG ||--o{ INVENTORY_ITEMS : defines
    CROP_TYPES ||--o{ PLAYER_CROPS : defines
    LAND_PLOTS ||--|| PLAYER_CROPS : hosts
```

## Notes

- Database configured in [`app/database.py`](../app/database.py) uses SQLite: `sqlite:///./freefarm.db`.
- `inventory_items` has a composite uniqueness rule on `(inventory_id, item_id)`.
- `land_plots` has a composite uniqueness rule on `(player_id, x, y)`.
- `revoked_access_tokens` is intentionally standalone and does not reference `players`.
