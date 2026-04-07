import sqlite3
from contextlib import closing
from datetime import datetime

import pandas as pd

import os
DB_PATH = os.getenv('INVENTORY_DB_PATH', 'data/inventory.db')
ALLOWED_ITEMS = ('CAT_VANG', 'CAT_XAY')
VALID_TRANSACTION_TYPES = {'Nhap', 'Xuat'}
ITEM_ORDER_SQL = "CASE Ma_Hang WHEN 'CAT_VANG' THEN 1 WHEN 'CAT_XAY' THEN 2 ELSE 99 END"
ADJUSTMENT_PREFIX = '[ADJ]'

PLANNING_CONFIG = {
    'CAT_VANG': {
        'lead_time_days': 2,
        'target_stock': 2200.0,
        'default_supplier': 'NCC Mỏ Cát A',
    },
    'CAT_XAY': {
        'lead_time_days': 2,
        'target_stock': 1800.0,
        'default_supplier': 'NCC Mỏ Cát B',
    },
}


class InventoryValidationError(ValueError):
    pass


class InventoryStockError(ValueError):
    pass


def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def _normalize_item_code(ma_hang: str) -> str:
    code = (ma_hang or '').strip().upper()
    if code not in ALLOWED_ITEMS:
        raise InventoryValidationError(
            'Hệ thống hiện chỉ hỗ trợ 2 mặt hàng cố định: CAT_VANG và CAT_XAY.'
        )
    return code


def _normalize_transaction_type(loai_gd: str) -> str:
    tx_type = (loai_gd or '').strip().title()
    if tx_type not in VALID_TRANSACTION_TYPES:
        raise InventoryValidationError("Loại giao dịch chỉ chấp nhận 'Nhap' hoặc 'Xuat'.")
    return tx_type


def _normalize_quantity(so_luong) -> float:
    try:
        qty = float(so_luong)
    except (TypeError, ValueError) as exc:
        raise InventoryValidationError('Số lượng phải là số hợp lệ.') from exc
    if qty <= 0:
        raise InventoryValidationError('Số lượng phải lớn hơn 0.')
    return round(qty, 2)


def get_dm_hanghoa() -> pd.DataFrame:
    query = f'''
        SELECT *
        FROM DM_HangHoa
        WHERE Ma_Hang IN ('CAT_VANG', 'CAT_XAY')
        ORDER BY {ITEM_ORDER_SQL}
    '''
    with closing(get_connection()) as conn:
        return pd.read_sql_query(query, conn)


def get_stock() -> pd.DataFrame:
    query = f'''
        SELECT *
        FROM Kho_Hien_Tai
        WHERE Ma_Hang IN ('CAT_VANG', 'CAT_XAY')
        ORDER BY {ITEM_ORDER_SQL}
    '''
    with closing(get_connection()) as conn:
        return pd.read_sql_query(query, conn)


def get_history(limit: int | None = None, include_adjustments: bool = True) -> pd.DataFrame:
    query = '''
        SELECT ID, Ngay_Giao_Dich, Loai_GD, Ma_Hang, So_Luong, Doi_Tac
        FROM Nhat_Ky_Giao_Dich
        WHERE Ma_Hang IN ('CAT_VANG', 'CAT_XAY')
    '''
    params: list[object] = []
    if not include_adjustments:
        query += " AND (Doi_Tac IS NULL OR Doi_Tac NOT LIKE '[ADJ]%')"
    query += ' ORDER BY datetime(Ngay_Giao_Dich) DESC, ID DESC'
    if limit is not None:
        query += ' LIMIT ?'
        params.append(int(limit))
    with closing(get_connection()) as conn:
        return pd.read_sql_query(query, conn, params=params)


def get_adjustment_history(limit: int | None = 50) -> pd.DataFrame:
    query = '''
        SELECT ID, Ngay_Giao_Dich, Loai_GD, Ma_Hang, So_Luong, Doi_Tac
        FROM Nhat_Ky_Giao_Dich
        WHERE Ma_Hang IN ('CAT_VANG', 'CAT_XAY')
          AND Doi_Tac LIKE '[ADJ]%'
        ORDER BY datetime(Ngay_Giao_Dich) DESC, ID DESC
    '''
    params: list[object] = []
    if limit is not None:
        query += ' LIMIT ?'
        params.append(int(limit))
    with closing(get_connection()) as conn:
        return pd.read_sql_query(query, conn, params=params)


def get_current_stock(ma_hang: str) -> float:
    code = _normalize_item_code(ma_hang)
    with closing(get_connection()) as conn:
        row = conn.execute(
            'SELECT So_Luong_Ton FROM Kho_Hien_Tai WHERE Ma_Hang = ?',
            (code,),
        ).fetchone()
    if row is None:
        raise InventoryValidationError(f'Không tìm thấy mã hàng: {code}')
    return round(float(row['So_Luong_Ton']), 2)


def add_transaction(loai_gd, ma_hang, so_luong, doi_tac):
    tx_type = _normalize_transaction_type(loai_gd)
    item_code = _normalize_item_code(ma_hang)
    qty = _normalize_quantity(so_luong)
    partner = (doi_tac or '').strip()
    if not partner:
        partner = 'Chưa cập nhật đối tác'

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('BEGIN IMMEDIATE')

        item = cursor.execute(
            'SELECT 1 FROM DM_HangHoa WHERE Ma_Hang = ?',
            (item_code,),
        ).fetchone()
        if item is None:
            raise InventoryValidationError(f'Mã hàng không tồn tại: {item_code}')

        stock_row = cursor.execute(
            'SELECT So_Luong_Ton FROM Kho_Hien_Tai WHERE Ma_Hang = ?',
            (item_code,),
        ).fetchone()
        if stock_row is None:
            raise InventoryValidationError(f'Chưa có tồn kho cho mã hàng: {item_code}')

        current_stock = float(stock_row['So_Luong_Ton'])
        if tx_type == 'Xuat' and qty > current_stock:
            raise InventoryStockError(
                f'Không đủ tồn kho để xuất. {item_code} hiện còn {current_stock:,.1f} m3.'
            )

        new_stock = current_stock + qty if tx_type == 'Nhap' else current_stock - qty
        if new_stock < 0:
            raise InventoryStockError('Giao dịch bị từ chối vì sẽ làm âm tồn kho.')

        cursor.execute(
            '''
            INSERT INTO Nhat_Ky_Giao_Dich
                (Ngay_Giao_Dich, Loai_GD, Ma_Hang, So_Luong, Doi_Tac)
            VALUES (?, ?, ?, ?, ?)
            ''',
            (now, tx_type, item_code, qty, partner),
        )
        cursor.execute(
            '''
            UPDATE Kho_Hien_Tai
            SET So_Luong_Ton = ?, Ngay_Cap_Nhat_Cuoi = ?
            WHERE Ma_Hang = ?
            ''',
            (round(new_stock, 2), now, item_code),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def adjust_stock_to_actual(ma_hang, so_luong_thuc_te, ly_do='Kiểm kê định kỳ', nguoi_kiem='Thủ kho'):
    item_code = _normalize_item_code(ma_hang)
    try:
        actual_qty = float(so_luong_thuc_te)
    except (TypeError, ValueError) as exc:
        raise InventoryValidationError('Số lượng thực tế phải là số hợp lệ.') from exc
    if actual_qty < 0:
        raise InventoryValidationError('Số lượng thực tế không được âm.')

    current_stock = get_current_stock(item_code)
    delta = round(actual_qty - current_stock, 2)
    if delta == 0:
        raise InventoryValidationError('Số lượng thực tế trùng với hệ thống, không cần điều chỉnh.')

    reason = (ly_do or 'Kiểm kê định kỳ').strip()
    checker = (nguoi_kiem or 'Thủ kho').strip()
    partner = f'{ADJUSTMENT_PREFIX} {checker} - {reason}'

    if delta > 0:
        add_transaction('Nhap', item_code, delta, partner)
    else:
        add_transaction('Xuat', item_code, abs(delta), partner)

    return {
        'ma_hang': item_code,
        'he_thong': current_stock,
        'thuc_te': round(actual_qty, 2),
        'chenh_lech': delta,
        'loai_dieu_chinh': 'Tang' if delta > 0 else 'Giam',
    }


def get_partner_summary(loai_gd: str, limit: int = 10) -> pd.DataFrame:
    tx_type = _normalize_transaction_type(loai_gd)
    query = '''
        SELECT Doi_Tac,
               COUNT(*) AS So_Giao_Dich,
               ROUND(SUM(So_Luong), 1) AS Tong_Khoi_Luong,
               MAX(Ngay_Giao_Dich) AS Giao_Dich_Gan_Nhat
        FROM Nhat_Ky_Giao_Dich
        WHERE Loai_GD = ?
          AND Ma_Hang IN ('CAT_VANG', 'CAT_XAY')
          AND (Doi_Tac IS NULL OR Doi_Tac NOT LIKE '[ADJ]%')
        GROUP BY Doi_Tac
        ORDER BY Tong_Khoi_Luong DESC, So_Giao_Dich DESC
        LIMIT ?
    '''
    with closing(get_connection()) as conn:
        return pd.read_sql_query(query, conn, params=[tx_type, int(limit)])


__all__ = [
    'DB_PATH',
    'ALLOWED_ITEMS',
    'PLANNING_CONFIG',
    'ADJUSTMENT_PREFIX',
    'InventoryValidationError',
    'InventoryStockError',
    'get_dm_hanghoa',
    'get_stock',
    'get_history',
    'get_adjustment_history',
    'get_current_stock',
    'get_partner_summary',
    'add_transaction',
    'adjust_stock_to_actual',
]