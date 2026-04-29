import os
import sqlite3
from datetime import datetime, timedelta
import numpy as np

DB_PATH = 'data/inventory.db'
os.makedirs('data', exist_ok=True)

CATALOG = [
    ('CAT_VANG', 'Cát vàng hạt lớn', 'm³', 200, 250000),
    ('CAT_XAY', 'Cát xây tô', 'm³', 150, 180000),
]

def _create_tables(cursor):
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS DM_HangHoa (
            Ma_Hang TEXT PRIMARY KEY, Ten_Hang TEXT, Don_Vi TEXT, Nguong_An_Toan REAL, Don_Gia REAL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Kho_Hien_Tai (
            Ma_Hang TEXT PRIMARY KEY, So_Luong_Ton REAL, Ngay_Cap_Nhat_Cuoi TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Nhat_Ky_Giao_Dich (
            ID INTEGER PRIMARY KEY AUTOINCREMENT, Ngay_Giao_Dich TEXT, Loai_GD TEXT, 
            Ma_Hang TEXT, So_Luong REAL, Doi_Tac TEXT
        )
    ''')

def generate_stationary_timeseries(days=1460, seed=42):
    """
    Tạo dữ liệu 4 năm (1460 ngày) có tính chu kỳ và phương sai ổn định (Stationary).
    Sử dụng hàm Sine để tạo mùa vụ và White Noise để tạo nhiễu ngẫu nhiên.
    """
    np.random.seed(seed)
    now = datetime.now().replace(hour=17, minute=0, second=0, microsecond=0)
    
    history = []
    # Tồn kho ban đầu
    stock = {'CAT_VANG': 500.0, 'CAT_XAY': 400.0}
    
    # Các hằng số cho hàm chuỗi thời gian (Time Series)
    # y(t) = Baseline + Amplitude * sin(2 * pi * t / 365) + Noise
    baseline_vang, amp_vang = 20, 10
    baseline_xay, amp_xay = 15, 8
    
    # Duyệt từ 4 năm trước đến hôm nay
    for offset in range(days, -1, -1):
        current_date = now - timedelta(days=offset)
        t = current_date.timetuple().tm_yday # Ngày thứ mấy trong năm (1-365)
        
        # 1. Tính toán lượng xuất kho (Sales) theo mô hình SARIMA lý tưởng
        # Dùng sin() để tạo chu kỳ. Bán mạnh cuối/đầu năm, giảm vào giữa năm (tháng 7, 8)
        seasonality_factor = np.cos(2 * np.pi * (t - 30) / 365) 
        
        noise_vang = np.random.normal(0, 3) # Nhiễu trắng (White noise), mean=0, std=3
        noise_xay = np.random.normal(0, 2)
        
        out_vang = max(1.0, round(baseline_vang + amp_vang * seasonality_factor + noise_vang, 1))
        out_xay = max(1.0, round(baseline_xay + amp_xay * seasonality_factor + noise_xay, 1))
        
        # Ghi nhận giao dịch xuất
        history.append((current_date.strftime('%Y-%m-%d 10:30:00'), 'Xuat', 'CAT_VANG', out_vang, 'Khách lẻ/Công trình'))
        history.append((current_date.strftime('%Y-%m-%d 14:15:00'), 'Xuat', 'CAT_XAY', out_xay, 'Công trình B'))
        stock['CAT_VANG'] -= out_vang
        stock['CAT_XAY'] -= out_xay
        
        # 2. Logic nhập kho tự động (Replenishment)
        # Giữ cho tồn kho không bị cạn kiệt và xoay quanh một mức trung bình
        if stock['CAT_VANG'] < 250:
            import_qty = round(np.random.normal(400, 20), 1)
            history.append((current_date.strftime('%Y-%m-%d 08:00:00'), 'Nhap', 'CAT_VANG', import_qty, 'NCC Mỏ Cát A'))
            stock['CAT_VANG'] += import_qty
            
        if stock['CAT_XAY'] < 200:
            import_qty = round(np.random.normal(300, 15), 1)
            history.append((current_date.strftime('%Y-%m-%d 08:30:00'), 'Nhap', 'CAT_XAY', import_qty, 'NCC Mỏ Cát B'))
            stock['CAT_XAY'] += import_qty

    return history, stock, now

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    _create_tables(cursor)
    cursor.execute('DELETE FROM Nhat_Ky_Giao_Dich')
    cursor.execute('DELETE FROM Kho_Hien_Tai')
    cursor.execute('DELETE FROM DM_HangHoa')

    # Thêm danh mục
    cursor.executemany('INSERT INTO DM_HangHoa VALUES (?,?,?,?,?)', CATALOG)

    # Sinh data Time Series 4 năm (1460 ngày)
    history_data, current_stock, now = generate_stationary_timeseries(days=1460)

    # Thêm lịch sử giao dịch
    cursor.executemany('''
        INSERT INTO Nhat_Ky_Giao_Dich (Ngay_Giao_Dich, Loai_GD, Ma_Hang, So_Luong, Doi_Tac)
        VALUES (?, ?, ?, ?, ?)
    ''', history_data)

    # Cập nhật tồn kho hiện tại
    stock_rows = [(code, round(current_stock[code], 1), now.strftime('%Y-%m-%d %H:%M:%S')) for code in current_stock]
    cursor.executemany('INSERT INTO Kho_Hien_Tai VALUES (?,?,?)', stock_rows)

    conn.commit()
    conn.close()
    print(" Đã tạo thành công Database 4 năm với dữ liệu chuỗi thời gian (Stationary).")

if __name__ == '__main__':
    init_db()