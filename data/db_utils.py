import logging

import aiosqlite
from config import DB_PATH, DEFAULT_CITY


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
    """Возвращает разделы каталога для выбранного города и общих записей (city='all')."""

    sql = (
        "SELECT DISTINCT section FROM products "
        "WHERE city IN (?, 'all') ORDER BY section"
    )
    params: tuple = (city,)

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(sql, params)
        rows = await cur.fetchall()
    return [r[0] for r in rows]


async def fetch_categories(section: str, city: str = DEFAULT_CITY) -> list[str]:
    """Возвращает уникальные категории для раздела тканей."""

    sql = (
        "SELECT DISTINCT category "
        "FROM products "
        "WHERE section=? AND category IS NOT NULL AND category != '' "
        "ORDER BY category"
    )

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(sql, (section,))
        rows = await cur.fetchall()
    return [r[0] for r in rows]


async def fetch_products_by_category(category: str) -> list[dict]:
    """Возвращает товары выбранного сегмента без учёта города и подкатегорий."""

    sql = (
        "SELECT * "
        "FROM products "
        "WHERE section='fabrics' "
        "  AND category=? "
        "ORDER BY name"
    )

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(sql, (category,))
        rows = await cur.fetchall()
        cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in rows]


async def fetch_product(name: str) -> dict:
    """Ищет товар ткани по точному совпадению имени."""

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT *
            FROM products
            WHERE section='fabrics'
              AND name=?
            LIMIT 1
            """,
            (name,),
        )
        row = await cur.fetchone()
        if not row:
            return {}
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
        "kind",
        "item_type",
        "code",
        "article",
        "name",
        "quantity",
        "free_quantity",
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
        if name is None and article is None:
            logger.warning("Запись пропущена: отсутствуют артикул и наименование")
            continue

        quantity = item.get("quantity")
        unit = item.get("unit")
        city_value = item.get("city", city)
        section_value = item.get("section", section)
        if unit is None:
            logger.warning("Запись пропущена: нет количества или единицы измерения")
            continue
        if quantity is None and not (city_value == "spb" and section_value == "fabrics"):
            logger.warning("Запись пропущена: нет количества или единицы измерения")
            continue

        values = [
            city_value,
            section_value,
            item.get("kind") or None,
            item.get("item_type") or None,
            item.get("code") or None,
            article or None,
            name,
            quantity,
            item.get("free_quantity"),
            unit,
            item.get("extra_info") or item.get("status") or None,
            item.get("date_incoming") or item.get("date_in") or None,
        ]

        if len(values) != len(columns):
            raise ValueError("Количество полей записи не соответствует числу столбцов таблицы")

        payload.append(tuple(values))

    logger.info(f"Сохраняем {len(payload)} записей в stock_items...")

    inserted_count = 0
    if payload:
        await db.executemany(stock_sql, payload)
        inserted_count = len(payload)

    await db.commit()
    logger.info(f"Импорт завершён: добавлено {inserted_count} записей.")

    return inserted_count


async def fetch_stock_items(city: str, section: str) -> list[dict]:
    """Возвращает остатки по городу и разделу."""

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT city, section, kind, item_type, code, article, name, quantity, free_quantity, unit, extra_info, date_in
            FROM stock_items
            WHERE city = ?
              AND section = ?
            ORDER BY name
            """,
            (city, section),
        )
        rows = await cur.fetchall()
        columns = [col[0] for col in cur.description]
    return [dict(zip(columns, row)) for row in rows]


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
    """Возвращает список категорий для раздела и города."""

    items = await fetch_stock_items(city, section)
    if not items:
        return []

    return ["Все позиции"]


async def fetch_stock_products_by_category(
    section: str, category: str, city: str = DEFAULT_CITY
) -> list[tuple[int, str]]:
    """Возвращает товары наличия указанной категории и города."""

    items = await fetch_stock_items(city, section)
    return [
        (idx, item.get("name")) for idx, item in enumerate(items) if item.get("name")
    ]


async def fetch_stock_item(city: str, section: str, index: int) -> dict:
    """Возвращает запись наличия по индексу из списка для города и раздела."""

    items = await fetch_stock_items(city, section)
    if index < 0 or index >= len(items):
        return {}
    return items[index]


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
