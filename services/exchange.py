import aiohttp
from data.db_utils import get_setting, set_setting

RANGES = [(85,90), (90,95), (95,100)]

async def get_usd() -> float | None:
    # ЦБ РФ JSON (без ключей): https://www.cbr-xml-daily.ru/daily_json.js
    url = "https://www.cbr-xml-daily.ru/daily_json.js"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=10) as r:
                j = await r.json()
                return float(j["Valute"]["USD"]["Value"])
    except Exception:
        return None

def pick_range(usd: float) -> str:
    for a,b in RANGES:
        if a <= usd < b: return f"{a}_{b}"
    return "95_100"  # дефолт вверх

async def current_range() -> str:
    mode = await get_setting("usd_mode","auto")        # auto|manual
    if mode == "manual":
        return await get_setting("usd_range","90_95")
    usd = await get_usd()
    if usd is None:
        return await get_setting("usd_range","90_95")  # последняя сохранённая
    rng = pick_range(usd)
    await set_setting("usd_range", rng)
    return rng
