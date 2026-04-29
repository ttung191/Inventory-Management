import pandas as pd
from inventory import database as db
import warnings
from statsmodels.tsa.statespace.sarimax import SARIMAX

warnings.filterwarnings("ignore")

def get_sarima_forecast(ma_hang, steps=3):
    """Dự báo nhu cầu xuất kho trong n tháng tới bằng SARIMA."""
    df = db.get_history()
    df = df[(df['Loai_GD'] == 'Xuat') & (df['Ma_Hang'] == ma_hang)].copy()
    
    if len(df) < 20: return [] # Không đủ data

    df['Ngay_Giao_Dich'] = pd.to_datetime(df['Ngay_Giao_Dich'])
    df.set_index('Ngay_Giao_Dich', inplace=True)
    # Gom nhóm theo tháng
    monthly_sales = df['So_Luong'].resample('ME').sum()
    
    try:
        # Cấu hình SARIMA (p,d,q)(P,D,Q,s)
        model = SARIMAX(monthly_sales, order=(1, 0, 1), seasonal_order=(1, 0, 1, 12))
        fitted = model.fit(disp=False)
        forecast = fitted.forecast(steps=steps)
        return forecast.tolist()
    except:
        return []