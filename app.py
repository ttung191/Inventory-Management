from datetime import timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from inventory import ai_agent
from inventory import database as db

st.set_page_config(page_title="AI Inventory Copilot", layout="wide")

with st.sidebar:
    st.subheader("Gemini Debug")
    debug = ai_agent.get_debug_status()

    st.write(
        {
            "env_exists": debug["env_exists"],
            "env_path": debug["env_path"],
            "sdk_import_ok": debug["sdk_import_ok"],
            "has_api_key": debug["has_api_key"],
            "api_key_masked": debug["api_key_masked"],
            "model_name": debug["model_name"],
            "client_ready": debug["client_ready"],
            "client_init_error": debug["client_init_error"],
        }
    )

    if st.button("Test Gemini API"):
        test_result = ai_agent.test_gemini_connection()
        if test_result.get("ok"):
            st.success(f"Gemini OK: {test_result.get('message')}")
        else:
            st.error(f"Gemini lỗi: {test_result.get('message')}")

ITEM_LABELS = {
    "CAT_VANG": "Cát vàng hạt lớn",
    "CAT_XAY": "Cát xây tô",
}
ITEM_ORDER = ["CAT_VANG", "CAT_XAY"]


def format_qty(value) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "-"
    if value.is_integer():
        return f"{value:,.0f}"
    return f"{value:,.1f}"


def _ensure_datetime(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["Ngay_Giao_Dich"] = pd.to_datetime(out["Ngay_Giao_Dich"], errors="coerce")
    out["So_Luong"] = pd.to_numeric(out["So_Luong"], errors="coerce").fillna(0)
    out = out.dropna(subset=["Ngay_Giao_Dich"]).copy()
    return out


@st.cache_data(ttl=5)
def load_data():
    df_dm = db.get_dm_hanghoa()
    df_stock = db.get_stock()
    df_history_all = _ensure_datetime(db.get_history())
    df_adjustments = _ensure_datetime(db.get_adjustment_history())

    if df_dm.empty or df_stock.empty:
        raise RuntimeError("Database chưa có dữ liệu danh mục hoặc tồn kho.")

    df_stock["So_Luong_Ton"] = pd.to_numeric(df_stock["So_Luong_Ton"], errors="coerce").fillna(0)
    df_dm["Nguong_An_Toan"] = pd.to_numeric(df_dm["Nguong_An_Toan"], errors="coerce").fillna(0)
    df_dm["Don_Gia"] = pd.to_numeric(df_dm["Don_Gia"], errors="coerce").fillna(0)

    if not df_history_all.empty:
        df_history_all["Ten_Hang"] = df_history_all["Ma_Hang"].map(ITEM_LABELS)
        df_history_all["Is_Adjustment"] = (
            df_history_all["Doi_Tac"].fillna("").str.startswith(db.ADJUSTMENT_PREFIX)
        )
    else:
        df_history_all["Is_Adjustment"] = pd.Series(dtype=bool)

    if not df_adjustments.empty:
        df_adjustments["Ten_Hang"] = df_adjustments["Ma_Hang"].map(ITEM_LABELS)

    df_business = df_history_all[~df_history_all["Is_Adjustment"]].copy()
    df_dm = df_dm.set_index("Ma_Hang").reindex(ITEM_ORDER).reset_index()
    df_stock = df_stock.set_index("Ma_Hang").reindex(ITEM_ORDER).reset_index()
    return df_dm, df_stock, df_business, df_adjustments, df_history_all


def draw_stock_chart(df, loai_gd, colors):
    df_plot = df[df["Loai_GD"] == loai_gd].copy()
    if df_plot.empty:
        return st.info(f"Chưa có dữ liệu {loai_gd}.")

    resolution = st.radio(
        f"Gộp dữ liệu ({loai_gd})",
        ["Theo Giờ", "Theo Ngày", "Theo Tháng"],
        horizontal=True,
        key=f"res_{loai_gd}",
    )

    if resolution == "Theo Giờ":
        df_plot["Time"] = df_plot["Ngay_Giao_Dich"].dt.floor("h")
    elif resolution == "Theo Tháng":
        df_plot["Time"] = df_plot["Ngay_Giao_Dich"].dt.to_period("M").dt.to_timestamp()
    else:
        df_plot["Time"] = df_plot["Ngay_Giao_Dich"].dt.floor("d")

    trend = (
        df_plot.groupby(["Time", "Ma_Hang"], as_index=False)["So_Luong"]
        .sum()
        .sort_values("Time")
    )

    fig = px.bar(
        trend,
        x="Time",
        y="So_Luong",
        color="Ma_Hang",
        barmode="group",
        color_discrete_sequence=colors,
        category_orders={"Ma_Hang": ITEM_ORDER},
        labels={
            "Time": "Thời gian",
            "So_Luong": "Khối lượng (m3)",
            "Ma_Hang": "Mặt hàng",
        },
    )

    fig.update_xaxes(
        rangeslider_visible=True,
        rangeselector=dict(
            buttons=list(
                [
                    dict(count=1, label="1 Ngày", step="day", stepmode="backward"),
                    dict(count=7, label="1 Tuần", step="day", stepmode="backward"),
                    dict(count=1, label="1 Tháng", step="month", stepmode="backward"),
                    dict(count=3, label="3 Tháng", step="month", stepmode="backward"),
                    dict(count=6, label="6 Tháng", step="month", stepmode="backward"),
                    dict(count=1, label="1 Năm", step="year", stepmode="backward"),
                    dict(step="all", label="Tất cả"),
                ]
            ),
            bgcolor="#1F2937",
            activecolor="#3B82F6",
        ),
    )
    fig.update_layout(
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=0, r=0, t=30, b=0),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, width="stretch")


def build_replenishment_table(df_stock, df_dm, df_history, lookback_days: int):
    now = pd.Timestamp.now().normalize()
    since = now - pd.Timedelta(days=lookback_days)
    recent_out = df_history[
        (df_history["Loai_GD"] == "Xuat")
        & (df_history["Ngay_Giao_Dich"] >= since)
    ].copy()

    rows = []
    for _, stock_row in df_stock.iterrows():
        ma_hang = stock_row["Ma_Hang"]
        dm_row = df_dm[df_dm["Ma_Hang"] == ma_hang].iloc[0]
        plan = db.PLANNING_CONFIG[ma_hang]

        total_out = recent_out.loc[recent_out["Ma_Hang"] == ma_hang, "So_Luong"].sum()
        avg_daily_out = round(total_out / lookback_days, 2) if lookback_days > 0 else 0

        current_stock = float(stock_row["So_Luong_Ton"])
        safety_stock = float(dm_row["Nguong_An_Toan"])
        lead_time_days = float(plan["lead_time_days"])
        target_stock = float(plan["target_stock"])

        reorder_point = round(avg_daily_out * lead_time_days + safety_stock, 1)

        if avg_daily_out > 0:
            days_cover = round(current_stock / avg_daily_out, 1)
            stockout_date = (now + timedelta(days=float(days_cover))).date().isoformat()
        else:
            days_cover = float("inf")
            stockout_date = "Chưa xác định"

        if current_stock <= reorder_point:
            suggested_order = round(max(target_stock - current_stock, 0), 1)
        else:
            suggested_order = 0.0

        if avg_daily_out == 0:
            status = "Ổn định"
        elif current_stock <= reorder_point * 0.8 or days_cover < lead_time_days:
            status = "Rủi ro cao"
        elif current_stock <= reorder_point:
            status = "Cần lên đơn"
        else:
            status = "Ổn"

        rows.append(
            {
                "Mặt hàng": ITEM_LABELS[ma_hang],
                "Tồn hiện tại (m3)": round(current_stock, 1),
                f"Xuất TB/{lookback_days} ngày (m3/ngày)": avg_daily_out,
                "Lead time (ngày)": lead_time_days,
                "Ngưỡng an toàn (m3)": round(safety_stock, 1),
                "Điểm đặt hàng lại (m3)": reorder_point,
                "Mức tồn mục tiêu (m3)": target_stock,
                "Đề xuất nhập (m3)": suggested_order,
                "Số ngày đủ hàng": "∞" if days_cover == float("inf") else days_cover,
                "Dự báo chạm đáy": stockout_date,
                "Nhà cung cấp gợi ý": plan["default_supplier"],
                "Trạng thái": status,
            }
        )

    return pd.DataFrame(rows)


def build_partner_summary(df_history, loai_gd: str):
    df = df_history[df_history["Loai_GD"] == loai_gd].copy()
    if df.empty:
        return pd.DataFrame()

    summary = (
        df.groupby("Doi_Tac", as_index=False)
        .agg(
            Tong_Khoi_Luong=("So_Luong", "sum"),
            So_Giao_Dich=("ID", "count"),
            Lan_Cuoi=("Ngay_Giao_Dich", "max"),
        )
        .sort_values(["Tong_Khoi_Luong", "So_Giao_Dich"], ascending=[False, False])
        .head(8)
    )
    summary["Tong_Khoi_Luong"] = summary["Tong_Khoi_Luong"].round(1)
    summary["Lan_Cuoi"] = summary["Lan_Cuoi"].dt.strftime("%d/%m/%Y %H:%M")
    return summary


def detect_outbound_anomalies(df_history, compare_days: int = 7, baseline_days: int = 30):
    if df_history.empty:
        return pd.DataFrame()

    today = pd.Timestamp.now().normalize()
    current_start = today - pd.Timedelta(days=compare_days)
    baseline_start = current_start - pd.Timedelta(days=baseline_days)

    outbound = df_history[df_history["Loai_GD"] == "Xuat"].copy()
    current = outbound[outbound["Ngay_Giao_Dich"] >= current_start]
    baseline = outbound[
        (outbound["Ngay_Giao_Dich"] >= baseline_start)
        & (outbound["Ngay_Giao_Dich"] < current_start)
    ]

    rows = []
    for ma_hang in ITEM_ORDER:
        current_total = current.loc[current["Ma_Hang"] == ma_hang, "So_Luong"].sum()
        baseline_total = baseline.loc[baseline["Ma_Hang"] == ma_hang, "So_Luong"].sum()
        current_daily = current_total / max(compare_days, 1)
        baseline_daily = baseline_total / max(baseline_days, 1)
        ratio = round(current_daily / baseline_daily, 2) if baseline_daily > 0 else None

        if ratio is not None and ratio >= 1.4:
            rows.append(
                {
                    "Mặt hàng": ITEM_LABELS[ma_hang],
                    f"Xuất TB {compare_days} ngày gần nhất": round(current_daily, 1),
                    f"Xuất TB {baseline_days} ngày trước đó": round(baseline_daily, 1),
                    "Tỷ lệ tăng": ratio,
                    "Nhận định": "Bất thường - cần theo dõi cấp hàng",
                }
            )

    return pd.DataFrame(rows)


try:
    df_dm, df_stock, df_history, df_adjustments, df_history_all = load_data()
except Exception as exc:
    st.error("Lỗi đọc database. Hãy chạy `python setup_db.py` trước.")
    st.caption(str(exc))
    st.stop()

col_dash, col_chat = st.columns([7, 3], gap="large")

with col_dash:
    st.title("🏗️ Dashboard Quản Lý Kho Cát")
    st.caption(
        "Hệ thống được tối ưu riêng cho 2 mặt hàng: Cát vàng hạt lớn và Cát xây tô. Đã bổ sung thêm trung tâm nhập hàng, kiểm kê đối soát và phân tích đối tác."
    )
    st.markdown("---")

    cols = st.columns(len(df_stock))
    for i, row in df_stock.iterrows():
        dm_info = df_dm[df_dm["Ma_Hang"] == row["Ma_Hang"]].iloc[0]
        is_safe = float(row["So_Luong_Ton"]) > float(dm_info["Nguong_An_Toan"])
        delta_color = "normal" if is_safe else "inverse"
        delta_text = f"Ngưỡng: {format_qty(dm_info['Nguong_An_Toan'])} m3"

        with cols[i]:
            st.metric(
                ITEM_LABELS.get(row["Ma_Hang"], row["Ma_Hang"]),
                f"{format_qty(row['So_Luong_Ton'])} m3",
                delta_text,
                delta_color=delta_color,
            )
            est_value = float(row["So_Luong_Ton"]) * float(dm_info["Don_Gia"])
            st.caption(f"Giá trị tồn ước tính: {est_value:,.0f} đ")

    replenishment_snapshot = build_replenishment_table(df_stock, df_dm, df_history, lookback_days=30)
    high_risk = replenishment_snapshot[
        replenishment_snapshot["Trạng thái"].isin(["Rủi ro cao", "Cần lên đơn"])
    ]
    if not high_risk.empty:
        for _, row in high_risk.iterrows():
            st.warning(
                f"{row['Mặt hàng']}: {row['Trạng thái']} | Điểm đặt hàng lại {row['Điểm đặt hàng lại (m3)']} m3 | Đề xuất nhập {row['Đề xuất nhập (m3)']} m3."
            )

    st.markdown("---")
    tabs = st.tabs(
        [
            "📤 Xuất kho (Bán)",
            "📥 Nhập kho (Mua)",
            "📈 Trung tâm nhập hàng",
            "🧮 Kiểm kê & Điều chỉnh",
            "🧑‍🤝‍🧑 Đối tác & Cảnh báo",
            "🗃️ Dữ liệu tổng thể",
        ]
    )

    with tabs[0]:
        draw_stock_chart(df_history, "Xuat", ["#E63946", "#F4A261"])

        with st.form("f_xuat", clear_on_submit=True):
            st.markdown("**📝 Tạo giao dịch Xuất mới**")
            c1, c2, c3 = st.columns(3)
            item_x = c1.selectbox("Hàng hóa", df_dm["Ten_Hang"])
            qty_x = c2.number_input("Số lượng (m3)", min_value=0.5, step=0.5, value=1.0)
            partner_x = c3.text_input("Khách hàng / Công trình")

            selected_code_x = df_dm[df_dm["Ten_Hang"] == item_x]["Ma_Hang"].values[0]
            available_x = df_stock.loc[df_stock["Ma_Hang"] == selected_code_x, "So_Luong_Ton"].iloc[0]
            st.caption(f"Tồn hiện tại của {item_x}: {format_qty(available_x)} m3")

            if st.form_submit_button("Xác nhận Xuất"):
                try:
                    db.add_transaction("Xuat", selected_code_x, qty_x, partner_x)
                    load_data.clear()
                    st.success("Đã ghi nhận giao dịch xuất kho.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    with tabs[1]:
        draw_stock_chart(df_history, "Nhap", ["#2A9D8F", "#457B9D"])

        with st.form("f_nhap", clear_on_submit=True):
            st.markdown("**📝 Tạo giao dịch Nhập mới**")
            c1, c2, c3 = st.columns(3)
            item_n = c1.selectbox("Hàng hóa", df_dm["Ten_Hang"], key="n")
            qty_n = c2.number_input("Số lượng (m3)", min_value=0.5, step=0.5, value=1.0, key="qn")
            partner_n = c3.text_input("Nhà cung cấp", key="pn")

            selected_code_n = df_dm[df_dm["Ten_Hang"] == item_n]["Ma_Hang"].values[0]
            available_n = df_stock.loc[df_stock["Ma_Hang"] == selected_code_n, "So_Luong_Ton"].iloc[0]
            st.caption(f"Tồn hiện tại của {item_n}: {format_qty(available_n)} m3")

            if st.form_submit_button("Xác nhận Nhập"):
                try:
                    db.add_transaction("Nhap", selected_code_n, qty_n, partner_n)
                    load_data.clear()
                    st.success("Đã ghi nhận giao dịch nhập kho.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    with tabs[2]:
        st.subheader("📈 Trung tâm nhập hàng")
        lookback_days = st.slider("Khoảng dữ liệu để tính nhu cầu xuất trung bình", 14, 90, 30, 1)
        repl = build_replenishment_table(df_stock, df_dm, df_history, lookback_days=lookback_days)
        st.dataframe(repl, width="stretch", hide_index=True)

        chart_data = repl[["Mặt hàng", "Đề xuất nhập (m3)"]].copy()
        fig = px.bar(chart_data, x="Mặt hàng", y="Đề xuất nhập (m3)", text="Đề xuất nhập (m3)")
        fig.update_layout(margin=dict(l=0, r=0, t=30, b=0))
        st.plotly_chart(fig, width="stretch")

        urgent = repl[repl["Đề xuất nhập (m3)"] > 0]
        if urgent.empty:
            st.success("Hiện chưa cần tạo đề xuất nhập gấp theo cấu hình hiện tại.")
        else:
            for _, row in urgent.iterrows():
                st.info(
                    f"Đề xuất: nhập {row['Đề xuất nhập (m3)']} m3 cho {row['Mặt hàng']} từ {row['Nhà cung cấp gợi ý']}."
                )

            csv_repl = repl.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "Tải CSV đề xuất nhập hàng",
                data=csv_repl,
                file_name="de_xuat_nhap_hang_cat.csv",
                mime="text/csv",
            )

    with tabs[3]:
        st.subheader("🧮 Kiểm kê & Điều chỉnh tồn thực tế")
        st.caption(
            "Dùng khi số lượng ngoài bãi không khớp với hệ thống. Hệ thống sẽ tự tạo bút toán điều chỉnh tăng/giảm."
        )

        with st.form("f_adjust", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            item_a = c1.selectbox("Mặt hàng", df_dm["Ten_Hang"], key="adj_item")
            actual_qty = c2.number_input("Số lượng kiểm thực tế (m3)", min_value=0.0, step=0.5, value=0.0)
            checker = c3.text_input("Người kiểm kê", value="Thủ kho")
            reason = st.text_input("Lý do chênh lệch", value="Kiểm kê cuối ngày")

            selected_code_a = df_dm[df_dm["Ten_Hang"] == item_a]["Ma_Hang"].values[0]
            system_qty = df_stock.loc[df_stock["Ma_Hang"] == selected_code_a, "So_Luong_Ton"].iloc[0]
            st.caption(f"Hệ thống đang ghi nhận: {format_qty(system_qty)} m3")

            if st.form_submit_button("Ghi nhận kiểm kê"):
                try:
                    result = db.adjust_stock_to_actual(selected_code_a, actual_qty, reason, checker)
                    load_data.clear()
                    st.success(
                        f"Đã điều chỉnh {ITEM_LABELS[result['ma_hang']]} | Hệ thống: {result['he_thong']} m3 | Thực tế: {result['thuc_te']} m3 | Chênh lệch: {result['chenh_lech']} m3."
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

        st.markdown("**Lịch sử điều chỉnh gần nhất**")
        adj_show = df_adjustments.copy()
        if not adj_show.empty:
            adj_show["Ngay_Giao_Dich"] = adj_show["Ngay_Giao_Dich"].dt.strftime("%d/%m/%Y %H:%M")
        st.dataframe(adj_show, width="stretch", hide_index=True)

    with tabs[4]:
        st.subheader("🧑‍🤝‍🧑 Đối tác & Cảnh báo bất thường")
        c1, c2 = st.columns(2)

        with c1:
            st.markdown("**Top khách hàng / công trình**")
            customer_summary = build_partner_summary(df_history, "Xuat")
            st.dataframe(customer_summary, width="stretch", hide_index=True)

            if not customer_summary.empty:
                fig = px.bar(customer_summary, x="Doi_Tac", y="Tong_Khoi_Luong", text="Tong_Khoi_Luong")
                fig.update_layout(margin=dict(l=0, r=0, t=30, b=0), xaxis_title="Đối tác", yaxis_title="m3")
                st.plotly_chart(fig, width="stretch")

        with c2:
            st.markdown("**Top nhà cung cấp**")
            supplier_summary = build_partner_summary(df_history, "Nhap")
            st.dataframe(supplier_summary, width="stretch", hide_index=True)

            if not supplier_summary.empty:
                fig = px.bar(supplier_summary, x="Doi_Tac", y="Tong_Khoi_Luong", text="Tong_Khoi_Luong")
                fig.update_layout(margin=dict(l=0, r=0, t=30, b=0), xaxis_title="Đối tác", yaxis_title="m3")
                st.plotly_chart(fig, width="stretch")

        st.markdown("**Cảnh báo tăng nhịp xuất bất thường**")
        anomalies = detect_outbound_anomalies(df_history)

        if anomalies.empty:
            st.success("7 ngày gần nhất chưa thấy mặt hàng nào tăng nhịp xuất bất thường so với nền 30 ngày trước đó.")
        else:
            st.warning("Có dấu hiệu tăng nhịp xuất, nên kiểm tra kế hoạch nhập hàng và tiến độ công trình.")
            st.dataframe(anomalies, width="stretch", hide_index=True)

    with tabs[5]:
        st.subheader("🗃️ Dữ liệu tổng thể")
        df_show = df_history_all.copy()
        if not df_show.empty:
            df_show["Ngay_Giao_Dich"] = df_show["Ngay_Giao_Dich"].dt.strftime("%d/%m/%Y %H:%M")
            df_show["So_Luong"] = df_show["So_Luong"].map(lambda x: f"{float(x):,.1f}")
        st.dataframe(df_show, width="stretch", hide_index=True)

        csv_data = df_history_all.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "Tải CSV toàn bộ lịch sử giao dịch",
            data=csv_data,
            file_name="lich_su_giao_dich_cat_day_du.csv",
            mime="text/csv",
            disabled=df_history_all.empty,
        )

with col_chat:
    st.subheader("🤖 AI Copilot")

    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": "Mình đang theo dõi đúng 2 mặt hàng cát của kho. Bạn có thể hỏi về tồn kho, đề xuất nhập hàng, kiểm kê đối soát hoặc đối tác nhập/xuất.",
            }
        ]

    if "ai_running" not in st.session_state:
        st.session_state.ai_running = False

    chat_container = st.container(height=500)
    with chat_container:
        for msg in st.session_state.messages:
            st.chat_message(msg["role"]).write(msg["content"])

    prompt = st.chat_input(
        "Hỏi AI...",
        disabled=st.session_state.ai_running,
    )

    if prompt and not st.session_state.ai_running:
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.session_state.ai_running = True

        with chat_container:
            st.chat_message("user").write(prompt)
            with st.spinner("Đang phân tích dữ liệu kho..."):
                try:
                    response = ai_agent.get_copilot_response(prompt, df_stock, df_dm, df_history)
                except Exception as exc:
                    response = f"Lỗi khi gọi AI: {exc}"

            st.chat_message("assistant").write(response)

        st.session_state.messages.append({"role": "assistant", "content": response})
        st.session_state.ai_running = False
        st.rerun()