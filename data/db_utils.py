import aiosqlite
from config import DB_PATH

CREATE_SQL = [
    """
    CREATE TABLE IF NOT EXISTS products (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      section TEXT NOT NULL,             -- 'fabrics' | 'hardware'
      category TEXT NOT NULL,
      subcategory TEXT,
      name TEXT NOT NULL,
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
      -- ткани: цены по коридорам (могут быть NULL для фурнитуры)
      price_piece_85_90 REAL,
      price_roll_85_90  REAL,
      price_piece_90_95 REAL,
      price_roll_90_95  REAL,
      price_piece_95_100 REAL,
      price_roll_95_100  REAL,
      -- фурнитура:
      price_rrc REAL,
      price_opt REAL,
      special TEXT,                      -- дополнительная отметка (распродажа, новинка и т.д.)
      in_stock INTEGER,
      image_url TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_section_cat ON products(section, category);",
    """
    CREATE TABLE IF NOT EXISTS settings (
      key TEXT PRIMARY KEY,
      value TEXT
    );
    """
]

async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        for sql in CREATE_SQL:
            await db.execute(sql)
        await _ensure_product_columns(db)
        await db.commit()


async def _ensure_product_columns(db: aiosqlite.Connection) -> None:
    """Добавляет отсутствующие колонки в таблицу products."""

    required = {
        "collection": "TEXT",
        "brand_country": "TEXT",
        "multiplicity": "TEXT",
        "unit": "TEXT",
        "currency": "TEXT",
        "status": "TEXT",
    }

    cur = await db.execute("PRAGMA table_info(products)")
    existing = {row[1] for row in await cur.fetchall()}

    for column, definition in required.items():
        if column in existing:
            continue
        await db.execute(f"ALTER TABLE products ADD COLUMN {column} {definition}")

async def get_setting(key: str, default: str="") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cur.fetchone()
    return row[0] if row else default

async def set_setting(key: str, value: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        await db.commit()

async def fetch_sections(only_available: bool = False) -> list[str]:
    """Возвращает список разделов каталога."""

    sql = "SELECT DISTINCT section FROM products"
    params: tuple = ()
    if only_available:
        sql += " WHERE COALESCE(in_stock, 0) > 0"
    sql += " ORDER BY section"

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(sql, params)
        rows = await cur.fetchall()
    return [r[0] for r in rows]


async def fetch_categories(section: str, only_available: bool = False) -> list[str]:
    """Возвращает категории для выбранного раздела."""

    base_sql = "SELECT DISTINCT category FROM products WHERE section=?"
    params: tuple = (section,)
    if only_available:
        base_sql += " AND COALESCE(in_stock, 0) > 0"
    base_sql += " ORDER BY category"

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(base_sql, params)
        rows = await cur.fetchall()
    return [r[0] for r in rows]


async def fetch_products_by_category(
    section: str,
    category: str,
    only_available: bool = False,
) -> list[tuple[int, str]]:
    """Возвращает товары выбранной категории."""

    sql = "SELECT id, name FROM products WHERE section=? AND category=?"
    params: tuple = (section, category)
    if only_available:
        sql += " AND COALESCE(in_stock, 0) > 0"
    sql += " ORDER BY name"

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(sql, params)
        return [(int(r[0]), r[1]) for r in await cur.fetchall()]

async def fetch_product(pid: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT * FROM products WHERE id=?", (pid,))
        row = await cur.fetchone()
        if not row: return {}
        cols = [c[0] for c in cur.description]
        return dict(zip(cols, row))
