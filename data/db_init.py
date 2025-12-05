import os
import sqlite3

import aiosqlite

from config import DB_PATH


async def init_db() -> None:
    """Создаёт все необходимые таблицы, если они отсутствуют."""

    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    create_sql = """
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        city TEXT NOT NULL,
        section TEXT NOT NULL,
        category TEXT,
        subcategory TEXT,
        name TEXT,
        article TEXT,
        country TEXT,
        fabric_type TEXT,
        segment TEXT,
        collection TEXT,
        brand_country TEXT,
        multiplicity TEXT,
        unit TEXT,
        currency TEXT,
        status TEXT,
        price_piece_85_90 REAL,
        price_roll_85_90 REAL,
        price_piece_90_95 REAL,
        price_roll_90_95 REAL,
        price_piece_95_100 REAL,
        price_roll_95_100 REAL,
        price_rrc REAL,
        price_opt REAL,
        special TEXT,
        in_stock REAL,
        image_url TEXT
    );

    CREATE TABLE IF NOT EXISTS stock_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        city TEXT NOT NULL,
        section TEXT NOT NULL,
        kind TEXT,
        item_type TEXT,
        category TEXT,
        article TEXT,
        name TEXT,
        quantity REAL,
        free_quantity REAL,
        unit TEXT,
        program TEXT,
        reserve REAL,
        arrival_date TEXT,
        code TEXT,
        extra_info TEXT,
        date_in TEXT
    );

    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tg_id INTEGER UNIQUE NOT NULL
    );

    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );

    CREATE TABLE IF NOT EXISTS fabrics_catalog (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        country TEXT,
        fabric_type TEXT,
        segment TEXT,
        wholesale_roll REAL,
        wholesale_piece REAL,
        price_roll_85_90 REAL,
        price_piece_85_90 REAL,
        price_roll_90_95 REAL,
        price_piece_90_95 REAL,
        price_roll_95_100 REAL,
        price_piece_95_100 REAL,
        special_status TEXT,
        image_url TEXT
    );

    CREATE TABLE IF NOT EXISTS hardware_catalog (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        article TEXT,
        name TEXT,
        collection TEXT,
        status TEXT,
        multiplicity TEXT,
        brand_country TEXT,
        unit TEXT,
        currency TEXT,
        price_rrc REAL,
        price_opt REAL,
        image_url TEXT
    );

    CREATE TABLE IF NOT EXISTS fabrics_stock_spb (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        catalog_id INTEGER,
        name TEXT,
        quantity REAL,
        free_quantity REAL,
        unit TEXT,
        arrival_date TEXT,
        reserved TEXT,
        additional_info TEXT
    );

    CREATE TABLE IF NOT EXISTS fabrics_stock_msk (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        catalog_id INTEGER,
        name TEXT,
        quantity REAL,
        free_quantity REAL,
        unit TEXT,
        arrival_date TEXT,
        reserved TEXT,
        additional_info TEXT
    );

    CREATE TABLE IF NOT EXISTS hardware_stock_spb (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        catalog_id INTEGER,
        name TEXT,
        article TEXT,
        quantity REAL,
        free_quantity REAL,
        unit TEXT,
        arrival_date TEXT,
        reserved TEXT,
        additional_info TEXT
    );

    CREATE TABLE IF NOT EXISTS hardware_stock_msk (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        catalog_id INTEGER,
        name TEXT,
        article TEXT,
        quantity REAL,
        free_quantity REAL,
        unit TEXT,
        arrival_date TEXT,
        reserved TEXT,
        additional_info TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_fabrics_stock_spb_catalog_id ON fabrics_stock_spb(catalog_id);
    CREATE INDEX IF NOT EXISTS idx_fabrics_stock_msk_catalog_id ON fabrics_stock_msk(catalog_id);
    CREATE INDEX IF NOT EXISTS idx_hardware_stock_spb_catalog_id ON hardware_stock_spb(catalog_id);
    CREATE INDEX IF NOT EXISTS idx_hardware_stock_msk_catalog_id ON hardware_stock_msk(catalog_id);
    """

    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(create_sql)
        await ensure_column(db, "products", "city", "TEXT")
        await ensure_column(db, "stock_items", "city", "TEXT")
        await ensure_column(db, "stock_items", "kind", "TEXT")
        await ensure_column(db, "stock_items", "item_type", "TEXT")
        await ensure_column(db, "stock_items", "code", "TEXT")
        await ensure_column(db, "stock_items", "extra_info", "TEXT")
        await ensure_column(db, "stock_items", "date_in", "TEXT")
        await db.commit()


async def ensure_column(db: aiosqlite.Connection, table: str, column: str, type_def: str):
    """Добавляет отсутствующий столбец, если он нужен для текущей схемы."""

    try:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {type_def}")
    except sqlite3.OperationalError:
        pass
