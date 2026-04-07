from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_DB_PATH = DATA_DIR / "inventory.db"
DB_PATH = Path(os.getenv("INVENTORY_DB_PATH", DEFAULT_DB_PATH))

DATE_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_LOOKBACK_DAYS = int(os.getenv("DEFAULT_LOOKBACK_DAYS", "30"))
DEFAULT_CURRENCY = os.getenv("INVENTORY_CURRENCY", "VND")
