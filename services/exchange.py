import time
import aiohttp
from data.db_utils import get_setting, set_setting

RANGES = [(85, 90), (90, 95), (95, 100)]
CBR_URL = "https://www.cbr-xml-daily.ru/daily_json.js"
TTL_SEC = 6 * 3600  # кэш на 6 часов

async def _fetch_usd() -> float | None:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(CBR_URL, timeout=10) as r:
                j = await r.json()
                return float(j["Valute"]["USD"]["Value"])
    except Exception:
        return None

async def _get_usd_cached() -> float | None:
    ts = float((await get_setting("usd_cache_ts", "0")) or "0")
    now = time.time()
    if now - ts < TTL_SEC:
        val = await get_setting("usd_cache_value", "")
        try:
            return float(val)
        except Exception:
            pass
    usd = await _fetch_usd()
    if usd is not None:
        await set_setting("usd_cache_value", f"{usd}")
        await set_setting("usd_cache_ts", f"{now}")
    return usd

def _pick_range(usd: float) -> str:
    for a, b in RANGES:
        if a <= usd < b:
            return f"{a}_{b}"
    return "95_100"

async def current_range() -> tuple[str, float | None]:
    """
    Возвращает (коридор '85_90'|'90_95'|'95_100', курс USD или None).
    Режим — всегда авто (по заданию).
    """
    usd = await _get_usd_cached()
    if usd is None:
        # используем последний сохранённый диапазон, если есть
        rng = await get_setting("usd_range", "90_95")
        return rng, None
    rng = _pick_range(usd)
    await set_setting("usd_range", rng)
    return rng, usd

def range_label(rng: str, usd: float | None) -> str:
    pretty = rng.replace("_", "–")
    if usd is None:
        return f"Курс: н/д → {pretty}"
    return f"Курс: {usd:.2f} ₽ → {pretty}"


async def refresh_range() -> tuple[str, float | None]:
    """Принудительно обновляет курс и возвращает актуальный коридор."""

    usd = await _fetch_usd()
    if usd is not None:
        now = time.time()
        await set_setting("usd_cache_value", f"{usd}")
        await set_setting("usd_cache_ts", f"{now}")
        rng = _pick_range(usd)
        await set_setting("usd_range", rng)
        return rng, usd
    return await current_range()
