"""Extract from CSV, SQLite or a JSON REST endpoint; validate before loading."""
import math
import sqlite3
import time
from pathlib import Path
import httpx
import pandas as pd
from app.db import connect

COLUMNS = {
    'suppliers': ['supplier_id','name'],
    'inventory': ['sku','name','supplier_id','quantity','counted_quantity','reorder_point','unit_cost','opening_quantity','consumed_quantity'],
    'purchase_orders': ['po_id','sku','supplier_id','quantity','status','ordered_date','expected_date','delivered_date'],
}

def retry(operation, attempts=3, delay=0.2):
    """Retry transient network/SQLite locks only; never retry invalid business data."""
    for attempt in range(attempts):
        try:
            return operation()
        except (httpx.TransportError, httpx.HTTPStatusError, sqlite3.OperationalError) as exc:
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500 and exc.response.status_code != 429:
                raise
            if isinstance(exc, sqlite3.OperationalError) and 'locked' not in str(exc).lower():
                raise
            if attempt == attempts - 1:
                raise
            time.sleep(delay * 2 ** attempt)

def extract(kind, location):
    if kind == 'csv':
        return {t: pd.read_csv(Path(location) / f'{t}.csv', dtype=str, keep_default_na=False) for t in COLUMNS}
    if kind == 'sqlite':
        uri = Path(location).resolve().as_uri() + '?mode=ro'
        with sqlite3.connect(uri, uri=True) as conn:
            return {t: pd.read_sql_query(f'SELECT * FROM {t}', conn) for t in COLUMNS}
    if kind == 'api':
        def fetch():
            response = httpx.get(location, timeout=20, follow_redirects=False)
            response.raise_for_status()
            return response.json()
        payload = retry(fetch)
        return {t: pd.DataFrame(payload[t]) for t in COLUMNS}
    raise ValueError('Source must be csv, sqlite or api')

def validate(frames):
    clean = {}
    for table, columns in COLUMNS.items():
        frame = frames[table].copy()
        missing = set(columns) - set(frame.columns)
        if missing:
            raise ValueError(f'{table}: missing columns {sorted(missing)}')
        frame = frame[columns].fillna('')
        for col in columns:
            frame[col] = frame[col].astype(str).str.strip()
            if col != 'delivered_date' and frame[col].eq('').any():
                raise ValueError(f'{table}.{col}: blank values')
        key = columns[0]
        if frame[key].duplicated().any():
            raise ValueError(f'{table}: duplicate {key}')
        numeric = [c for c in columns if c in {'quantity','counted_quantity','reorder_point','unit_cost','opening_quantity','consumed_quantity'}]
        for col in numeric:
            values = pd.to_numeric(frame[col], errors='raise')
            if not values.map(math.isfinite).all() or (values < 0).any() or (values > 1e12).any():
                raise ValueError(f'{table}.{col}: expected finite values between 0 and 1e12')
            if col != 'unit_cost' and (values % 1 != 0).any():
                raise ValueError(f'{table}.{col}: whole numbers required')
            frame[col] = values.astype(float if col == 'unit_cost' else 'int64')
        clean[table] = frame
    suppliers, inventory, orders = (clean[t] for t in COLUMNS)
    if not set(inventory.supplier_id) <= set(suppliers.supplier_id):
        raise ValueError('Inventory references an unknown supplier')
    if not set(orders.supplier_id) <= set(suppliers.supplier_id) or not set(orders.sku) <= set(inventory.sku):
        raise ValueError('Purchase order references an unknown supplier or SKU')
    orders['status'] = orders.status.str.lower()
    if not orders.status.isin(['pending','shipped','delivered']).all() or (orders.quantity <= 0).any():
        raise ValueError('Orders require a valid status and positive quantity')
    for col in ['ordered_date','expected_date','delivered_date']:
        values = orders[col]
        nonempty = values.ne('')
        if not values[nonempty].str.fullmatch(r'\d{4}-\d{2}-\d{2}').all():
            raise ValueError(f'{col}: use YYYY-MM-DD')
        pd.to_datetime(values[nonempty], format='%Y-%m-%d', errors='raise')
    if (orders.expected_date < orders.ordered_date).any():
        raise ValueError('Expected date precedes ordered date')
    delivered = orders.status.eq('delivered')
    if (delivered != orders.delivered_date.ne('')).any():
        raise ValueError('Only delivered orders must have a delivery date')
    if (orders.loc[delivered, 'delivered_date'] < orders.loc[delivered, 'ordered_date']).any():
        raise ValueError('Delivery date precedes ordered date')
    orders.loc[~delivered, 'delivered_date'] = None
    return clean

def load(frames, timestamp):
    """Replace the complete operational snapshot atomically; history is retained."""
    def transaction():
        with connect() as conn:
            for table in reversed(COLUMNS):
                conn.execute(f'DELETE FROM {table}')
            for table, columns in COLUMNS.items():
                placeholders = ','.join('?' for _ in columns)
                conn.executemany(f'INSERT INTO {table} ({",".join(columns)}) VALUES ({placeholders})', frames[table].itertuples(index=False, name=None))
            count = sum(len(f) for f in frames.values())
            conn.execute('INSERT INTO audit(created_at,action,detail) VALUES (?,?,?)', (timestamp,'snapshot_loaded',f'{count} rows'))
        return count
    return retry(transaction)
