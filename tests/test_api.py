import shutil
import unittest
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import close_all_sessions, sessionmaker

from app import database, main, models


class APITestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir_path = Path("tests_tmp") / uuid4().hex
        self.temp_dir_path.mkdir(parents=True, exist_ok=True)
        db_path = self.temp_dir_path / "test.db"
        self.test_engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        self.TestingSessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.test_engine,
        )
        models.Base.metadata.create_all(bind=self.test_engine)

        self.original_engine = database.engine
        self.original_session_local = database.SessionLocal
        database.engine = self.test_engine
        database.SessionLocal = self.TestingSessionLocal

        def override_get_db():
            db = self.TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        main.app.dependency_overrides[main.get_db] = override_get_db
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        self.client.close()
        main.app.dependency_overrides.clear()
        database.SessionLocal = self.original_session_local
        database.engine = self.original_engine
        close_all_sessions()
        self.test_engine.dispose()
        self.original_engine.dispose()
        shutil.rmtree(self.temp_dir_path, ignore_errors=True)

    def _register_and_login(self) -> tuple[dict[str, str], dict]:
        unique_suffix = uuid4().hex[:8]
        username = f"test_{unique_suffix}"
        email = f"{username}@example.com"
        password = "12345"

        register_response = self.client.post(
            "/register",
            json={"username": username, "email": email, "password": password},
        )
        self.assertEqual(register_response.status_code, 200, register_response.text)

        login_response = self.client.post(
            "/login",
            data={"username": username, "password": password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(login_response.status_code, 200, login_response.text)
        token_payload = login_response.json()
        headers = {"Authorization": f"Bearer {token_payload['access_token']}"}
        return headers, token_payload

    def _db_session(self):
        return self.TestingSessionLocal()

    @staticmethod
    def _idempotency_headers(headers: dict[str, str], key: str) -> dict[str, str]:
        return {**headers, "Idempotency-Key": key}

    def test_auth_profile_progression_and_logout(self) -> None:
        headers, tokens = self._register_and_login()

        me_response = self.client.get("/me", headers=headers)
        self.assertEqual(me_response.status_code, 200, me_response.text)
        me_payload = me_response.json()
        self.assertIn("username", me_payload)
        self.assertEqual(me_payload["balance"], 100.0)

        profile_response = self.client.get("/profile/me", headers=headers)
        self.assertEqual(profile_response.status_code, 200, profile_response.text)
        profile_payload = profile_response.json()
        self.assertEqual(profile_payload["username"], me_payload["username"])
        self.assertEqual(profile_payload["stats"]["level"], 1)

        progression_response = self.client.get("/progression/me", headers=headers)
        self.assertEqual(progression_response.status_code, 200, progression_response.text)
        progression_payload = progression_response.json()
        self.assertEqual(progression_payload["username"], me_payload["username"])
        self.assertEqual(progression_payload["wealth_xp"], 142.25)
        self.assertEqual(progression_payload["level"], 1)
        self.assertEqual(progression_payload["farm_size"], 3)

        refresh_response = self.client.post(
            "/token/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        self.assertEqual(refresh_response.status_code, 200, refresh_response.text)
        refreshed_tokens = refresh_response.json()
        self.assertIn("access_token", refreshed_tokens)
        self.assertNotEqual(refreshed_tokens["refresh_token"], tokens["refresh_token"])

        logout_response = self.client.post(
            "/logout",
            json={"refresh_token": refreshed_tokens["refresh_token"]},
            headers={"Authorization": f"Bearer {refreshed_tokens['access_token']}"},
        )
        self.assertEqual(logout_response.status_code, 200, logout_response.text)

        revoked_response = self.client.get(
            "/me",
            headers={"Authorization": f"Bearer {refreshed_tokens['access_token']}"},
        )
        self.assertEqual(revoked_response.status_code, 401, revoked_response.text)

    def test_storage_routes_and_validation_errors(self) -> None:
        headers, _tokens = self._register_and_login()

        storage_response = self.client.get("/storage/me", headers=headers)
        inventory_alias_response = self.client.get("/inventory/me", headers=headers)
        self.assertEqual(storage_response.status_code, 200, storage_response.text)
        self.assertEqual(inventory_alias_response.status_code, 200, inventory_alias_response.text)
        self.assertEqual(storage_response.json(), inventory_alias_response.json())

        invalid_item_response = self.client.post(
            "/inventory/items/add",
            json={"item_code": "does_not_exist", "quantity": 1},
            headers=self._idempotency_headers(headers, "storage-invalid-1"),
        )
        self.assertEqual(invalid_item_response.status_code, 400, invalid_item_response.text)
        self.assertEqual(invalid_item_response.json()["detail"], "Item code not found")

        overflow_response = self.client.post(
            "/inventory/items/add",
            json={"item_code": "wheat", "quantity": 1000},
            headers=self._idempotency_headers(headers, "storage-overflow-1"),
        )
        self.assertEqual(overflow_response.status_code, 409, overflow_response.text)
        self.assertEqual(overflow_response.json()["detail"], "Storage capacity exceeded")

    def test_crop_lifecycle_harvest_and_land_snapshot(self) -> None:
        headers, _tokens = self._register_and_login()

        land_response = self.client.get("/land/me", headers=headers)
        self.assertEqual(land_response.status_code, 200, land_response.text)
        first_plot = land_response.json()["plots"][0]

        plant_response = self.client.post(
            "/crops/plant",
            json={"crop_type_code": "wheat", "plot_id": first_plot["id"]},
            headers=self._idempotency_headers(headers, "plant-wheat-1"),
        )
        self.assertEqual(plant_response.status_code, 200, plant_response.text)
        crop_payload = plant_response.json()
        crop_id = crop_payload["id"]

        occupied_plot_response = self.client.patch(
            f"/land/plots/{first_plot['id']}/state",
            json={"state": "plowed"},
            headers=headers,
        )
        self.assertEqual(occupied_plot_response.status_code, 409, occupied_plot_response.text)
        self.assertEqual(
            occupied_plot_response.json()["detail"],
            "Occupied plots cannot be changed manually",
        )

        farm_snapshot_response = self.client.get("/land/me", headers=headers)
        self.assertEqual(farm_snapshot_response.status_code, 200, farm_snapshot_response.text)
        planted_plot = next(
            plot for plot in farm_snapshot_response.json()["plots"] if plot["id"] == first_plot["id"]
        )
        self.assertTrue(planted_plot["is_occupied"])
        self.assertIsNotNone(planted_plot["crop"])
        self.assertEqual(planted_plot["crop"]["crop_type_code"], "wheat")

        early_harvest_response = self.client.post(
            f"/crops/{crop_id}/harvest",
            headers=self._idempotency_headers(headers, "harvest-early-1"),
        )
        self.assertEqual(early_harvest_response.status_code, 409, early_harvest_response.text)
        self.assertEqual(early_harvest_response.json()["detail"], "Crop is not ready for harvest")

        with self._db_session() as db:
            db_crop = db.query(models.PlayerCrop).filter(models.PlayerCrop.id == crop_id).first()
            self.assertIsNotNone(db_crop)
            assert db_crop is not None
            db_crop.planted_at = db_crop.planted_at - timedelta(seconds=db_crop.crop_type.growth_time_seconds + 1)
            db.commit()

        harvest_response = self.client.post(
            f"/crops/{crop_id}/harvest",
            headers=self._idempotency_headers(headers, "harvest-ready-1"),
        )
        self.assertEqual(harvest_response.status_code, 200, harvest_response.text)
        harvest_payload = harvest_response.json()
        self.assertEqual(harvest_payload["crop"]["state"], "harvested")
        harvested_items = [
            item
            for category in harvest_payload["storage"]["categories"]
            for item in category["items"]
            if item["code"] == "wheat"
        ]
        self.assertTrue(harvested_items)
        self.assertGreaterEqual(harvested_items[0]["quantity"], 2)

        cleared_land_response = self.client.get("/land/me", headers=headers)
        self.assertEqual(cleared_land_response.status_code, 200, cleared_land_response.text)
        cleared_plot = next(
            plot for plot in cleared_land_response.json()["plots"] if plot["id"] == first_plot["id"]
        )
        self.assertFalse(cleared_plot["is_occupied"])
        self.assertIsNone(cleared_plot["crop"])

    def test_land_expansion_and_weekly_tax_application(self) -> None:
        headers, _tokens = self._register_and_login()

        expand_response = self.client.post(
            "/land/expand",
            json={},
            headers=self._idempotency_headers(headers, "expand-tier-1"),
        )
        self.assertEqual(expand_response.status_code, 200, expand_response.text)
        expand_payload = expand_response.json()
        self.assertEqual(expand_payload["previous_farm_size"], 3)
        self.assertEqual(expand_payload["new_farm_size"], 4)
        self.assertEqual(expand_payload["price_paid"], 50.0)
        self.assertEqual(expand_payload["weekly_land_tax"], 14.0)
        self.assertEqual(expand_payload["balance"], 50.0)

        progression_before_tax = self.client.get("/progression/me", headers=headers)
        self.assertEqual(progression_before_tax.status_code, 200, progression_before_tax.text)
        progression_payload = progression_before_tax.json()
        self.assertEqual(progression_payload["breakdown"]["balance_wealth"], 50.0)

        with self._db_session() as db:
            db_player = db.query(models.Player).filter(models.Player.username == progression_payload["username"]).first()
            self.assertIsNotNone(db_player)
            assert db_player is not None
            db_stats = db.query(models.PlayerStats).filter(models.PlayerStats.player_id == db_player.id).first()
            self.assertIsNotNone(db_stats)
            assert db_stats is not None
            db_stats.last_land_tax_at = db_stats.last_land_tax_at - timedelta(days=14)
            db.commit()

        taxed_land_response = self.client.get("/land/me", headers=headers)
        self.assertEqual(taxed_land_response.status_code, 200, taxed_land_response.text)
        taxed_land_payload = taxed_land_response.json()
        self.assertEqual(taxed_land_payload["weekly_land_tax"], 14.0)
        self.assertEqual(taxed_land_payload["farm_size"], 4)

        progression_after_tax = self.client.get("/progression/me", headers=headers)
        self.assertEqual(progression_after_tax.status_code, 200, progression_after_tax.text)
        self.assertEqual(progression_after_tax.json()["breakdown"]["balance_wealth"], 22.0)
        self.assertEqual(progression_after_tax.json()["land_tax_due_now"], 0.0)

        history_response = self.client.get("/wallet/history", headers=headers)
        self.assertEqual(history_response.status_code, 200, history_response.text)
        transactions = history_response.json()
        self.assertEqual(len(transactions), 2)
        self.assertEqual(transactions[0]["transaction_type"], "expense")
        self.assertEqual(transactions[0]["amount"], 28.0)
        self.assertEqual(transactions[1]["transaction_type"], "expense")
        self.assertEqual(transactions[1]["amount"], 50.0)


    def test_idempotent_deposit_and_expand_do_not_duplicate_effects(self) -> None:
        headers, _tokens = self._register_and_login()

        first_deposit = self.client.post(
            "/wallet/deposit",
            json={"amount": 25},
            headers=self._idempotency_headers(headers, "deposit-25"),
        )
        self.assertEqual(first_deposit.status_code, 200, first_deposit.text)
        self.assertEqual(first_deposit.json()["balance"], 125.0)

        repeated_deposit = self.client.post(
            "/wallet/deposit",
            json={"amount": 25},
            headers=self._idempotency_headers(headers, "deposit-25"),
        )
        self.assertEqual(repeated_deposit.status_code, 200, repeated_deposit.text)
        self.assertEqual(repeated_deposit.json()["balance"], 125.0)

        conflicting_deposit = self.client.post(
            "/wallet/deposit",
            json={"amount": 30},
            headers=self._idempotency_headers(headers, "deposit-25"),
        )
        self.assertEqual(conflicting_deposit.status_code, 409, conflicting_deposit.text)
        self.assertEqual(
            conflicting_deposit.json()["detail"],
            "Idempotency key already used with a different payload",
        )

        first_expand = self.client.post(
            "/land/expand",
            json={},
            headers=self._idempotency_headers(headers, "expand-tier-repeat"),
        )
        self.assertEqual(first_expand.status_code, 200, first_expand.text)
        self.assertEqual(first_expand.json()["new_farm_size"], 4)
        self.assertEqual(first_expand.json()["balance"], 75.0)

        repeated_expand = self.client.post(
            "/land/expand",
            json={},
            headers=self._idempotency_headers(headers, "expand-tier-repeat"),
        )
        self.assertEqual(repeated_expand.status_code, 200, repeated_expand.text)
        self.assertEqual(repeated_expand.json()["new_farm_size"], 4)
        self.assertEqual(repeated_expand.json()["balance"], 75.0)

        history_response = self.client.get("/wallet/history", headers=headers)
        self.assertEqual(history_response.status_code, 200, history_response.text)
        transactions = history_response.json()
        self.assertEqual(len(transactions), 2)
        self.assertEqual(transactions[0]["transaction_type"], "expense")
        self.assertEqual(transactions[0]["amount"], 50.0)
        self.assertEqual(transactions[1]["transaction_type"], "deposit")
        self.assertEqual(transactions[1]["amount"], 25.0)

if __name__ == "__main__":
    unittest.main()
