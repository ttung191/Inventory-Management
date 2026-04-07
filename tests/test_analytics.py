from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from inventory.analytics import build_kpis, compute_stock_health
from inventory.database import InventoryRepository
from inventory.demo_seed import seed_demo_data


class AnalyticsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "analytics_inventory.db"
        self.repo = InventoryRepository(self.db_path)
        seed_demo_data(repo=self.repo, reset=True, days=45, seed=9)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_compute_stock_health_has_expected_columns(self) -> None:
        stock = self.repo.get_stock_snapshot()
        transactions = self.repo.get_transactions()
        health = compute_stock_health(stock, transactions, lookback_days=30)

        self.assertFalse(health.empty)
        self.assertIn("suggested_reorder_qty", health.columns)
        self.assertIn("days_remaining", health.columns)
        self.assertTrue((health["suggested_reorder_qty"] >= 0).all())

    def test_build_kpis_returns_inventory_value(self) -> None:
        stock = self.repo.get_stock_snapshot()
        transactions = self.repo.get_transactions()
        health = compute_stock_health(stock, transactions, lookback_days=30)
        kpis = build_kpis(health, transactions)

        self.assertGreater(kpis["active_sku"], 0)
        self.assertGreater(kpis["inventory_value"], 0)
        self.assertGreater(kpis["transaction_count"], 0)


if __name__ == "__main__":
    unittest.main()
