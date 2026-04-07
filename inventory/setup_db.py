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
OPENING_STOCK = {
    'CAT_VANG': 1550.0,
    'CAT_XAY': 1220.0,
}
SCHEDULED_IMPORT = {
    'CAT_VANG': 300.0,
    'CAT_XAY': 250.0,
}
EMERGENCY_IMPORT = {
    'CAT_VANG': 900.0,
    'CAT_XAY': 700.0,
}
MIN_BUFFER = {
    'CAT_VANG': 220.0,
    'CAT_XAY': 160.0,
}


def _create_tables(cursor):
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS DM_HangHoa (
            Ma_Hang TEXT PRIMARY KEY CHECK (Ma_Hang IN ('CAT_VANG', 'CAT_XAY')),
            Ten_Hang TEXT NOT NULL,
            Don_Vi TEXT NOT NULL,
            Nguong_An_Toan REAL NOT NULL CHECK (Nguong_An_Toan >= 0),
            Don_Gia REAL NOT NULL CHECK (Don_Gia >= 0)
        )
        '''
    )
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS Kho_Hien_Tai (
            Ma_Hang TEXT PRIMARY KEY CHECK (Ma_Hang IN ('CAT_VANG', 'CAT_XAY')),
            So_Luong_Ton REAL NOT NULL CHECK (So_Luong_Ton >= 0),
            Ngay_Cap_Nhat_Cuoi TEXT NOT NULL,
            FOREIGN KEY (Ma_Hang) REFERENCES DM_HangHoa(Ma_Hang)
        )
        '''
    )
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS Nhat_Ky_Giao_Dich (
            ID INTEGER PRIMARY KEY AUTOINCREMENT,
            Ngay_Giao_Dich TEXT NOT NULL,
            Loai_GD TEXT NOT NULL CHECK (Loai_GD IN ('Nhap', 'Xuat')),
            Ma_Hang TEXT NOT NULL CHECK (Ma_Hang IN ('CAT_VANG', 'CAT_XAY')),
            So_Luong REAL NOT NULL CHECK (So_Luong > 0),
            Doi_Tac TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (Ma_Hang) REFERENCES DM_HangHoa(Ma_Hang)
        )
        '''
    )
    cursor.execute(
        'CREATE INDEX IF NOT EXISTS idx_nhat_ky_ngay ON Nhat_Ky_Giao_Dich(Ngay_Giao_Dich)'
    )


def _add_import(history, stock, when_dt, item_code, quantity, partner):
    qty = round(float(quantity), 1)
    history.append(
        (
            when_dt.strftime('%Y-%m-%d %H:%M:%S'),
            'Nhap',
            item_code,
            qty,
            partner,
        )
    )
    stock[item_code] = round(stock[item_code] + qty, 1)


def _add_export(history, stock, when_dt, item_code, quantity, partner):
    qty = round(float(quantity), 1)
    history.append(
        (
            when_dt.strftime('%Y-%m-%d %H:%M:%S'),
            'Xuat',
            item_code,
            qty,
            partner,
        )
    )
    stock[item_code] = round(stock[item_code] - qty, 1)


def build_history(days: int = 730, seed: int = 42):
    np.random.seed(seed)
    now = datetime.now().replace(second=0, microsecond=0)
    history_end = now - timedelta(days=1)
    stock = {code: float(value) for code, value in OPENING_STOCK.items()}
    history: list[tuple[str, str, str, float, str]] = []

    for offset in range(days, -1, -1):
        current_date = history_end - timedelta(days=offset)
        month = current_date.month
        factor = 0.3 if month in [7, 8] else (1.5 if month in [1, 2, 11, 12] else 1.0)

        if offset % 15 == 0:
            _add_import(
                history,
                stock,
                current_date.replace(hour=8, minute=0),
                'CAT_VANG',
                SCHEDULED_IMPORT['CAT_VANG'],
                'NCC Mỏ Cát A',
            )
            _add_import(
                history,
                stock,
                current_date.replace(hour=8, minute=5),
                'CAT_XAY',
                SCHEDULED_IMPORT['CAT_XAY'],
                'NCC Mỏ Cát B',
            )

        for _ in range(np.random.randint(1, 4)):
            export_time = current_date.replace(
                hour=int(np.random.randint(7, 18)),
                minute=int(np.random.randint(0, 60)),
            )

            qty_vang = round(float(np.random.randint(10, 30) * factor), 1)
            qty_xay = round(float(np.random.randint(8, 25) * factor), 1)

            if stock['CAT_VANG'] < qty_vang + MIN_BUFFER['CAT_VANG']:
                _add_import(
                    history,
                    stock,
                    current_date.replace(hour=6, minute=int(np.random.randint(0, 20))),
                    'CAT_VANG',
                    max(EMERGENCY_IMPORT['CAT_VANG'], qty_vang * 4),
                    'NCC Mỏ Cát A - Bổ sung nhanh',
                )
            if stock['CAT_XAY'] < qty_xay + MIN_BUFFER['CAT_XAY']:
                _add_import(
                    history,
                    stock,
                    current_date.replace(hour=6, minute=20 + int(np.random.randint(0, 20))),
                    'CAT_XAY',
                    max(EMERGENCY_IMPORT['CAT_XAY'], qty_xay * 4),
                    'NCC Mỏ Cát B - Bổ sung nhanh',
                )

            _add_export(history, stock, export_time, 'CAT_VANG', qty_vang, 'Khách lẻ / Công trình')
            _add_export(history, stock, export_time, 'CAT_XAY', qty_xay, 'Công trình B')

    history.sort(key=lambda row: row[0])
    return history, stock, now


def init_db(days: int = 730):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    _create_tables(cursor)

    cursor.execute('DELETE FROM Nhat_Ky_Giao_Dich')
    cursor.execute('DELETE FROM Kho_Hien_Tai')
    cursor.execute('DELETE FROM DM_HangHoa')

    cursor.executemany('INSERT INTO DM_HangHoa VALUES (?,?,?,?,?)', CATALOG)

    history_data, current_stock, now = build_history(days=days)

    cursor.executemany(
        '''
        INSERT INTO Nhat_Ky_Giao_Dich
            (Ngay_Giao_Dich, Loai_GD, Ma_Hang, So_Luong, Doi_Tac)
        VALUES (?, ?, ?, ?, ?)
        ''',
        history_data,
    )

    stock_rows = [
        (code, round(current_stock[code], 1), now.strftime('%Y-%m-%d %H:%M:%S'))
        for code, *_ in CATALOG
    ]
    cursor.executemany('INSERT INTO Kho_Hien_Tai VALUES (?,?,?)', stock_rows)

    conn.commit()
    conn.close()

    print('✅ Đã tạo database chỉ gồm 2 mặt hàng cát và đồng bộ tồn kho với lịch sử giao dịch.')
    print('📦 Tồn hiện tại:')
    for code, qty, _ in stock_rows:
        print(f'   - {code}: {qty:,.1f} m³')


if __name__ == '__main__':
    init_db()