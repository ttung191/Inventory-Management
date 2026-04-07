from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import pandas as pd


def _ensure_datetime(df: pd.DataFrame, column: str) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    result = df.copy()
    result[column] = pd.to_datetime(result[column])
    return result


def build_daily_movement(transactions: pd.DataFrame, transaction_type: Optional[str] = None) -> pd.DataFrame:
    if transactions.empty:
        return pd.DataFrame(
            columns=["movement_date", "item_code", "item_name", "transaction_type", "quantity", "total_value"]
        )

    df = _ensure_datetime(transactions, "occurred_at")
    if transaction_type:
        df = df[df["transaction_type"] == transaction_type.upper()].copy()
    if df.empty:
        return pd.DataFrame(
            columns=["movement_date", "item_code", "item_name", "transaction_type", "quantity", "total_value"]
        )

    df["movement_date"] = df["occurred_at"].dt.date
    grouped = (
        df.groupby(["movement_date", "item_code", "item_name", "transaction_type"], as_index=False)[
            ["quantity", "total_value"]
        ]
        .sum()
        .sort_values("movement_date")
    )
    return grouped


def build_monthly_summary(transactions: pd.DataFrame) -> pd.DataFrame:
    if transactions.empty:
        return pd.DataFrame(
            columns=[
                "month",
                "qty_in",
                "qty_out",
                "net_qty",
                "value_in",
                "value_out",
            ]
        )

    df = _ensure_datetime(transactions, "occurred_at")
    df["month"] = df["occurred_at"].dt.to_period("M").astype(str)
    df["qty_in"] = df["quantity"].where(df["transaction_type"] == "IN", 0.0)
    df["qty_out"] = df["quantity"].where(df["transaction_type"] == "OUT", 0.0)
    df["value_in"] = df["total_value"].where(df["transaction_type"] == "IN", 0.0)
    df["value_out"] = df["total_value"].where(df["transaction_type"] == "OUT", 0.0)

    summary = (
        df.groupby("month", as_index=False)[["qty_in", "qty_out", "value_in", "value_out"]]
        .sum()
        .sort_values("month")
    )
    summary["net_qty"] = summary["qty_in"] - summary["qty_out"]
    return summary


def compute_stock_health(
    stock_snapshot: pd.DataFrame,
    transactions: pd.DataFrame,
    lookback_days: int = 30,
) -> pd.DataFrame:
    if stock_snapshot.empty:
        return pd.DataFrame()

    health = stock_snapshot.copy()
    health["avg_daily_out"] = 0.0
    health["out_qty_7d"] = 0.0
    health["out_qty_30d"] = 0.0
    health["days_remaining"] = pd.NA
    health["suggested_reorder_qty"] = 0.0
    health["urgency"] = "healthy"

    if not transactions.empty:
        tx = _ensure_datetime(transactions, "occurred_at")
        if "total_value" not in tx.columns:
            tx["total_value"] = tx["quantity"] * tx.get("unit_price", 0)

        now = tx["occurred_at"].max()
        cutoff_lookback = now - timedelta(days=int(lookback_days))
        cutoff_7d = now - timedelta(days=7)
        cutoff_30d = now - timedelta(days=30)

        out_tx = tx[tx["transaction_type"] == "OUT"].copy()

        avg_daily_out = (
            out_tx[out_tx["occurred_at"] >= cutoff_lookback]
            .groupby("item_code")["quantity"]
            .sum()
            .div(max(int(lookback_days), 1))
        )

        qty_7d = out_tx[out_tx["occurred_at"] >= cutoff_7d].groupby("item_code")["quantity"].sum()
        qty_30d = out_tx[out_tx["occurred_at"] >= cutoff_30d].groupby("item_code")["quantity"].sum()

        health["avg_daily_out"] = health["item_code"].map(avg_daily_out).fillna(0.0).round(2)
        health["out_qty_7d"] = health["item_code"].map(qty_7d).fillna(0.0).round(2)
        health["out_qty_30d"] = health["item_code"].map(qty_30d).fillna(0.0).round(2)

    def _days_remaining(row: pd.Series):
        avg_daily_out = float(row["avg_daily_out"])
        if avg_daily_out <= 0:
            return pd.NA
        return round(float(row["quantity_on_hand"]) / avg_daily_out, 1)

    def _reorder_qty(row: pd.Series) -> float:
        coverage_need = float(row["safe_stock"]) + float(row["avg_daily_out"]) * float(row["lead_time_days"])
        target_need = float(row["target_stock"])
        qty = float(row["quantity_on_hand"])
        suggested = max(coverage_need - qty, target_need - qty, 0.0)
        return round(suggested, 2)

    def _urgency(row: pd.Series) -> str:
        qty = float(row["quantity_on_hand"])
        safe_stock = float(row["safe_stock"])
        reorder_point = float(row["reorder_point"])
        days_remaining = row["days_remaining"]
        if qty <= safe_stock:
            return "critical"
        if pd.notna(days_remaining) and float(days_remaining) <= max(float(row["lead_time_days"]), 1):
            return "critical"
        if qty <= reorder_point:
            return "warning"
        if qty >= float(row["target_stock"]) * 1.2:
            return "overstock"
        return "healthy"

    health["days_remaining"] = health.apply(_days_remaining, axis=1)
    health["suggested_reorder_qty"] = health.apply(_reorder_qty, axis=1)
    health["urgency"] = health.apply(_urgency, axis=1)

    def _status(row: pd.Series) -> str:
        urgency = row["urgency"]
        return {
            "critical": "CRITICAL",
            "warning": "LOW",
            "overstock": "OVERSTOCK",
            "healthy": "HEALTHY",
        }[urgency]

    urgency_rank = {
        "critical": 0,
        "warning": 1,
        "healthy": 2,
        "overstock": 3,
    }

    health["stock_status"] = health.apply(_status, axis=1)
    health["urgency_rank"] = health["urgency"].map(urgency_rank).fillna(99).astype(int)
    return health.sort_values(["urgency_rank", "category", "item_name"]).reset_index(drop=True)


def build_kpis(stock_health: pd.DataFrame, transactions: pd.DataFrame) -> dict[str, float]:
    if stock_health.empty:
        return {
            "active_sku": 0,
            "inventory_value": 0.0,
            "critical_items": 0,
            "warning_items": 0,
            "overstock_items": 0,
            "out_value": 0.0,
            "in_value": 0.0,
            "transaction_count": 0,
        }

    kpis = {
        "active_sku": int(len(stock_health)),
        "inventory_value": float(stock_health["inventory_value"].sum()),
        "critical_items": int((stock_health["urgency"] == "critical").sum()),
        "warning_items": int((stock_health["urgency"] == "warning").sum()),
        "overstock_items": int((stock_health["urgency"] == "overstock").sum()),
        "out_value": 0.0,
        "in_value": 0.0,
        "transaction_count": 0,
    }

    if not transactions.empty:
        kpis["transaction_count"] = int(len(transactions))
        kpis["out_value"] = float(
            transactions.loc[transactions["transaction_type"] == "OUT", "total_value"].sum()
        )
        kpis["in_value"] = float(
            transactions.loc[transactions["transaction_type"] == "IN", "total_value"].sum()
        )
    return kpis


def top_movers(transactions: pd.DataFrame, transaction_type: str = "OUT", top_n: int = 10) -> pd.DataFrame:
    if transactions.empty:
        return pd.DataFrame(columns=["item_name", "quantity", "total_value"])

    df = transactions[transactions["transaction_type"] == transaction_type.upper()].copy()
    if df.empty:
        return pd.DataFrame(columns=["item_name", "quantity", "total_value"])

    movers = (
        df.groupby("item_name", as_index=False)[["quantity", "total_value"]]
        .sum()
        .sort_values(["quantity", "total_value"], ascending=False)
        .head(top_n)
    )
    return movers


def generate_business_alerts(stock_health: pd.DataFrame) -> list[str]:
    if stock_health.empty:
        return ["Chưa có dữ liệu tồn kho để phân tích."]

    alerts: list[str] = []
    critical = stock_health[stock_health["urgency"] == "critical"]
    warning = stock_health[stock_health["urgency"] == "warning"]
    overstock = stock_health[stock_health["urgency"] == "overstock"]

    for _, row in critical.iterrows():
        message = (
            f"Khẩn cấp: {row['item_name']} chỉ còn {row['quantity_on_hand']:.2f} {row['unit']}, "
            f"nên nhập thêm khoảng {row['suggested_reorder_qty']:.2f} {row['unit']}."
        )
        alerts.append(message)

    for _, row in warning.head(3).iterrows():
        alerts.append(
            f"Cảnh báo: {row['item_name']} đã chạm vùng reorder, cân nhắc lên đơn sớm."
        )

    for _, row in overstock.head(2).iterrows():
        alerts.append(
            f"Chú ý: {row['item_name']} đang dư tồn ({row['quantity_on_hand']:.2f} {row['unit']}); "
            "nên rà soát tốc độ bán và vòng quay."
        )

    if not alerts:
        alerts.append("Tồn kho hiện ở trạng thái ổn định, chưa có cảnh báo lớn.")
    return alerts


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    if df.empty:
        return b""
    return df.to_csv(index=False).encode("utf-8-sig")
