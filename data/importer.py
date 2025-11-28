from typing import BinaryIO, Union
from collections.abc import Iterable

import logging
import re

from openpyxl import load_workbook
import pandas as pd

from config import DEFAULT_CITY


SourceType = Union[str, BinaryIO]


logger = logging.getLogger(__name__)

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


def _load_sheet_rows(source: SourceType) -> list[list[object]]:
    """Читает строки первого листа XLSX с вычисленными значениями."""

    current_source = _reset_stream(source)
    workbook = load_workbook(current_source, data_only=True)
    try:
        sheet = workbook.active
        rows: list[list[object]] = []
        max_columns = sheet.max_column or 0
        for row in sheet.iter_rows(values_only=True):
            values = list(row)
            if max_columns and len(values) < max_columns:
                values.extend([None] * (max_columns - len(values)))
            rows.append(values)
    finally:
        workbook.close()

    return rows


def _normalize(name: object) -> str:
    """Приводит имя колонки к нижнему регистру без лишних пробелов."""

    return " ".join(str(name).strip().lower().split())


def _string_value(value: object) -> str | None:
    """Возвращает строковое представление значения или None."""

    candidate = value

    if isinstance(candidate, (pd.Series, pd.Index)):
        iterable: Iterable = candidate.tolist()
    elif isinstance(candidate, (list, tuple, set)):
        iterable = list(candidate)
    else:
        iterable = None

    if iterable is not None:
        candidate = None
        for item in iterable:
            if item is None:
                continue
            try:
                if pd.isna(item):
                    continue
            except TypeError:
                pass
            candidate = item
            break

    if candidate is None:
        return None

    try:
        if pd.isna(candidate):
            return None
    except TypeError:
        pass

    text = str(candidate).strip()
    return text or None


def _number_value(value: object) -> float | None:
    """Преобразует ячейку с ценой к числу, обрабатывая коллекции и серии."""

    candidate = value

    if isinstance(candidate, (pd.Series, pd.Index)):
        iterable: Iterable = candidate.tolist()
    elif isinstance(candidate, (list, tuple, set)):
        iterable = list(candidate)
    else:
        iterable = None

    if iterable is not None:
        candidate = None
        for item in iterable:
            if item is None:
                continue
            try:
                if pd.isna(item):
                    continue
            except TypeError:
                pass
            candidate = item
            break

    if candidate is None:
        return None

    try:
        if pd.isna(candidate):
            return None
    except TypeError:
        pass

    if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
        number = float(candidate)
        return number if number > 0 else None

    text = str(candidate).strip()
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

    return number if number > 0 else None


def _quantity_value(value: object) -> float | None:
    """Возвращает числовое значение остатка, поддерживая коллекции и нули."""

    candidate = value

    if isinstance(candidate, (pd.Series, pd.Index)):
        iterable: Iterable = candidate.tolist()
    elif isinstance(candidate, (list, tuple, set)):
        iterable = list(candidate)
    else:
        iterable = None

    if iterable is not None:
        candidate = None
        for item in iterable:
            if item is None:
                continue
            try:
                if pd.isna(item):
                    continue
            except TypeError:
                pass
            candidate = item
            break

    if candidate is None:
        return None

    try:
        if pd.isna(candidate):
            return None
    except TypeError:
        pass

    if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
        return float(candidate)

    text = str(candidate).strip()
    if not text:
        return None

    normalized = text.replace("\xa0", " ")
    cleaned = re.sub(r"[^0-9,\.\-]", "", normalized)
    if cleaned == "":
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

    return number


def _build_multiheader_dataframe(rows: list[list[object]]) -> tuple[pd.DataFrame, dict[str, str]]:
    """Формирует датафрейм с учётом двухуровневой шапки цен."""

    top_index = 3
    bottom_index = 4
    if len(rows) <= bottom_index:
        raise ValueError("Недостаточно строк для многоуровневой шапки")

    top_row = rows[top_index]
    bottom_row = rows[bottom_index]
    combined_columns: list[str] = []
    last_top = ""

    max_len = max(len(top_row), len(bottom_row))

    for index in range(max_len):
        top_cell = top_row[index] if index < len(top_row) else None
        bottom_cell = bottom_row[index] if index < len(bottom_row) else None
        top_text = "" if top_cell is None else str(top_cell).strip()
        bottom_text = "" if bottom_cell is None else str(bottom_cell).strip()

        if not top_text:
            lower_bottom = bottom_text.lower()
            if lower_bottom in {"ролик", "отрез"} and last_top:
                top_text = last_top
        else:
            last_top = top_text

        if top_text and bottom_text:
            combined = f"{top_text}__{bottom_text}"
        else:
            combined = top_text or bottom_text

        combined_columns.append(combined)

    data_rows = rows[bottom_index + 1 :]
    if not data_rows:
        raise ValueError("Нет данных после шапки таблицы")

    df = pd.DataFrame(data_rows, columns=combined_columns)
    df = df.dropna(how="all")
    mapping = {_normalize(col): col for col in combined_columns}

    if "наименование коллекции" not in mapping:
        raise ValueError("Многоуровневая шапка не содержит колонку коллекции")

    return df, mapping


def _build_single_header_dataframe(
    rows: list[list[object]], header_index: int
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Формирует датафрейм с одиночной строкой заголовков."""

    if header_index >= len(rows):
        raise ValueError("Указанная строка заголовков отсутствует")

    header_row = rows[header_index]
    data_rows = rows[header_index + 1 :]
    if not data_rows:
        raise ValueError("Нет данных после строки заголовков")

    df = pd.DataFrame(data_rows, columns=header_row)
    df = df.dropna(how="all")
    mapping = {_normalize(col): col for col in df.columns}

    if "наименование коллекции" not in mapping:
        raise ValueError("Строка заголовков не содержит колонку коллекции")

    return df, mapping


def _read_fabric_frame(source: SourceType) -> tuple[pd.DataFrame, dict[str, str]]:
    """Возвращает датафрейм с колонками тканей и их сопоставление."""

    rows = _load_sheet_rows(source)
    if not rows:
        raise ValueError("Файл не содержит данных")

    try:
        return _build_multiheader_dataframe(rows)
    except ValueError:
        pass

    header_candidates = (0, 1, 2, 3, 4, 5)

    for header in header_candidates:
        try:
            return _build_single_header_dataframe(rows, header)
        except ValueError:
            continue

    raise ValueError("Не удалось найти заголовок с колонкой 'Наименование коллекции'")


def _resolve_column(columns: dict[str, str], *aliases: str) -> str | None:
    """Возвращает имя существующей колонки по набору псевдонимов."""

    for alias in aliases:
        normalized = _normalize(alias)
        if normalized in columns:
            return columns[normalized]
    return None


def parse_fabrics(source: SourceType, city: str = DEFAULT_CITY) -> list[dict]:
    """Разбирает XLSX с тканями и возвращает список товаров."""

    df, columns = _read_fabric_frame(source)

    name_column = columns.get("наименование коллекции")

    if logger.isEnabledFor(logging.INFO):
        logger.info("Колонки таблицы тканей: %s", repr(list(df.columns)))
        if name_column and name_column in df.columns:
            bison_rows = df[df[name_column] == "BISON"]
            if not bison_rows.empty:
                logger.info("Строка ткани BISON: %s", bison_rows.iloc[0].to_dict())

    price_columns: dict[tuple[str, str], str] = {}
    price_order = [
        ("85_90", "roll"),
        ("85_90", "piece"),
        ("90_95", "roll"),
        ("90_95", "piece"),
        ("95_100", "roll"),
        ("95_100", "piece"),
    ]

    column_list = list(df.columns)
    segment_column = columns.get("сегмент")
    wholesale_roll_column = columns.get("оптовая от ролика")
    wholesale_piece_column = columns.get("оптовая в отрез")
    special_column = columns.get("спеццена")

    def _column_index(target: str | None) -> int | None:
        """Возвращает индекс колонки или None."""

        if target is None:
            return None
        try:
            return column_list.index(target)
        except ValueError:
            return None

    segment_index = _column_index(segment_column)
    wholesale_roll_index = _column_index(wholesale_roll_column)
    wholesale_piece_index = _column_index(wholesale_piece_column)
    special_index = _column_index(special_column)

    base_index_candidates = [
        index for index in (wholesale_roll_index, wholesale_piece_index) if index is not None
    ]
    if base_index_candidates:
        base_index = max(base_index_candidates) + 1
    elif segment_index is not None:
        base_index = segment_index + 1
    else:
        base_index = 0

    candidates: list[str] = []
    current_index = base_index
    limit_index = special_index if special_index is not None else len(column_list)

    while current_index < limit_index and len(candidates) < len(price_order):
        column_name = column_list[current_index]
        current_index += 1
        if column_name is None:
            continue
        candidates.append(column_name)

    while len(candidates) < len(price_order) and current_index < len(column_list):
        column_name = column_list[current_index]
        current_index += 1
        if column_name is None:
            continue
        candidates.append(column_name)

    if len(candidates) >= len(price_order):
        for key, column in zip(price_order, candidates[: len(price_order)]):
            price_columns[key] = column
    else:
        logger.warning(
            "Недостаточно колонок цен для позиционного сопоставления: %s",
            candidates,
        )

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "Сопоставление колонок цен: %s",
            {
                f"{range_key}_{price_kind}": column
                for (range_key, price_kind), column in price_columns.items()
            },
        )

    items: list[dict] = []

    for _, row in df.iterrows():
        name = _string_value(row.get(name_column)) if name_column else None
        if not name:
            continue

        country = _string_value(row.get(columns.get("страна")))
        fabric_type = _string_value(row.get(columns.get("тип ткани")))
        segment = _string_value(row.get(columns.get("сегмент")))
        special_flag = _string_value(row.get(columns.get("спеццена")))

        record: dict[str, object] = {
            "city": city,
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


def parse_stock(source: SourceType, city: str = DEFAULT_CITY) -> list[dict]:
    """Разбирает XLSX с остатками товаров."""

    df_source = _reset_stream(source)
    df = pd.read_excel(df_source)
    columns = {_normalize(col): col for col in df.columns}

    section_col = _resolve_column(columns, "Раздел", "Section", "Раздел остатков")
    category_col = _resolve_column(columns, "Категория", "Группа")
    name_col = _resolve_column(columns, "Наименование", "Товар", "Название")
    article_col = _resolve_column(columns, "Артикул", "SKU", "Код")
    qty_col = _resolve_column(columns, "Наличие", "Остаток", "Количество", "Кол-во")
    unit_col = _resolve_column(columns, "Ед.", "Ед", "Единица", "единица")
    status_col = _resolve_column(columns, "Статус", "Статус наличия", "Availability")

    items: list[dict] = []

    for _, row in df.iterrows():
        name = _string_value(row.get(name_col)) if name_col else None
        if not name:
            continue

        section = _string_value(row.get(section_col)) if section_col else None
        category = _string_value(row.get(category_col)) if category_col else None
        article = _string_value(row.get(article_col)) if article_col else None
        quantity = _quantity_value(row.get(qty_col)) if qty_col else None
        unit = _string_value(row.get(unit_col)) if unit_col else None
        status = _string_value(row.get(status_col)) if status_col else None

        items.append(
            {
                "city": city,
                "section": section or "Наличие",
                "category": category or "Общий",
                "name": name,
                "article": article,
                "quantity": quantity,
                "unit": unit,
                "status": status,
            }
        )

    return items


def parse_hardware(source: SourceType, city: str = DEFAULT_CITY) -> list[dict]:
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
                "city": city,
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
