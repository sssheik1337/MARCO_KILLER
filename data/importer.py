from typing import BinaryIO, Union

import re

import pandas as pd


SourceType = Union[str, BinaryIO]

_PRICE_RANGES = {
    "85_90": "85-90",
    "90_95": "90-95",
    "95_100": "95-100",
}


def _reset_stream(source: SourceType) -> SourceType:
    """Возвращает источник в начало, если он поток."""

    if hasattr(source, "seek"):
        source.seek(0)
    return source


def _normalize(name: object) -> str:
    """Приводит имя колонки к нижнему регистру без лишних пробелов."""

    return " ".join(str(name).strip().lower().split())


def _string_value(value: object) -> str | None:
    """Возвращает строковое представление значения или None."""

    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _number_value(value: object) -> float | None:
    """Преобразует ячейку с ценой к числу."""

    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None

    normalized = text.replace("\xa0", " ")
    cleaned = re.sub(r"[^0-9,\.\-]", "", normalized)
    if not cleaned:
        return None

    negative = cleaned.startswith("-")
    if negative:
        cleaned = cleaned[1:]

    cleaned = cleaned.strip()
    if not cleaned:
        return None

    last_comma = cleaned.rfind(",")
    last_dot = cleaned.rfind(".")

    number_text = cleaned
    decimal_sep = None
    thousands_sep = None

    if last_comma != -1 or last_dot != -1:
        if last_comma > last_dot:
            decimal_sep = ","
            thousands_sep = "." if last_dot != -1 else None
        elif last_dot > last_comma:
            decimal_sep = "."
            thousands_sep = "," if last_comma != -1 else None
        else:
            decimal_sep = "," if last_comma != -1 else "."

        if thousands_sep:
            number_text = number_text.replace(thousands_sep, "")
        if decimal_sep != ".":
            number_text = number_text.replace(decimal_sep, ".")

    number_text = number_text.replace(" ", "")

    try:
        number = float(number_text)
    except (TypeError, ValueError):
        return None

    if negative:
        number = -number

    if number <= 0:
        return None

    return number


def _read_fabric_frame(source: SourceType) -> tuple[pd.DataFrame, dict[str, str]]:
    """Подбирает корректный заголовок и возвращает датафрейм с маппингом колонок."""

    header_candidates = (0, 1, 2, 3, 4, 5)

    for header in header_candidates:
        current_source = _reset_stream(source)
        df = pd.read_excel(current_source, header=header)
        mapping = {_normalize(col): col for col in df.columns}
        if "наименование коллекции" in mapping:
            return df, mapping

    raise ValueError("Не удалось найти заголовок с колонкой 'Наименование коллекции'")


def _resolve_column(columns: dict[str, str], *aliases: str) -> str | None:
    """Возвращает имя существующей колонки по набору псевдонимов."""

    for alias in aliases:
        normalized = _normalize(alias)
        if normalized in columns:
            return columns[normalized]
    return None


def parse_fabrics(source: SourceType) -> list[dict]:
    """Разбирает XLSX с тканями и возвращает список товаров."""

    df, columns = _read_fabric_frame(source)

    price_columns: dict[tuple[str, str], str] = {}
    for column in df.columns:
        normalized = _normalize(column)
        for range_key, range_label in _PRICE_RANGES.items():
            if range_label in normalized:
                if "рол" in normalized:
                    price_columns[(range_key, "roll")] = column
                elif "отр" in normalized:
                    price_columns[(range_key, "piece")] = column

    items: list[dict] = []
    name_column = columns.get("наименование коллекции")

    for _, row in df.iterrows():
        name = _string_value(row.get(name_column)) if name_column else None
        if not name:
            continue

        country = _string_value(row.get(columns.get("страна")))
        fabric_type = _string_value(row.get(columns.get("тип ткани")))
        segment = _string_value(row.get(columns.get("сегмент")))
        special_flag = _string_value(row.get(columns.get("спеццена")))

        record: dict[str, object] = {
            "section": "fabrics",
            "category": "Ткани",
            "name": name,
            "country": country,
            "fabric_type": fabric_type,
            "segment": segment,
            "special": special_flag,
            "in_stock": None,
        }

        for range_key in _PRICE_RANGES:
            for price_kind in ("piece", "roll"):
                column_name = price_columns.get((range_key, price_kind))
                field_name = f"price_{price_kind}_{range_key}"
                record[field_name] = (
                    _number_value(row.get(column_name)) if column_name else None
                )

        items.append(record)

    return items


def parse_hardware(source: SourceType) -> list[dict]:
    """Разбирает XLSX с фурнитурой."""

    df_source = _reset_stream(source)
    df = pd.read_excel(df_source, header=10)
    columns = {_normalize(col): col for col in df.columns}

    article_col = _resolve_column(columns, "Артикул")
    name_col = _resolve_column(columns, "Наименование")
    collection_col = _resolve_column(columns, "Коллекция")
    status_col = _resolve_column(columns, "Статус")
    multiplicity_col = _resolve_column(columns, "Кратность")
    brand_col = _resolve_column(columns, "Бренд (Страна)", "Бренд")
    unit_col = _resolve_column(columns, "Ед.", "Ед")
    currency_col = _resolve_column(columns, "Валюта")
    rrc_col = _resolve_column(columns, "РРЦ")
    opt_col = _resolve_column(columns, "Оптовая", "Опт")

    items: list[dict] = []

    for _, row in df.iterrows():
        article = _string_value(row.get(article_col)) if article_col else None
        if not article:
            continue

        name = _string_value(row.get(name_col)) if name_col else None
        collection = _string_value(row.get(collection_col)) if collection_col else None
        status = _string_value(row.get(status_col)) if status_col else None
        multiplicity = _string_value(row.get(multiplicity_col)) if multiplicity_col else None
        brand_country = _string_value(row.get(brand_col)) if brand_col else None
        unit = _string_value(row.get(unit_col)) if unit_col else None
        currency = _string_value(row.get(currency_col)) if currency_col else None
        if currency:
            currency = currency.upper()

        items.append(
            {
                "section": "hardware",
                "category": collection or "Фурнитура",
                "subcategory": None,
                "name": name or article,
                "article": article,
                "collection": collection,
                "brand_country": brand_country,
                "multiplicity": multiplicity,
                "unit": unit,
                "currency": currency,
                "status": status,
                "price_rrc": _number_value(row.get(rrc_col)) if rrc_col else None,
                "price_opt": _number_value(row.get(opt_col)) if opt_col else None,
                "in_stock": None,
            }
        )

    return items
