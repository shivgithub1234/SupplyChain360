"""SQLite persistence. Each operation gets its own connection/transaction."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def runtime():
    path = Path(os.environ.get('SC360_DATA_DIR', ROOT / 'runtime'))
    path.mkdir(parents=True, exist_ok=True)
    return path

@contextmanager
def connect():
    conn = sqlite3.connect(runtime() / 'supplychain.db', timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        with conn:
            yield conn
    finally:
        conn.close()

def initialize():
    with connect() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS suppliers (
            supplier_id TEXT PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS inventory (
            sku TEXT PRIMARY KEY, name TEXT NOT NULL,
            supplier_id TEXT NOT NULL REFERENCES suppliers(supplier_id),
            quantity INTEGER NOT NULL CHECK(quantity>=0),
            counted_quantity INTEGER NOT NULL CHECK(counted_quantity>=0),
            reorder_point INTEGER NOT NULL CHECK(reorder_point>=0),
            unit_cost REAL NOT NULL CHECK(unit_cost>=0),
            opening_quantity INTEGER NOT NULL CHECK(opening_quantity>=0),
            consumed_quantity INTEGER NOT NULL CHECK(consumed_quantity>=0));
        CREATE TABLE IF NOT EXISTS purchase_orders (
            po_id TEXT PRIMARY KEY, sku TEXT NOT NULL REFERENCES inventory(sku),
            supplier_id TEXT NOT NULL REFERENCES suppliers(supplier_id),
            quantity INTEGER NOT NULL CHECK(quantity>0),
            status TEXT NOT NULL CHECK(status IN ('pending','shipped','delivered')),
            ordered_date TEXT NOT NULL, expected_date TEXT NOT NULL, delivered_date TEXT);
        CREATE TABLE IF NOT EXISTS alerts (
            alert_key TEXT PRIMARY KEY, rule TEXT NOT NULL, entity TEXT NOT NULL,
            severity TEXT NOT NULL, message TEXT NOT NULL, active INTEGER NOT NULL,
            first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, escalated INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, kind TEXT NOT NULL,
            message TEXT NOT NULL, channel TEXT NOT NULL DEFAULT 'local_outbox');
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, status TEXT NOT NULL,
            duration_ms REAL, rows_loaded INTEGER DEFAULT 0, error TEXT, sla_met INTEGER);
        CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL);
        ''')

def rows(table):
    allowed = {'suppliers','inventory','purchase_orders','alerts','notifications','runs','audit'}
    if table not in allowed:
        raise ValueError('Unknown table')
    with connect() as conn:
        return [dict(r) for r in conn.execute(f'SELECT * FROM {table}')]
