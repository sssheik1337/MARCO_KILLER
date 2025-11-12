import pandas as pd
import re

def _col(df, names):  # ищем первую подходящую колонку
    for n in names:
        if n in df.columns: return n
    return None

def parse_fabrics(xlsx_path: str) -> list[dict]:
    df = pd.read_excel(xlsx_path, header=4)  # у твоего файла хедер с 5-й строки
    # авто-поиск столбцов цен по коридорам
    price_cols = {}
    for col in df.columns:
        m = re.search(r"(85-90|90-95|95-100).*?(РОЛИК|отрез)", str(col), re.I)
        if m:
            rng = m.group(1).replace('-', '_')
            kind = "roll" if m.group(2).lower().startswith("рол") else "piece"
            price_cols[f"{kind}_{rng}"] = col

    items = []
    for _, r in df.iterrows():
        name = str(r.get(_col(df, ["Наименование коллекции","Коллекция"]))).strip()
        if name in ("nan","None",""):
            continue
        rec = {
            "section": "fabrics",
            "category": "Ткани",
            "name": name,
            "country": r.get(_col(df, ["Страна"])),
            "fabric_type": r.get(_col(df, ["Тип ткани"])),
            "segment": r.get(_col(df, ["сегмент","Сегмент"])),
            "special": (str(r.get(_col(df, ["спеццена","Статус"]))).strip().lower()
                        if pd.notna(r.get(_col(df, ["спеццена","Статус"]))) else None),
            "in_stock": 0
        }
        # нормализуем special
        if isinstance(rec["special"], str):
            if "распрод" in rec["special"]: rec["special"] = "sale"
            elif "новин" in rec["special"]: rec["special"] = "new"
            else: rec["special"] = None
        # цены по коридорам
        for key, col in price_cols.items():
            v = r.get(col)
            if pd.notna(v):
                rec[f"price_{key}"] = float(str(v).replace(" ", "").replace("р","").replace(",", "."))
        items.append(rec)
    return items

def parse_hardware(xlsx_path: str) -> list[dict]:
    df = pd.read_excel(xlsx_path, header=10)  # по скрину заголовки около 11 строки
    items = []
    for _, r in df.iterrows():
        name = r.get(_col(df, ["Наименование"]))
        art = r.get(_col(df, ["Артикул"]))
        if pd.isna(name) and pd.isna(art):
            continue
        items.append({
            "section": "hardware",
            "category": str(r.get(_col(df, ["Коллекция"])) or "Фурнитура"),
            "name": str(name),
            "article": str(art) if pd.notna(art) else None,
            "country": str(r.get(_col(df, ["Бренд (Страна)"])) or ""),
            "price_rrc": _num(r.get(_col(df, ["РРЦ"]))),
            "price_opt": _num(r.get(_col(df, ["Оптовая"]))),
            "in_stock": None,
        })
    return items

def _num(v):
    if pd.isna(v): return None
    s = str(v).replace(" ", "").replace("RUB","").replace(",", ".")
    try: return float(s)
    except: return None
