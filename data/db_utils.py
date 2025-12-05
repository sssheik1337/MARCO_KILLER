import logging

import aiosqlite
from config import DB_PATH, DEFAULT_CITY
from data.importer import debug_log


logger = logging.getLogger(__name__)


async def upsert_user(tg_id: int) -> None:
    """Сохраняет Telegram ID пользователя для последующих рассылок."""

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users(tg_id) VALUES(?)",
            (tg_id,),
        )
        await db.commit()


async def mark_user_blocked(tg_id: int) -> None:
    """Удаляет пользователя из рассылки, если он заблокировал бота."""

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM users WHERE tg_id=?", (tg_id,))
        await db.commit()


async def fetch_active_users() -> list[int]:
    """Возвращает список Telegram ID для рассылки."""

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT tg_id FROM users ORDER BY id")
        rows = await cur.fetchall()
    return [int(row[0]) for row in rows]


async def find_product_by_code(code: str) -> dict | None:
    """Ищет товар по артикулу без ограничения города."""

    normalized = (code or "").strip()
    if not normalized:
        return None

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT *
            FROM products
            WHERE lower(coalesce(article, '')) = lower(?)
            ORDER BY city
            LIMIT 1
            """,
            (normalized,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        cols = [c[0] for c in cur.description]
        return dict(zip(cols, row))

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

async def fetch_sections(city: str = DEFAULT_CITY) -> list[str]:
    """Возвращает список разделов каталога для указанного города."""

    sql = "SELECT DISTINCT section FROM products WHERE city=? ORDER BY section"
    params: tuple = (city,)

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(sql, params)
        rows = await cur.fetchall()
    return [r[0] for r in rows]


async def fetch_categories(section: str, city: str = DEFAULT_CITY) -> list[str]:
    """Возвращает категории для выбранного раздела и города."""

    base_sql = (
        "SELECT DISTINCT category FROM products WHERE section=? AND city=? ORDER BY category"
    )
    params: tuple = (section, city)

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(base_sql, params)
        rows = await cur.fetchall()
    return [r[0] for r in rows]


async def fetch_products_by_category(
    section: str,
    category: str,
    city: str = DEFAULT_CITY,
) -> list[tuple[int, str]]:
    """Возвращает товары выбранной категории и города."""

    sql = (
        "SELECT id, name FROM products WHERE section=? AND category=? AND city=? ORDER BY name"
    )
    params: tuple = (section, category, city)

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


# --- наличие ---


async def add_stock_items(
    db: aiosqlite.Connection, items: list[dict], city: str, section: str
) -> int:
    """Сохраняет остатки с учётом города и раздела."""

    await db.execute(
        "DELETE FROM stock_items WHERE city=? AND section=?",
        (city, section),
    )

    columns = [
        "city",
        "section",
        "code",
        "article",
        "name",
        "quantity",
        "unit",
        "extra_info",
        "date_in",
    ]

    placeholders = ",".join(["?"] * len(columns))
    stock_sql = f"INSERT INTO stock_items({','.join(columns)}) VALUES({placeholders})"

    payload: list[tuple] = []
    for item in items:
        name = item.get("name")
        article = item.get("article")
        if not name and not article:
            logger.warning("Запись пропущена: отсутствуют артикул и наименование")
            continue

        quantity = item.get("quantity")
        unit = item.get("unit")
        if quantity is None or unit is None:
            logger.warning("Запись пропущена: нет количества или единицы измерения")
            continue

        values = [
            item.get("city", city),
            item.get("section", section),
            item.get("code") or None,
            article or None,
            name,
            quantity,
            unit,
            item.get("extra_info") or item.get("status") or None,
            item.get("date_incoming") or item.get("date_in") or None,
        ]

        if len(values) != len(columns):
            raise ValueError("Количество полей записи не соответствует числу столбцов таблицы")

        payload.append(tuple(values))

    logger.info(f"Сохраняем {len(payload)} записей в таблицу stock...")

    inserted_count = 0
    if payload:
        await db.executemany(stock_sql, payload)
        inserted_count = len(payload)

    await db.commit()
    logger.info(f"Импорт завершён. Добавлено записей: {inserted_count}")

    return inserted_count


async def fetch_stock_sections(city: str = DEFAULT_CITY) -> list[str]:
    """Возвращает разделы из таблицы наличия для указанного города."""

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT DISTINCT section FROM stock_items WHERE city=? ORDER BY section",
            (city,),
        )
        rows = await cur.fetchall()
    return [row[0] for row in rows]


async def fetch_stock_categories(section: str, city: str = DEFAULT_CITY) -> list[str]:
    """Возвращает категории наличия для раздела и города."""

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT DISTINCT category FROM stock_items WHERE section=? AND city=? ORDER BY category",
            (section, city),
        )
        rows = await cur.fetchall()
    return [row[0] for row in rows]


async def fetch_stock_products_by_category(
    section: str, category: str, city: str = DEFAULT_CITY
) -> list[tuple[int, str]]:
    """Возвращает товары наличия указанной категории и города."""

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, name FROM stock_items WHERE section=? AND category=? AND city=? ORDER BY name",
            (section, category, city),
        )
        rows = await cur.fetchall()
    return [(int(row[0]), row[1]) for row in rows]


async def fetch_stock_item(pid: int) -> dict:
    """Возвращает запись наличия по идентификатору."""

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT * FROM stock_items WHERE id=?", (pid,))
        row = await cur.fetchone()
        if not row:
            return {}
        cols = [c[0] for c in cur.description]
        return dict(zip(cols, row))


async def _table_has_column(db: aiosqlite.Connection, table: str, column: str) -> bool:
    """Проверяет наличие столбца в таблице перед выполнением выборки."""

    cur = await db.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in await cur.fetchall()]
    return column in columns


async def find_catalog_product_by_article(article: str) -> tuple[str, dict] | None:
    """Ищет товар по артикулу в каталогах тканей и фурнитуры."""

    normalized = (article or "").strip()
    if not normalized:
        return None

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT * FROM hardware_catalog WHERE article = ? LIMIT 1",
            (normalized,),
        )
        row = await cur.fetchone()
        if row:
            cols = [c[0] for c in cur.description]
            return "hardware", dict(zip(cols, row))

        if await _table_has_column(db, "fabrics_catalog", "article"):
            cur = await db.execute(
                "SELECT * FROM fabrics_catalog WHERE article = ? LIMIT 1",
                (normalized,),
            )
            row = await cur.fetchone()
            if row:
                cols = [c[0] for c in cur.description]
                return "fabrics", dict(zip(cols, row))

    return None
