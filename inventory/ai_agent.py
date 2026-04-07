from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=False)

try:
    from google import genai
except Exception:
    genai = None

API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
MODEL_NAME = (os.getenv("GEMINI_MODEL") or "gemini-2.5-flash").strip()

CLIENT = None
CLIENT_INIT_ERROR = None

if genai is None:
    CLIENT_INIT_ERROR = "Chưa import được package 'google.genai'. Hãy cài: pip install google-genai"
elif not API_KEY:
    CLIENT_INIT_ERROR = f"Không tìm thấy GEMINI_API_KEY trong file {ENV_PATH}"
else:
    try:
        CLIENT = genai.Client(api_key=API_KEY)
    except Exception as exc:
        CLIENT_INIT_ERROR = f"Không khởi tạo được Gemini client: {exc}"


def _safe_to_datetime(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce")


def _extract_text_from_response(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()

    candidates = getattr(response, "candidates", None)
    if candidates:
        chunks: list[str] = []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            if not content:
                continue
            parts = getattr(content, "parts", None) or []
            for part in parts:
                part_text = getattr(part, "text", None)
                if isinstance(part_text, str) and part_text.strip():
                    chunks.append(part_text.strip())
        if chunks:
            return "\n".join(chunks).strip()

    return ""


def get_debug_status() -> dict[str, Any]:
    key_masked = ""
    if API_KEY:
        if len(API_KEY) <= 8:
            key_masked = "*" * len(API_KEY)
        else:
            key_masked = f"{API_KEY[:4]}...{API_KEY[-4:]}"

    return {
        "env_path": str(ENV_PATH),
        "env_exists": ENV_PATH.exists(),
        "sdk_import_ok": genai is not None,
        "has_api_key": bool(API_KEY),
        "api_key_masked": key_masked,
        "model_name": MODEL_NAME,
        "client_ready": CLIENT is not None,
        "client_init_error": CLIENT_INIT_ERROR,
    }


def test_gemini_connection() -> dict[str, Any]:
    status = get_debug_status().copy()

    if CLIENT is None:
        status["ok"] = False
        status["message"] = CLIENT_INIT_ERROR or "Gemini client chưa sẵn sàng"
        return status

    try:
        response = CLIENT.models.generate_content(
            model=MODEL_NAME,
            contents="Hãy trả lời đúng duy nhất một từ: OK",
        )
        text = _extract_text_from_response(response)
        status["ok"] = bool(text)
        status["message"] = text or "Gemini trả response nhưng không có text"
        return status
    except Exception as exc:
        status["ok"] = False
        status["message"] = f"Lỗi gọi Gemini test: {exc}"
        return status


def _build_replenishment_summary(
    df_stock: pd.DataFrame,
    df_dm: pd.DataFrame,
    df_history: pd.DataFrame,
) -> list[str]:
    lines: list[str] = []
    history = df_history.copy()
    if history.empty:
        return lines

    history["Ngay_Giao_Dich"] = _safe_to_datetime(history["Ngay_Giao_Dich"])
    history["So_Luong"] = pd.to_numeric(history["So_Luong"], errors="coerce").fillna(0)

    now = pd.Timestamp.now().normalize()
    since = now - pd.Timedelta(days=30)
    recent = history[
        (history["Loai_GD"] == "Xuat")
        & (history["Ngay_Giao_Dich"] >= since)
    ]

    merged = df_stock.merge(df_dm, on="Ma_Hang", how="left")
    merged["So_Luong_Ton"] = pd.to_numeric(
        merged["So_Luong_Ton"], errors="coerce"
    ).fillna(0)
    merged["Nguong_An_Toan"] = pd.to_numeric(
        merged["Nguong_An_Toan"], errors="coerce"
    ).fillna(0)

    for _, row in merged.iterrows():
        sold = recent.loc[recent["Ma_Hang"] == row["Ma_Hang"], "So_Luong"].sum()
        avg_daily = sold / 30
        if avg_daily <= 0:
            continue

        days_cover = row["So_Luong_Ton"] / avg_daily
        lines.append(
            f"- {row['Ten_Hang']}: tiêu thụ TB 30 ngày {avg_daily:.1f} m3/ngày, tồn hiện tại đủ khoảng {days_cover:.1f} ngày."
        )

    return lines


def _fallback_response(
    user_query: str,
    df_stock: pd.DataFrame,
    df_dm: pd.DataFrame,
    df_history: pd.DataFrame,
    extra_debug: str | None = None,
) -> str:
    merged = df_stock.merge(df_dm, on="Ma_Hang", how="left")
    merged["So_Luong_Ton"] = pd.to_numeric(
        merged["So_Luong_Ton"], errors="coerce"
    ).fillna(0)
    merged["Nguong_An_Toan"] = pd.to_numeric(
        merged["Nguong_An_Toan"], errors="coerce"
    ).fillna(0)

    history = df_history.copy()
    if not history.empty:
        history["Ngay_Giao_Dich"] = _safe_to_datetime(history["Ngay_Giao_Dich"])
        history["So_Luong"] = pd.to_numeric(
            history["So_Luong"], errors="coerce"
        ).fillna(0)

    low_items = merged[merged["So_Luong_Ton"] <= merged["Nguong_An_Toan"]].copy()
    latest = history.head(8)
    q = (user_query or "").lower()
    lines: list[str] = []

    if "kiểm kê" in q or "điều chỉnh" in q:
        lines.append(
            "Bạn có thể dùng tab Kiểm kê & Điều chỉnh để nhập số lượng thực tế và ghi nhận chênh lệch ngay vào hệ thống."
        )

    if "nhập" in q or "mua" in q or "reorder" in q or "cần nhập" in q:
        if low_items.empty:
            lines.append("Hiện chưa có mặt hàng nào xuống dưới ngưỡng an toàn, chưa cần nhập gấp.")
        else:
            for _, row in low_items.iterrows():
                deficit = max(float(row["Nguong_An_Toan"]) - float(row["So_Luong_Ton"]), 0)
                lines.append(
                    f"- {row['Ten_Hang']}: tồn {row['So_Luong_Ton']:.1f} m3, thấp hơn ngưỡng {row['Nguong_An_Toan']:.1f} m3. Nên nhập thêm tối thiểu {deficit + 80:.1f} m3."
                )

    if ("xuất" in q or "bán" in q or "ban" in q) and not history.empty:
        recent_out = history[history["Loai_GD"] == "Xuat"].copy()
        if not recent_out.empty:
            summary = recent_out.groupby("Ma_Hang", as_index=False)["So_Luong"].sum()
            for _, row in summary.iterrows():
                ten_hang = df_dm.loc[
                    df_dm["Ma_Hang"] == row["Ma_Hang"], "Ten_Hang"
                ].iloc[0]
                lines.append(f"- Tổng xuất gần đây của {ten_hang}: {row['So_Luong']:.1f} m3.")

    if "đối tác" in q or "khách" in q or "nhà cung cấp" in q:
        if not history.empty:
            recent_by_partner = (
                history.groupby(["Loai_GD", "Doi_Tac"], as_index=False)["So_Luong"]
                .sum()
                .sort_values("So_Luong", ascending=False)
                .head(6)
            )
            for _, row in recent_by_partner.iterrows():
                lines.append(f"- {row['Loai_GD']} / {row['Doi_Tac']}: {row['So_Luong']:.1f} m3.")

    if ("tồn" in q or "ton" in q or "kho" in q or "stock" in q) or not lines:
        for _, row in merged.iterrows():
            status = "an toàn"
            if row["So_Luong_Ton"] <= row["Nguong_An_Toan"]:
                status = "cần theo dõi sát"
            lines.append(
                f"- {row['Ten_Hang']}: tồn {row['So_Luong_Ton']:.1f} m3, ngưỡng an toàn {row['Nguong_An_Toan']:.1f} m3, trạng thái {status}."
            )

    lines.extend(_build_replenishment_summary(df_stock, df_dm, df_history)[:2])

    if not latest.empty:
        last_time = latest.iloc[0]["Ngay_Giao_Dich"]
        last_row = latest.iloc[0]
        if pd.notna(last_time):
            lines.append(
                f"- Giao dịch mới nhất: {last_row['Loai_GD']} {last_row['So_Luong']:.1f} m3 {last_row['Ma_Hang']} lúc {last_time.strftime('%d/%m/%Y %H:%M')}."
            )

    header = "⚙️ Chế độ phản hồi nội bộ"
    if extra_debug:
        header += f" | Debug: {extra_debug}"

    return header + "\n" + "\n".join(lines[:10])


def get_copilot_response(
    user_query: str,
    df_stock: pd.DataFrame,
    df_dm: pd.DataFrame,
    df_history: pd.DataFrame,
) -> str:
    if CLIENT is None:
        return _fallback_response(
            user_query,
            df_stock,
            df_dm,
            df_history,
            extra_debug=CLIENT_INIT_ERROR or "Gemini client chưa sẵn sàng",
        )

    stock_info = (
        df_stock.merge(df_dm, on="Ma_Hang")[
            ["Ten_Hang", "So_Luong_Ton", "Nguong_An_Toan"]
        ]
        .to_string(index=False)
    )
    recent_history = df_history.head(12).to_string(index=False)

    prompt = f"""
Bạn là AI Copilot chuyên quản lý kho cát xây dựng.
Hệ thống này CHỈ quản lý 2 mặt hàng cố định: Cát vàng hạt lớn và Cát xây tô.

[TỒN KHO]
{stock_info}

[12 GIAO DỊCH GẦN NHẤT]
{recent_history}

Yêu cầu:
- Trả lời ngắn gọn bằng tiếng Việt.
- Tập trung vào cảnh báo nhập thêm, rủi ro âm hàng, nhịp xuất bán, đối soát tồn thực tế và khuyến nghị hành động.
- Không đề xuất mở rộng thêm mặt hàng khác.

Câu hỏi người dùng: {user_query}
"""

    try:
        response = CLIENT.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
        )

        text = _extract_text_from_response(response)
        if text:
            return text

        finish_reason = None
        candidates = getattr(response, "candidates", None)
        if candidates:
            finish_reason = getattr(candidates[0], "finish_reason", None)

        return _fallback_response(
            user_query,
            df_stock,
            df_dm,
            df_history,
            extra_debug=f"Gemini trả response rỗng, finish_reason={finish_reason}",
        )
    except Exception as exc:
        return _fallback_response(
            user_query,
            df_stock,
            df_dm,
            df_history,
            extra_debug=f"Lỗi gọi Gemini: {exc}",
        )