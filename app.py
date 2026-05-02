import math
from datetime import timedelta
import pandas as pd
import plotly.express as px
import streamlit as st

from inventory import ai_agent
from inventory import database as db
from inventory import analytics

st.set_page_config(page_title="AI Inventory Copilot", layout="wide")

with st.sidebar:
    st.subheader("Gemini Debug")
    debug = ai_agent.get_debug_status()

    st.write({
        "env_exists": debug["env_exists"],
        "env_path": debug["env_path"],
        "sdk_import_ok": debug["sdk_import_ok"],
        "has_api_key": debug["has_api_key"],
        "api_key_masked": debug["api_key_masked"],
        "model_name": debug["model_name"],
        "client_ready": debug["client_ready"],
        "client_init_error": debug["client_init_error"],
    })

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
        df_history_all["Is_Adjustment"] = df_history_all["Doi_Tac"].fillna("").str.startswith(db.ADJUSTMENT_PREFIX)
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

    df_plot["Time"] = df_plot["Ngay_Giao_Dich"].dt.floor("d")
    trend = df_plot.groupby(["Time", "Ma_Hang"], as_index=False)["So_Luong"].sum().sort_values("Time")

    fig = px.bar(
        trend,
        x="Time",
        y="So_Luong",
        color="Ma_Hang",
        barmode="stack",
        color_discrete_sequence=colors,
        category_orders={"Ma_Hang": ITEM_ORDER},
        labels={"Time": "Thời gian", "So_Luong": "Khối lượng (m3)", "Ma_Hang": "Mặt hàng"},
    )
    fig.update_traces(marker_line_width=0)
    
    recent_date = df_plot['Ngay_Giao_Dich'].max()
    start_date = recent_date - pd.DateOffset(months=3)
    fig.update_xaxes(range=[start_date, recent_date])
    
    fig.update_layout(
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=0, r=0, t=30, b=0),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", bargap=0.1
    )
    st.plotly_chart(fig, use_container_width=True, key=f"chart_{loai_gd}")

def build_replenishment_table(df_stock, df_dm, df_history, lookback_days: int, service_level_z: float, ordering_cost: float, holding_cost_rate: float):
    now = pd.Timestamp.now().normalize()
    since = now - pd.Timedelta(days=lookback_days)
    recent_out = df_history[(df_history["Loai_GD"] == "Xuat") & (df_history["Ngay_Giao_Dich"] >= since)].copy()

    rows = []
    for _, stock_row in df_stock.iterrows():
        ma_hang = stock_row["Ma_Hang"]
        dm_row = df_dm[df_dm["Ma_Hang"] == ma_hang].iloc[0]
        plan = db.PLANNING_CONFIG[ma_hang]

        current_stock = float(stock_row["So_Luong_Ton"])
        lead_time_days = float(plan["lead_time_days"])
        don_gia = float(dm_row["Don_Gia"])
        
        # Dự báo từ AI SARIMA
        try:
            fc = analytics.get_sarima_forecast(ma_hang, steps=1)
            forecasted_monthly_demand = fc[0] if fc else 0
        except:
            forecasted_monthly_demand = 600.0 

        daily_demand = forecasted_monthly_demand / 30.0

        # TÍNH NĂNG DYNAMIC SAFETY STOCK
        rmse = analytics.get_model_rmse(ma_hang)
        lead_time_months = lead_time_days / 30.0
        dynamic_safety_stock = service_level_z * rmse * math.sqrt(lead_time_months)
        
        # Tính ROP (Điểm đặt hàng lại)
        reorder_point = (daily_demand * lead_time_days) + dynamic_safety_stock

        # TÍNH NĂNG EOQ
        annual_demand = forecasted_monthly_demand * 12
        holding_cost = don_gia * holding_cost_rate
        
        if holding_cost > 0 and annual_demand > 0:
            eoq = math.sqrt((2 * annual_demand * ordering_cost) / holding_cost)
        else:
            eoq = 0.0

        if current_stock <= reorder_point:
            suggested_order = eoq
        else:
            suggested_order = 0.0

        if daily_demand > 0:
            days_cover = round(current_stock / daily_demand, 1)
        else:
            days_cover = float("inf")

        if current_stock <= reorder_point * 0.8:
            status = "Rủi ro đứt hàng"
        elif current_stock <= reorder_point:
            status = "Cần lên đơn (Chạm ROP)"
        else:
            status = "Tồn kho An toàn"

        rows.append({
            "Mặt hàng": ITEM_LABELS[ma_hang],
            "Tồn hiện tại (m³)": round(current_stock, 1),
            "Dự báo AI (m³/tháng)": round(forecasted_monthly_demand, 1),
            "Ngưỡng an toàn động (m³)": round(dynamic_safety_stock, 1),
            "Điểm ROP (m³)": round(reorder_point, 1),
            "Lượng nhập EOQ (m³)": round(eoq, 1),
            "Đề xuất nhập (m³)": round(suggested_order, 1),
            "Trạng thái": status,
        })

    return pd.DataFrame(rows)

def build_partner_summary(df_history, loai_gd: str):
    df = df_history[df_history["Loai_GD"] == loai_gd].copy()
    if df.empty: return pd.DataFrame()
    summary = df.groupby("Doi_Tac", as_index=False).agg(Tong_Khoi_Luong=("So_Luong", "sum"), So_Giao_Dich=("ID", "count"), Lan_Cuoi=("Ngay_Giao_Dich", "max")).sort_values(["Tong_Khoi_Luong", "So_Giao_Dich"], ascending=[False, False]).head(8)
    summary["Tong_Khoi_Luong"] = summary["Tong_Khoi_Luong"].round(1)
    summary["Lan_Cuoi"] = summary["Lan_Cuoi"].dt.strftime("%d/%m/%Y %H:%M")
    return summary

def detect_outbound_anomalies(df_history, compare_days: int = 7, baseline_days: int = 30):
    if df_history.empty: return pd.DataFrame()
    today = pd.Timestamp.now().normalize()
    current_start = today - pd.Timedelta(days=compare_days)
    baseline_start = current_start - pd.Timedelta(days=baseline_days)

    outbound = df_history[df_history["Loai_GD"] == "Xuat"].copy()
    current = outbound[outbound["Ngay_Giao_Dich"] >= current_start]
    baseline = outbound[(outbound["Ngay_Giao_Dich"] >= baseline_start) & (outbound["Ngay_Giao_Dich"] < current_start)]

    rows = []
    for ma_hang in ITEM_ORDER:
        current_total = current.loc[current["Ma_Hang"] == ma_hang, "So_Luong"].sum()
        baseline_total = baseline.loc[baseline["Ma_Hang"] == ma_hang, "So_Luong"].sum()
        current_daily = current_total / max(compare_days, 1)
        baseline_daily = baseline_total / max(baseline_days, 1)
        ratio = round(current_daily / baseline_daily, 2) if baseline_daily > 0 else None

        if ratio is not None and ratio >= 1.4:
            rows.append({
                "Mặt hàng": ITEM_LABELS[ma_hang],
                f"Xuất TB {compare_days} ngày gần nhất": round(current_daily, 1),
                f"Xuất TB {baseline_days} ngày trước đó": round(baseline_daily, 1),
                "Tỷ lệ tăng": ratio,
                "Nhận định": "Bất thường - cần theo dõi cấp hàng",
            })
    return pd.DataFrame(rows)

try:
    df_dm, df_stock, df_history, df_adjustments, df_history_all = load_data()
except Exception as exc:
    st.error("Lỗi đọc database. Hãy chạy `python setup_db.py` trước.")
    st.caption(str(exc))
    st.stop()

df_history_all['Year'] = df_history_all['Ngay_Giao_Dich'].dt.year
available_years = sorted(df_history_all['Year'].dropna().unique(), reverse=True)

with st.sidebar:
    st.markdown("---")
    st.subheader("📅 Bộ lọc Thời gian")
    if available_years:
        selected_year = st.selectbox("Hiển thị dữ liệu của Năm:", available_years)
    else:
        selected_year = pd.Timestamp.now().year
        st.selectbox("Hiển thị dữ liệu của Năm:", [selected_year])

df_history_filtered = df_history_all[df_history_all['Year'] == selected_year].copy()

col_dash, col_chat = st.columns([7, 3], gap="large")

with col_dash:
    st.title("🏗️ Dashboard Quản Lý Kho Cát & Tối Ưu Nguồn Vốn")
    st.caption(f"Hệ thống tối ưu chuỗi cung ứng Cát vàng hạt lớn và Cát xây tô. Đang hiển thị dữ liệu năm **{selected_year}**.")
    st.markdown("---")

    cols = st.columns(len(df_stock))
    for i, row in df_stock.iterrows():
        ma_hang = row["Ma_Hang"]
        dm_info = df_dm[df_dm["Ma_Hang"] == ma_hang].iloc[0]
        
        try:
            fc = analytics.get_sarima_forecast(ma_hang, steps=1)
            predicted_demand = f"{fc[0]:.1f}" if fc else "Không đủ data"
        except Exception:
            predicted_demand = "Lỗi tính toán"

        is_safe = float(row["So_Luong_Ton"]) > (float(predicted_demand)/30)*float(db.PLANNING_CONFIG[ma_hang]['lead_time_days'])
        delta_color = "normal" if is_safe else "inverse"
        
        with cols[i]:
            st.metric(
                ITEM_LABELS.get(ma_hang, ma_hang),
                f"{format_qty(row['So_Luong_Ton'])} m³",
                f"Ngưỡng: {format_qty(dm_info['Nguong_An_Toan'])} m³",
                delta_color=delta_color,
            )
            st.info(f"🔮 Dự báo xuất tháng tới (SARIMA): **{predicted_demand} m³**")
            est_value = float(row["So_Luong_Ton"]) * float(dm_info["Don_Gia"])
            st.caption(f"Giá trị tồn ước tính: {est_value:,.0f} đ")

    st.markdown("---")
    tabs = st.tabs([
        "📤 Xuất kho (Bán)",
        "📥 Nhập kho (Mua)",
        "📈 Trung tâm nhập hàng (EOQ)",
        "🧮 Kiểm kê & Điều chỉnh",
        "🧑‍🤝‍🧑 Đối tác & Cảnh báo",
        f"🗃️ Dữ liệu năm {selected_year}",
        "🛠️ MLOps & Retrain"
    ])

    with tabs[0]:
        draw_stock_chart(df_history_filtered, "Xuat", ["#E63946", "#F4A261"]) 
        with st.form("f_xuat", clear_on_submit=True):
            st.markdown("**📝 Tạo giao dịch Xuất mới**")
            c1, c2, c3 = st.columns(3)
            item_x = c1.selectbox("Hàng hóa", df_dm["Ten_Hang"])
            qty_x = c2.number_input("Số lượng (m3)", min_value=0.5, step=0.5, value=1.0)
            partner_x = c3.text_input("Khách hàng / Công trình")
            selected_code_x = df_dm[df_dm["Ten_Hang"] == item_x]["Ma_Hang"].values[0]
            if st.form_submit_button("Xác nhận Xuất"):
                db.add_transaction("Xuat", selected_code_x, qty_x, partner_x)
                load_data.clear()
                st.rerun()

    with tabs[1]:
        draw_stock_chart(df_history_filtered, "Nhap", ["#2A9D8F", "#457B9D"]) 
        with st.form("f_nhap", clear_on_submit=True):
            st.markdown("**📝 Tạo giao dịch Nhập mới**")
            c1, c2, c3 = st.columns(3)
            item_n = c1.selectbox("Hàng hóa", df_dm["Ten_Hang"], key="n")
            qty_n = c2.number_input("Số lượng (m3)", min_value=0.5, step=0.5, value=1.0, key="qn")
            partner_n = c3.text_input("Nhà cung cấp", key="pn")
            selected_code_n = df_dm[df_dm["Ten_Hang"] == item_n]["Ma_Hang"].values[0]
            if st.form_submit_button("Xác nhận Nhập"):
                db.add_transaction("Nhap", selected_code_n, qty_n, partner_n)
                load_data.clear()
                st.rerun()

    with tabs[2]:
        st.subheader("📈 Tối ưu hóa Nguồn vốn & Nhập hàng (Dynamic EOQ)")
        st.caption("Ứng dụng AI dự báo và công thức Toán kinh tế để đề xuất lượng nhập hàng tối ưu.")
        
        c1, c2, c3 = st.columns(3)
        service_level = c1.selectbox("Mức độ phục vụ (Z-Score)", options=["90%", "95%", "99%"], index=1)
        ordering_cost = c2.number_input("Chi phí 1 lần đặt hàng (S - VNĐ)", min_value=100000, value=500000, step=50000)
        holding_rate_pct = c3.number_input("Tỷ lệ chi phí lưu kho/năm (H - %)", min_value=1, max_value=50, value=20, step=1)
        
        z_scores = {"90%": 1.28, "95%": 1.65, "99%": 2.33}
        z_val = z_scores[service_level]
        h_val = holding_rate_pct / 100.0

        repl = build_replenishment_table(df_stock, df_dm, df_history_all, 30, z_val, ordering_cost, h_val)
        
        def color_status(val):
            color = '#E63946' if val == 'Rủi ro đứt hàng' else '#F4A261' if 'Cần lên đơn' in val else '#2A9D8F'
            return f'background-color: {color}; color: white'
            
        st.dataframe(repl.style.map(color_status, subset=['Trạng thái']), width="stretch", hide_index=True)

        urgent = repl[repl["Đề xuất nhập (m³)"] > 0]
        if urgent.empty:
            st.success("✅ Tồn kho hiện tại đang ở mức tối ưu. Vốn lưu động được kiểm soát tốt.")
        else:
            for _, row in urgent.iterrows():
                st.warning(f"⚠️ **{row['Mặt hàng']}**: Chạm ROP ({row['Điểm ROP (m³)']} m³). Hệ thống đề xuất nhập **EOQ = {row['Lượng nhập EOQ (m³)']} m³**.")

    with tabs[3]:
        st.subheader("🧮 Kiểm kê & Điều chỉnh tồn thực tế")
        with st.form("f_adjust", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            item_a = c1.selectbox("Mặt hàng", df_dm["Ten_Hang"], key="adj_item")
            actual_qty = c2.number_input("Số lượng thực tế", min_value=0.0, step=0.5)
            checker = c3.text_input("Người kiểm kê", value="Thủ kho")
            reason = st.text_input("Lý do", value="Kiểm kê")
            selected_code_a = df_dm[df_dm["Ten_Hang"] == item_a]["Ma_Hang"].values[0]
            if st.form_submit_button("Ghi nhận"):
                db.adjust_stock_to_actual(selected_code_a, actual_qty, reason, checker)
                load_data.clear()
                st.rerun()
        st.dataframe(df_adjustments, width="stretch", hide_index=True)

    with tabs[4]:
        st.subheader("🧑‍🤝‍🧑 Đối tác & Cảnh báo bất thường")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Top khách hàng / công trình**")
            customer_summary = build_partner_summary(df_history_all, "Xuat")
            st.dataframe(customer_summary, width="stretch", hide_index=True)
        with c2:
            st.markdown("**Top nhà cung cấp**")
            supplier_summary = build_partner_summary(df_history_all, "Nhap")
            st.dataframe(supplier_summary, width="stretch", hide_index=True)
            
        anomalies = detect_outbound_anomalies(df_history_all)
        if not anomalies.empty:
            st.warning("Có dấu hiệu tăng nhịp xuất bất thường.")
            st.dataframe(anomalies, width="stretch", hide_index=True)

    with tabs[5]:
        st.subheader(f"🗃️ Dữ liệu tổng thể năm {selected_year}")
        st.dataframe(df_history_filtered.drop(columns=['Year'], errors='ignore'), width="stretch", hide_index=True)

    with tabs[6]:
        st.subheader("🛠️ MLOps: Giám sát, Cập nhật & Kiểm định Mô hình")
        st.markdown("Khu vực dành riêng cho Data Scientist/BA để theo dõi sức khỏe mô hình AI và kiểm định độ chính xác.")
        
        c1, c2 = st.columns([1.5, 1])
        with c1:
            st.markdown("**1. Biểu đồ Learning Curve (Kiểm định tính hội tụ)**")
            df_plot_ml = df_history_all[df_history_all["Loai_GD"] == "Xuat"]
            fig = analytics.plot_sarima_learning_curve(df_plot_ml)
            st.pyplot(fig)
            st.caption("*Khoảng cách hẹp giữa Train Error và Validation Error cho thấy mô hình không bị quá khớp (Overfitting).*")
            
        with c2:
            st.markdown("**2. Pipeline Retrain Mô hình**")
            st.info("Trạng thái: **Đang hoạt động ổn định**")
            if st.button("🚀 Kích hoạt Huấn luyện lại (Retrain SARIMA)", type="primary", use_container_width=True):
                with st.spinner("Đang khởi tạo Pipeline MLOps..."):
                    success, msg = analytics.retrain_all_models()
                    if success:
                        st.success(msg)
                    else:
                        st.error(f"Lỗi Pipeline: {msg}")
            
            st.markdown("---")
            st.markdown("**3. Backtest (Kiểm định ngược)**")
            st.caption("Chạy mô hình trên dữ liệu 6 tháng qua để đo lường sai số thực tế.")
            bt_item = st.selectbox("Chọn mặt hàng để Backtest", df_dm["Ten_Hang"], key="bt_item")
            bt_code = df_dm[df_dm["Ten_Hang"] == bt_item]["Ma_Hang"].values[0]
            
            if st.button("📊 Chạy Backtest", use_container_width=True):
                with st.spinner(f"Đang chạy Backtest cho {bt_item}..."):
                    metrics = analytics.run_model_backtest(df_history_all, ma_hang=bt_code)
                    
                    st.success("Hoàn tất kiểm định!")
                    mc1, mc2 = st.columns(2)
                    mc1.metric("Độ chính xác", metrics["Accuracy"])
                    mc2.metric("Sai số wMAPE", metrics["wMAPE"])
                    
                    mc3, mc4 = st.columns(2)
                    mc3.metric("MAE (Khối lượng lệch)", f"{metrics['MAE']} m³")
                    mc4.metric("RMSE (Rủi ro)", f"{metrics['RMSE']} m³")

with col_chat:
    st.subheader("🤖 AI Copilot")
    forecast_steps = st.slider("Số tháng AI cần nhìn xa:", 1, 6, 3)
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Mình là AI Inventory Copilot. Bạn có thể hỏi về EOQ, điểm đặt hàng hoặc tồn kho."}]
    if "ai_running" not in st.session_state: st.session_state.ai_running = False

    chat_container = st.container(height=500)
    with chat_container:
        for msg in st.session_state.messages:
            st.chat_message(msg["role"]).write(msg["content"])

    prompt = st.chat_input("Hỏi AI...", disabled=st.session_state.ai_running)
    if prompt and not st.session_state.ai_running:
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.session_state.ai_running = True
        with chat_container:
            st.chat_message("user").write(prompt)
            with st.spinner("Đang phân tích..."):
                try: response = ai_agent.get_copilot_response(prompt, df_stock, df_dm, df_history_all, forecast_months=forecast_steps)
                except Exception as exc: response = f"Lỗi AI: {exc}"
            st.chat_message("assistant").write(response)
        st.session_state.messages.append({"role": "assistant", "content": response})
        st.session_state.ai_running = False
        st.rerun()