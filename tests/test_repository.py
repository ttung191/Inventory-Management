from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from inventory.database import InventoryRepository
from inventory.exceptions import StockUnderflowError


class RepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_inventory.db"
        self.repo = InventoryRepository(self.db_path)
        self.repo.init_db(reset=True)
        self.repo.upsert_item(
            item_code="CAT_VANG",
            item_name="Cát vàng hạt lớn",
            category="Cát",
            unit="m3",
            safe_stock=100,
            reorder_point=150,
            target_stock=400,
            lead_time_days=4,
            cost_price=250000,
            sell_price=320000,
            supplier_name="Mỏ cát A",
            is_active=True,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_record_inbound_and_outbound_updates_stock(self) -> None:
        self.repo.record_transaction("IN", "CAT_VANG", 300, partner="NCC", unit_price=250000)
        self.repo.record_transaction("OUT", "CAT_VANG", 80, partner="CT A", unit_price=320000)

        stock = self.repo.get_stock_snapshot()
        row = stock.loc[stock["item_code"] == "CAT_VANG"].iloc[0]
        self.assertEqual(float(row["quantity_on_hand"]), 220.0)

        transactions = self.repo.get_transactions()
        self.assertEqual(len(transactions), 2)

    def test_outbound_cannot_make_stock_negative(self) -> None:
        self.repo.record_transaction("IN", "CAT_VANG", 40, partner="NCC", unit_price=250000)

        with self.assertRaises(StockUnderflowError):
            self.repo.record_transaction("OUT", "CAT_VANG", 50, partner="CT A", unit_price=320000)

    def test_upsert_existing_item_keeps_code_and_updates_fields(self) -> None:
        self.repo.upsert_item(
            item_code="CAT_VANG",
            item_name="Cát vàng sông",
            category="Cát",
            unit="m3",
            safe_stock=120,
            reorder_point=180,
            target_stock=420,
            lead_time_days=5,
            cost_price=255000,
            sell_price=330000,
            supplier_name="Mỏ cát B",
            is_active=True,
        )
        item = self.repo.get_item("CAT_VANG")
        self.assertEqual(item["item_name"], "Cát vàng sông")
        self.assertEqual(float(item["target_stock"]), 420.0)


if __name__ == "__main__":
    unittest.main()
