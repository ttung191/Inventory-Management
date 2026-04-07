from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from inventory.database import InventoryRepository
from inventory.demo_seed import seed_demo_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Khởi tạo dữ liệu demo cho hệ thống inventory.")
    parser.add_argument("--days", type=int, default=240, help="Số ngày lịch sử muốn seed.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Xóa dữ liệu cũ trước khi tạo lại toàn bộ dữ liệu demo.",
    )
    args = parser.parse_args()

    repo = InventoryRepository()
    seed_demo_data(repo=repo, reset=args.reset, days=args.days)
    summary = repo.summary_counts()
    print("✅ Hoàn tất khởi tạo dữ liệu demo.")
    print(f"- Active SKU: {int(summary['items'])}")
    print(f"- Transactions: {int(summary['transactions'])}")
    print(f"- Inventory value: {summary['inventory_value']:,.0f}")


if __name__ == "__main__":
    main()
