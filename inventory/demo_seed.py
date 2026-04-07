from __future__ import annotations

import random
from datetime import datetime, timedelta

from .database import InventoryRepository


ITEMS = [
    {
        "item_code": "CAT_VANG",
        "item_name": "Cát vàng hạt lớn",
        "category": "Cát",
        "unit": "m3",
        "safe_stock": 180,
        "reorder_point": 260,
        "target_stock": 620,
        "lead_time_days": 5,
        "cost_price": 260000,
        "sell_price": 330000,
        "supplier_name": "Mỏ cát An Phú",
        "opening_stock": 760,
        "base_daily_out": 20,
        "inbound_batch": 380,
        "partner_buyers": ["CT Nhà phố A", "CT Biệt thự B", "Khách lẻ"],
    },
    {
        "item_code": "CAT_XAY",
        "item_name": "Cát xây tô",
        "category": "Cát",
        "unit": "m3",
        "safe_stock": 140,
        "reorder_point": 210,
        "target_stock": 480,
        "lead_time_days": 4,
        "cost_price": 190000,
        "sell_price": 255000,
        "supplier_name": "Mỏ cát Sài Gòn",
        "opening_stock": 600,
        "base_daily_out": 18,
        "inbound_batch": 320,
        "partner_buyers": ["CT Chung cư C", "Khách lẻ", "Tổ đội xây tô"],
    },
    {
        "item_code": "DA_1X2",
        "item_name": "Đá 1x2",
        "category": "Đá",
        "unit": "m3",
        "safe_stock": 120,
        "reorder_point": 180,
        "target_stock": 420,
        "lead_time_days": 6,
        "cost_price": 320000,
        "sell_price": 410000,
        "supplier_name": "Mỏ đá Bình Minh",
        "opening_stock": 500,
        "base_daily_out": 12,
        "inbound_batch": 280,
        "partner_buyers": ["CT Hạ tầng D", "CT Nhà phố A", "Khách lẻ"],
    },
    {
        "item_code": "XI_MANG",
        "item_name": "Xi măng PCB40",
        "category": "Xi măng",
        "unit": "bao",
        "safe_stock": 250,
        "reorder_point": 360,
        "target_stock": 900,
        "lead_time_days": 3,
        "cost_price": 74000,
        "sell_price": 92000,
        "supplier_name": "Nhà máy Xi măng Miền Nam",
        "opening_stock": 1100,
        "base_daily_out": 28,
        "inbound_batch": 540,
        "partner_buyers": ["CT Dân dụng", "Đại lý cấp 2", "Khách lẻ"],
    },
    {
        "item_code": "GACH_ONG",
        "item_name": "Gạch ống",
        "category": "Gạch",
        "unit": "viên",
        "safe_stock": 4500,
        "reorder_point": 6500,
        "target_stock": 16000,
        "lead_time_days": 4,
        "cost_price": 1100,
        "sell_price": 1450,
        "supplier_name": "Lò gạch Đồng Tâm",
        "opening_stock": 18000,
        "base_daily_out": 550,
        "inbound_batch": 9000,
        "partner_buyers": ["CT Nhà ở E", "CT Nhà phố A", "Khách lẻ"],
    },
    {
        "item_code": "THEP_PHI10",
        "item_name": "Thép phi 10",
        "category": "Thép",
        "unit": "kg",
        "safe_stock": 1200,
        "reorder_point": 1900,
        "target_stock": 4800,
        "lead_time_days": 5,
        "cost_price": 15800,
        "sell_price": 18200,
        "supplier_name": "Nhà máy thép Hòa Phát",
        "opening_stock": 5600,
        "base_daily_out": 185,
        "inbound_batch": 2600,
        "partner_buyers": ["Xưởng cơ khí F", "CT Công nghiệp", "Đại lý phụ"],
    },
]


def _season_factor(month: int) -> float:
    if month in (7, 8):
        return 0.72
    if month in (11, 12, 1, 2):
        return 1.22
    return 1.0


def _weekday_factor(weekday: int) -> float:
    if weekday >= 5:  # Saturday/Sunday
        return 0.8
    return 1.0


def seed_demo_data(
    repo: InventoryRepository,
    reset: bool = True,
    days: int = 240,
    seed: int = 42,
) -> None:
    rng = random.Random(seed)
    repo.init_db(reset=reset)

    for item in ITEMS:
        repo.upsert_item(
            item_code=item["item_code"],
            item_name=item["item_name"],
            category=item["category"],
            unit=item["unit"],
            safe_stock=item["safe_stock"],
            reorder_point=item["reorder_point"],
            target_stock=item["target_stock"],
            lead_time_days=item["lead_time_days"],
            cost_price=item["cost_price"],
            sell_price=item["sell_price"],
            supplier_name=item["supplier_name"],
            is_active=True,
        )

    start_date = datetime.now() - timedelta(days=days)
    opening_timestamp = start_date - timedelta(days=1)

    stock_levels: dict[str, float] = {}

    for item in ITEMS:
        repo.record_transaction(
            transaction_type="IN",
            item_code=item["item_code"],
            quantity=float(item["opening_stock"]),
            partner=item["supplier_name"],
            unit_price=float(item["cost_price"]),
            notes="Opening balance / tồn đầu kỳ demo",
            occurred_at=opening_timestamp.replace(hour=8, minute=0, second=0, microsecond=0),
        )
        stock_levels[item["item_code"]] = float(item["opening_stock"])

    for day_offset in range(days + 1):
        current_day = start_date + timedelta(days=day_offset)
        season = _season_factor(current_day.month)
        weekday_scale = _weekday_factor(current_day.weekday())

        for item in ITEMS:
            code = item["item_code"]
            day_base = item["base_daily_out"] * season * weekday_scale
            # Not every day has outbound for every SKU.
            should_sell = rng.random() > 0.12
            outbound_qty = 0.0
            if should_sell:
                noise = rng.uniform(0.75, 1.30)
                outbound_qty = max(0.0, round(day_base * noise, 2))
                # Make sure outbound does not exceed available stock.
                outbound_qty = min(outbound_qty, max(stock_levels[code] * 0.4, 0.0))

            if outbound_qty > 0:
                repo.record_transaction(
                    transaction_type="OUT",
                    item_code=code,
                    quantity=outbound_qty,
                    partner=rng.choice(item["partner_buyers"]),
                    unit_price=float(item["sell_price"]),
                    notes="Bán hàng demo",
                    occurred_at=current_day.replace(
                        hour=rng.randint(7, 17),
                        minute=rng.randint(0, 59),
                        second=0,
                        microsecond=0,
                    ),
                )
                stock_levels[code] -= outbound_qty

            should_restock = (
                stock_levels[code] <= item["reorder_point"]
                or (day_offset % max(item["lead_time_days"], 1) == 0 and rng.random() > 0.93)
            )
            if should_restock:
                target = float(item["target_stock"])
                dynamic_need = max(target - stock_levels[code], float(item["inbound_batch"]))
                inbound_qty = round(dynamic_need * rng.uniform(0.90, 1.10), 2)
                repo.record_transaction(
                    transaction_type="IN",
                    item_code=code,
                    quantity=inbound_qty,
                    partner=item["supplier_name"],
                    unit_price=float(item["cost_price"]),
                    notes="Nhập hàng demo",
                    occurred_at=current_day.replace(hour=8, minute=30, second=0, microsecond=0),
                )
                stock_levels[code] += inbound_qty
