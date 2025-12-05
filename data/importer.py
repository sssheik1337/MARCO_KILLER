"""Модуль импорта прайс-листов и остатков из XLSX/CSV в словари."""
from __future__ import annotations

import io
import logging
import re
import sqlite3
from typing import BinaryIO, Union

import chardet
import pandas as pd
from openpyxl import load_workbook

from config import DB_PATH

SourceType = Union[str, BinaryIO]


class FormatError(Exception):
    """Исключение для ошибок формата входного файла."""


class SchemaMismatchError(Exception):
    """Исключение для несоответствия структуры таблицы ожидаемому формату."""

    def __init__(self, table_type: str, missing: list):
        super().__init__()
        self.table_type = table_type
        self.missing = missing
        logger.error(f"[SCHEMA ERROR] type={table_type} missing={self.missing}")


TABLE_SCHEMAS = {
    "fabrics_catalog": {
        "required_columns": [
            "Наименование коллекции",
            "Страна",
            "Тип ткани",
            "сегмент",
            "РОЛИК_85_90",
            "ОТРЕЗ_85_90",
            "РОЛИК_90_95",
            "ОТРЕЗ_90_95",
            "РОЛИК_95_100",
            "ОТРЕЗ_95_100",
            "статус",
        ],
        "template_path": "templates/fabrics_catalog_example.xlsx",
    },
    "hardware_catalog": {
        "required_columns": [
            "Артикул",
            "Наименование",
            "Коллекция",
            "Статус",
            "Кратность",
            "Бренд (Страна)",
            "Ед.",
            "Валюта",
            "РРЦ",
            "Оптовая",
        ],
        "template_path": "templates/hardware_catalog_example.xlsx",
    },
    "stock_fabrics_spb": {
        "required_columns": [
            "Номенклатура",
            "Остаток",
            "Свободный остаток",
        ],
        "template_path": "templates/stock_fabrics_spb_example.xlsx",
    },
    "stock_fabrics_msk": {
        "required_columns": [
            "Код товара",
            "Вид номенклатуры",
            "Тип номенклатуры",
            "Артикул",
            "Номенклатура",
            "Программа",
            "Наличие",
            "Ед.",
            "Доп. инфо.",
            "Дата прихода",
        ],
        "template_path": "templates/stock_fabrics_msk_example.xlsx",
    },
    "stock_hardware_spb": {
        "required_columns": [
            "Номенклатура",
            "Остаток",
            "Свободный остаток",
        ],
        "template_path": "templates/stock_hardware_spb_example.xlsx",
    },
    "stock_hardware_msk": {
        "required_columns": [
            "Код товара",
            "Вид номенклатуры",
            "Тип номенклатуры",
            "Артикул",
            "Номенклатура",
            "Программа",
            "Наличие",
            "Ед.",
            "Доп. инфо.",
            "Дата прихода",
            "Резерв",
        ],
        "template_path": "templates/stock_hardware_msk_example.xlsx",
    },
}


logger = logging.getLogger(__name__)


# ---------------------------------- служебные функции ----------------------------------

def _reset_stream(source: SourceType) -> SourceType:
    """Возвращает поток в начало, если он поддерживает seek."""

    if hasattr(source, "seek"):
        source.seek(0)
    return source


def _normalize_header(value: object) -> str:
    """Нормализует заголовок колонки: нижний регистр и одиночные пробелы."""

    return " ".join(str(value or "").strip().lower().split())


def _string(value: object) -> str | None:
    """Возвращает строку без лишних пробелов или None для пустых/NaN значений."""

    if isinstance(value, (list, tuple, set, pd.Series, pd.Index)):
        for item in value:
            result = _string(item)
            if result is not None:
                return result
        return None

    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass

    text = str(value).strip()
    return text or None


def _number(value: object) -> float | None:
    """Преобразует значение в float, очищая пробелы, запятые и валютные суффиксы."""

    if isinstance(value, (list, tuple, set, pd.Series, pd.Index)):
        for item in value:
            result = _number(item)
            if result is not None:
                return result
        return None

    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)

    text = str(value).strip()
    if not text:
        return None

    normalized = text.replace("\xa0", " ")
    cleaned = re.sub(r"[^0-9,\.\-]", "", normalized)
    if cleaned in {"", "-", ",", "."}:
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


def _number_or_error(value: object, column_title: str) -> float | None:
    """Пытается преобразовать значение в число или сообщает об ошибке."""

    number = _number(value)
    if number is not None:
        return number

    text = _string(value)
    if text not in (None, "", "-", "—"):
        raise Exception(
            f"Ошибка: некорректное числовое значение в столбце «{column_title}»."
        )

    return None


def _detect_format(source: SourceType) -> str:
    """Определяет формат файла по расширению или сигнатуре."""

    name = getattr(source, "name", None) if not isinstance(source, str) else source
    prefix_bytes: bytes | None = None

    if isinstance(source, str):
        try:
            with open(source, "rb") as handle:
                prefix_bytes = handle.read(4)
        except OSError:
            prefix_bytes = None
    elif hasattr(source, "read"):
        current = _reset_stream(source)
        prefix = current.read(4)
        _reset_stream(current)
        prefix_bytes = prefix.encode() if isinstance(prefix, str) else prefix

    def _xls_not_supported() -> None:
        raise Exception("Формат XLS не поддерживается. Используйте XLSX")

    if name:
        lowered = name.lower()
        if lowered.endswith(".xls"):
            _xls_not_supported()
        if lowered.endswith(".xlsx"):
            if prefix_bytes is not None and not prefix_bytes.startswith(b"PK"):
                _xls_not_supported()
            return "xlsx"
        if lowered.endswith(".csv"):
            return "csv"

    if prefix_bytes is not None and prefix_bytes.startswith(b"PK"):
        return "xlsx"

    return "csv"


def _load_xlsx_rows(source: SourceType) -> list[list[object]]:
    """Читает XLSX с вычисленными формулами и возвращает список строк."""

    current = _reset_stream(source)
    try:
        workbook = load_workbook(current, data_only=True)
    except Exception as exc:  # noqa: BLE001
        logger.error("Ошибка загрузки XLSX", exc_info=True)
        raise Exception(
            "Ошибка при чтении XLSX-файла. Проверьте, что файл не повреждён и соответствует формату XLSX."
        ) from exc

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


def _load_csv_rows(source: SourceType) -> list[list[object]]:
    """Читает CSV без заголовков и возвращает список строк."""

    try:
        if isinstance(source, str):
            with open(source, "rb") as handle:
                data = handle.read()
        else:
            current = _reset_stream(source)
            data = current.read()
            _reset_stream(current)

        detection = chardet.detect(data)
        encoding = detection.get("encoding") or "utf-8"
        buffer = io.BytesIO(data)
        df = pd.read_csv(buffer, header=None, encoding=encoding)
        return df.where(pd.notna(df), None).values.tolist()
    except UnicodeDecodeError as exc:
        logger.error("Ошибка декодирования CSV", exc_info=True)
        raise Exception("Ошибка чтения CSV: некорректная кодировка файла.") from exc
    except pd.errors.ParserError as exc:  # type: ignore[attr-defined]
        logger.error("Ошибка парсинга CSV", exc_info=True)
        raise Exception("Ошибка: некорректная структура CSV-файла.") from exc
    except Exception as exc:  # noqa: BLE001
        logger.error("Неизвестная ошибка при чтении CSV", exc_info=True)
        raise Exception("Ошибка чтения CSV-файла. Проверьте корректность данных.") from exc


def _load_rows(source: SourceType) -> list[list[object]]:
    """Возвращает все строки файла вне зависимости от формата."""

    fmt = _detect_format(source)
    if fmt == "xlsx":
        return _load_xlsx_rows(source)
    if fmt == "csv":
        return _load_csv_rows(source)
    raise FormatError("Формат файла не поддерживается. Используйте XLSX или CSV")


def _ensure_columns(columns: dict[str, object], required: list[str]) -> None:
    """Проверяет наличие обязательных колонок, выбрасывая осмысленную ошибку."""

    for title in required:
        if _normalize_header(title) not in columns:
            raise Exception(
                f"Ошибка: отсутствует столбец «{title}». Проверьте разметку таблицы."
            )


def _validate_headers(table_type: str, headers: list[str]) -> None:
    """Проверяет структуру таблицы по ожидаемой схеме."""

    schema = TABLE_SCHEMAS[table_type]
    required = schema["required_columns"]
    if not headers or all((h or "").strip() == "" for h in headers):
        missing = required
    else:
        missing = [c for c in required if c not in headers]

    if missing:
        logger.error(
            f"Ошибка структуры ({table_type}): отсутствуют колонки: {missing}",
        )
        raise SchemaMismatchError(table_type, missing)


def _row_value(row: list[object], index: int) -> object:
    """Безопасно получает значение ячейки по индексу."""

    return row[index] if 0 <= index < len(row) else None


def _load_catalog_index(table: str) -> tuple[dict[str, int], dict[str, int]]:
    """Возвращает словари поиска по артикулу и названию для каталога."""

    article_map: dict[str, int] = {}
    name_map: dict[str, int] = {}
    with sqlite3.connect(DB_PATH) as conn:
        try:
            cur = conn.execute(f"SELECT id, article, name FROM {table}")
            rows = cur.fetchall()
            for catalog_id, article, name in rows:
                if article:
                    article_map[_normalize_header(article)] = int(catalog_id)
                if name:
                    name_map[_normalize_header(name)] = int(catalog_id)
            return article_map, name_map
        except sqlite3.OperationalError:
            return article_map, name_map


def _find_catalog_id(
    article: str | None, name: str | None, article_map: dict[str, int], name_map: dict[str, int]
) -> int | None:
    """Ищет id каталога по артикулу или названию."""

    if article:
        normalized = _normalize_header(article)
        if normalized in article_map:
            return article_map[normalized]
    if name:
        normalized = _normalize_header(name)
        if normalized in name_map:
            return name_map[normalized]
    return None


# ---------------------------------- парсинг каталогов ----------------------------------

def parse_fabrics_catalog(stream: SourceType) -> list[dict]:
    """Парсит общий каталог тканей."""

    try:
        table_type = "fabrics_catalog"
        rows = _load_rows(stream)
        if not rows:
            return []

        logger.info(f"Импорт {table_type} для города -")

        header_index = None
        for idx, row in enumerate(rows):
            first_cell = _normalize_header(_row_value(row, 0))
            if first_cell == "наименование коллекции":
                header_index = idx
                break

        if header_index is None:
            raise Exception(
                "Ошибка: отсутствует столбец «Наименование коллекции». Проверьте разметку таблицы."
            )

        header_row = rows[header_index]
        top_row = rows[header_index - 1] if header_index > 0 else [None] * len(header_row)

        columns: dict[str, int] = {}
        for idx, value in enumerate(header_row):
            columns[_normalize_header(value)] = idx

        required_columns = [
            "Наименование коллекции",
            "Страна",
            "Тип ткани",
            "сегмент",
            "Оптовая от ролика",
            "Оптовая в отрез",
        ]
        _ensure_columns(columns, required_columns)

        price_columns: dict[tuple[str, str], int] = {}
        range_map = {"85-90": "85_90", "90-95": "90_95", "95-100": "95_100"}
        for idx, bottom in enumerate(header_row):
            bottom_norm = _normalize_header(bottom)
            top_text = _string(_row_value(top_row, idx)) or ""
            range_key = range_map.get(top_text.strip())
            if bottom_norm in {"ролик", "отрез"} and range_key:
                kind = "roll" if bottom_norm == "ролик" else "piece"
                price_columns[(range_key, kind)] = idx

        for human, key in [
            ("РОЛИК (85-90)", ("85_90", "roll")),
            ("отрез (85-90)", ("85_90", "piece")),
            ("РОЛИК (90-95)", ("90_95", "roll")),
            ("отрез (90-95)", ("90_95", "piece")),
            ("РОЛИК (95-100)", ("95_100", "roll")),
            ("отрез (95-100)", ("95_100", "piece")),
        ]:
            if key not in price_columns:
                raise Exception(
                    f"Ошибка: отсутствует столбец «{human}». Проверьте разметку таблицы."
                )

        status_index = columns.get(_normalize_header("статус"))
        special_index = status_index
        if special_index is None:
            for idx, value in enumerate(header_row):
                if value is None or str(value).strip() == "":
                    special_index = idx
                    break

        headers = [
            "Наименование коллекции",
            "Страна",
            "Тип ткани",
            "сегмент",
        ]
        for range_key in ("85_90", "90_95", "95_100"):
            if (range_key, "roll") in price_columns:
                headers.append(f"РОЛИК_{range_key}")
            if (range_key, "piece") in price_columns:
                headers.append(f"ОТРЕЗ_{range_key}")
        if special_index is not None:
            headers.append("статус")

        _validate_headers(table_type, headers)

        items: list[dict] = []
        for row in rows[header_index + 1 :]:
            name = _string(_row_value(row, columns["наименование коллекции"]))
            if not name:
                logger.warning("Запись пропущена: нет наименования строки")
                continue

            item = {
                "name": name,
                "country": _string(_row_value(row, columns["страна"])),
                "fabric_type": _string(_row_value(row, columns["тип ткани"])),
                "segment": _string(_row_value(row, columns["сегмент"])),
                "wholesale_roll": _number_or_error(
                    _row_value(row, columns["оптовая от ролика"]),
                    "Оптовая от ролика",
                ),
                "wholesale_piece": _number_or_error(
                    _row_value(row, columns["оптовая в отрез"]),
                    "Оптовая в отрез",
                ),
                "price_roll_85_90": _number_or_error(
                    _row_value(row, price_columns[("85_90", "roll")]),
                    "РОЛИК (85-90)",
                ),
                "price_piece_85_90": _number_or_error(
                    _row_value(row, price_columns[("85_90", "piece")]),
                    "отрез (85-90)",
                ),
                "price_roll_90_95": _number_or_error(
                    _row_value(row, price_columns[("90_95", "roll")]),
                    "РОЛИК (90-95)",
                ),
                "price_piece_90_95": _number_or_error(
                    _row_value(row, price_columns[("90_95", "piece")]),
                    "отрез (90-95)",
                ),
                "price_roll_95_100": _number_or_error(
                    _row_value(row, price_columns[("95_100", "roll")]),
                    "РОЛИК (95-100)",
                ),
                "price_piece_95_100": _number_or_error(
                    _row_value(row, price_columns[("95_100", "piece")]),
                    "отрез (95-100)",
                ),
                "special_status": _string(_row_value(row, special_index)) if special_index is not None else None,
                "image_url": None,
            }
            items.append(item)

        logger.info(f"Получено валидных записей: {len(items)}")

        return items
    except Exception as exc:  # noqa: BLE001
        logger.error("Ошибка импорта каталога тканей", exc_info=True)
        raise Exception(f"Ошибка при импорте каталога тканей: {exc}") from exc


def parse_hardware_catalog(stream: SourceType) -> list[dict]:
    """Парсит общий каталог фурнитуры."""

    try:
        table_type = "hardware_catalog"
        rows = _load_rows(stream)
        if not rows:
            return []

        logger.info(f"Импорт {table_type} для города -")

        required_titles = [
            "Артикул",
            "Фото",
            "Наименование",
            "Коллекция",
            "Статус",
            "Кратность",
            "Бренд (Страна)",
            "Ед.",
            "Валюта",
            "РРЦ",
            "Оптовая",
        ]

        header_index = None
        columns: dict[str, str] = {}
        header_row: list[object] | None = None
        for idx, row in enumerate(rows):
            temp_columns = {_normalize_header(val): val for val in row}
            try:
                _ensure_columns(temp_columns, required_titles)
                header_index = idx
                columns = temp_columns
                header_row = row
                break
            except Exception:
                continue

        if header_index is None or header_row is None:
            temp_columns = {_normalize_header(val): val for val in rows[0]}
            _ensure_columns(temp_columns, required_titles)
            header_index = 0
            header_row = rows[0]
            columns = temp_columns

        headers = [(_string(val) or "").strip() for val in header_row]
        _validate_headers(table_type, headers)

        data_rows = rows[header_index + 1 :]
        df = pd.DataFrame(data_rows, columns=header_row)
        df = df.dropna(how="all")

        items: list[dict] = []
        for _, row in df.iterrows():
            article = _string(row.get(columns["артикул"]))
            name = _string(row.get(columns["наименование"]))
            if not article and not name:
                continue

            currency = _string(row.get(columns["валюта"]))
            if currency:
                currency = currency.upper()

            item = {
                "article": article,
                "name": name,
                "collection": _string(row.get(columns["коллекция"])),
                "status": _string(row.get(columns["статус"])),
                "multiplicity": _string(row.get(columns["кратность"])),
                "brand_country": _string(row.get(columns["бренд (страна)"])),
                "unit": _string(row.get(columns["ед."])),
                "currency": currency,
                "price_rrc": _number_or_error(row.get(columns["ррц"]), "РРЦ"),
                "price_opt": _number_or_error(row.get(columns["оптовая"]), "Оптовая"),
                "image_url": None,
            }
            items.append(item)

        logger.info(f"Получено валидных записей: {len(items)}")

        return items
    except Exception as exc:  # noqa: BLE001
        logger.error("Ошибка импорта каталога фурнитуры", exc_info=True)
        raise Exception(f"Ошибка при импорте каталога фурнитуры: {exc}") from exc


# ---------------------------------- парсинг остатков ----------------------------------

def parse_hardware_stock_msk(stream: SourceType) -> list[dict]:
    """Парсит остатки фурнитуры для Москвы."""

    try:
        table_type = "stock_hardware_msk"
        rows = _load_rows(stream)
        if not rows:
            return []

        city = "msk"
        logger.info("Импорт %s для города %s", table_type, city)

        required_titles = [
            "Код товара",
            "Вид номенклатуры",
            "Тип номенклатуры",
            "Артикул",
            "Номенклатура",
            "Программа",
            "Наличие",
            "Ед.",
            "Доп. инфо.",
            "Дата прихода",
        ]
        optional_reserved = "Резерв"

        header_index = None
        columns: dict[str, str] = {}
        header_row: list[object] | None = None
        for idx, row in enumerate(rows):
            temp_columns = {_normalize_header(val): val for val in row}
            try:
                _ensure_columns(temp_columns, required_titles)
                header_index = idx
                columns = temp_columns
                header_row = row
                break
            except Exception:
                continue

        if header_index is None or header_row is None:
            temp_columns = {_normalize_header(val): val for val in rows[0]}
            _ensure_columns(temp_columns, required_titles)
            header_index = 0
            header_row = rows[0]
            columns = temp_columns

        headers = [(_string(val) or "").strip() for val in header_row]
        _validate_headers(table_type, headers)

        data_rows = rows[header_index + 1 :]
        df = pd.DataFrame(data_rows, columns=header_row)
        df = df.dropna(how="all")

        article_map, name_map = _load_catalog_index("hardware_catalog")
        reserved_idx = columns.get(_normalize_header(optional_reserved))

        items: list[dict] = []
        for _, row in df.iterrows():
            name = _string(row.get(columns["номенклатура"]))
            article = _string(row.get(columns["артикул"]))
            quantity = _number_or_error(row.get(columns["наличие"]), "Наличие")
            unit = _string(row.get(columns["ед."]))
            additional_info = _string(row.get(columns["доп. инфо."]))
            arrival_date = _string(row.get(columns["дата прихода"]))

            if not name and not article:
                logger.warning("Запись пропущена: нет артикула и наименования")
                continue

            catalog_id = _find_catalog_id(article, name, article_map, name_map)

            item = {
                "catalog_id": catalog_id,
                "name": name,
                "article": article,
                "quantity": quantity,
                "free_quantity": None,
                "unit": unit,
                "arrival_date": arrival_date,
                "reserved": _string(row.get(reserved_idx)) if reserved_idx is not None else None,
                "additional_info": additional_info,
            }
            items.append(item)

        logger.info("[IMPORT DONE] Type=%s City=%s Items=%s", table_type, city, len(items))

        return items
    except Exception as exc:  # noqa: BLE001
        logger.error("Ошибка импорта остатков фурнитуры (Москва)", exc_info=True)
        raise Exception(f"Ошибка при импорте остатков фурнитуры Москва: {exc}") from exc


def parse_hardware_stock_spb(stream: SourceType) -> list[dict]:
    """Парсит остатки фурнитуры для Санкт-Петербурга."""

    try:
        table_type = "stock_hardware_spb"
        rows = _load_rows(stream)
        if not rows:
            return []

        city = "spb"
        logger.info("Импорт %s для города %s", table_type, city)

        base_headers = ["Номенклатура", "Остаток", "Свободный остаток"]

        header_index = None
        main_header: list[object] | None = None
        sub_header: list[object] | None = None
        for idx, row in enumerate(rows):
            normalized = [_normalize_header(val) for val in row]
            if all(_normalize_header(title) in normalized for title in base_headers):
                header_index = idx
                main_header = row
                if idx + 1 < len(rows):
                    sub_header = rows[idx + 1]
                break

        if header_index is None or main_header is None:
            raise Exception("Ошибка: структура таблицы остатков фурнитуры СПБ не распознана.")

        max_len = max(len(main_header), len(sub_header or []))
        combined_headers: list[object] = []
        for i in range(max_len):
            top = main_header[i] if i < len(main_header) else None
            bottom = sub_header[i] if sub_header and i < len(sub_header) else None
            top_str = _string(top)
            bottom_str = _string(bottom)

            if bottom_str:
                combined = f"{top_str or ''} ({bottom_str})".strip()
            else:
                combined = top_str or None
            combined_headers.append(combined)

        normalized_headers = {
            _normalize_header(val): val
            for val in combined_headers
            if val is not None
        }

        headers: list[str] = []
        for value in combined_headers:
            normalized = _normalize_header(value)
            if normalized == _normalize_header("Номенклатура"):
                headers.append("Номенклатура")
            elif normalized in {
                _normalize_header("Остаток (В ед. хранения)"),
                _normalize_header("Остаток"),
            }:
                headers.append("Остаток")
            elif normalized in {
                _normalize_header("Свободный остаток (В ед. хранения)"),
                _normalize_header("Свободный остаток"),
            }:
                headers.append("Свободный остаток")

        _validate_headers(table_type, headers)

        data_rows = rows[(header_index + 2 if sub_header else header_index + 1) :]
        df = pd.DataFrame(data_rows, columns=combined_headers)
        df = df.dropna(how="all")

        article_map, name_map = _load_catalog_index("hardware_catalog")

        items: list[dict] = []
        for _, row in df.iterrows():
            name = _string(row.get(normalized_headers[_normalize_header("Номенклатура")]))
            if not name:
                logger.warning("Запись пропущена: нет наименования")
                continue

            quantity = _number_or_error(
                row.get(
                    normalized_headers[
                        _normalize_header("Остаток (В ед. хранения)")
                    ]
                ),
                "Остаток (В ед. хранения)",
            )
            free_quantity = _number_or_error(
                row.get(
                    normalized_headers[
                        _normalize_header("Свободный остаток (В ед. хранения)")
                    ]
                ),
                "Свободный остаток (В ед. хранения)",
            )

            catalog_id = _find_catalog_id(None, name, article_map, name_map)

            item = {
                "catalog_id": catalog_id,
                "name": name,
                "article": None,
                "quantity": quantity,
                "free_quantity": free_quantity,
                "unit": "ед. хранения",
                "arrival_date": None,
                "reserved": None,
                "additional_info": None,
                "city": "spb",
                "section": "hardware",
            }
            items.append(item)

        logger.info("[IMPORT DONE] Type=%s City=%s Items=%s", table_type, city, len(items))

        return items
    except Exception as exc:  # noqa: BLE001
        logger.error("Ошибка импорта остатков фурнитуры (СПБ)", exc_info=True)
        raise Exception(f"Ошибка при импорте остатков фурнитуры СПБ: {exc}") from exc


def parse_fabrics_stock_msk(stream: SourceType) -> list[dict]:
    """Парсит остатки тканей для Москвы."""

    try:
        table_type = "stock_fabrics_msk"
        rows = _load_rows(stream)
        if not rows:
            return []

        city = "msk"
        logger.info("Импорт %s для города %s", table_type, city)

        required_titles = [
            "Код товара",
            "Вид номенклатуры",
            "Тип номенклатуры",
            "Артикул",
            "Номенклатура",
            "Программа",
            "Наличие",
            "Ед.",
            "Доп. инфо.",
            "Дата прихода",
        ]

        header_index = None
        columns: dict[str, str] = {}
        header_row: list[object] | None = None
        for idx, row in enumerate(rows):
            temp_columns = {_normalize_header(val): val for val in row}
            try:
                _ensure_columns(temp_columns, required_titles)
                header_index = idx
                columns = temp_columns
                header_row = row
                break
            except Exception:
                continue

        if header_index is None or header_row is None:
            temp_columns = {_normalize_header(val): val for val in rows[0]}
            _ensure_columns(temp_columns, required_titles)
            header_index = 0
            header_row = rows[0]
            columns = temp_columns

        headers = [(_string(val) or "").strip() for val in header_row]
        _validate_headers(table_type, headers)

        data_rows = rows[header_index + 1 :]
        df = pd.DataFrame(data_rows, columns=header_row)
        df = df.dropna(how="all")

        items: list[dict] = []
        for _, row in df.iterrows():
            name = _string(row.get(columns["номенклатура"]))
            article = _string(row.get(columns["артикул"]))
            if not name and not article:
                logger.warning("Запись пропущена: нет артикула и наименования")
                continue

            quantity = _number_or_error(row.get(columns["наличие"]), "Наличие")
            unit = _string(row.get(columns["ед."]))
            status = _string(row.get(columns["доп. инфо."]))
            category = _string(row.get(columns["вид номенклатуры"]))

            if quantity is None:
                logger.warning("Запись пропущена: не указано количество")
                continue

            item = {
                "city": "msk",
                "section": "fabrics",
                "category": category,
                "article": article,
                "name": name,
                "quantity": quantity,
                "unit": unit,
                "status": status,
            }
            items.append(item)

        logger.info("[IMPORT DONE] Type=%s City=%s Items=%s", table_type, city, len(items))

        return items
    except Exception as exc:  # noqa: BLE001
        logger.error("Ошибка импорта остатков тканей (Москва)", exc_info=True)
        raise Exception(f"Ошибка при импорте остатков тканей Москва: {exc}") from exc


def parse_fabrics_stock_spb(stream: SourceType) -> list[dict]:
    """Парсит остатки тканей для Санкт-Петербурга."""

    try:
        table_type = "stock_fabrics_spb"
        rows = _load_rows(stream)
        if not rows:
            return []

        city = "spb"
        logger.info("Импорт %s для города %s", table_type, city)

        base_headers = ["Номенклатура", "Остаток", "Свободный остаток"]

        header_index = None
        main_header: list[object] | None = None
        sub_header: list[object] | None = None
        for idx, row in enumerate(rows):
            normalized = [_normalize_header(val) for val in row]
            if all(_normalize_header(title) in normalized for title in base_headers):
                header_index = idx
                main_header = row
                if idx + 1 < len(rows):
                    sub_header = rows[idx + 1]
                break

        if header_index is None or main_header is None:
            raise Exception(
                "Ошибка: структура таблицы остатков тканей СПБ не распознана.\n"
                "Требуемые колонки: Номенклатура, Остаток, Свободный остаток."
            )

        max_len = max(len(main_header), len(sub_header or []))
        combined_headers: list[object] = []
        for i in range(max_len):
            top = main_header[i] if i < len(main_header) else None
            bottom = sub_header[i] if sub_header and i < len(sub_header) else None
            top_str = _string(top)
            bottom_str = _string(bottom)

            if bottom_str:
                combined = f"{top_str or ''} ({bottom_str})".strip()
            else:
                combined = top_str or None
            combined_headers.append(combined)

        normalized_headers = {_normalize_header(val): val for val in combined_headers}

        headers: list[str] = []
        for value in combined_headers:
            normalized = _normalize_header(value)
            if normalized == _normalize_header("Номенклатура"):
                headers.append("Номенклатура")
            elif normalized in {
                _normalize_header("Остаток (В ед. хранения)"),
                _normalize_header("Остаток"),
            }:
                headers.append("Остаток")
            elif normalized in {
                _normalize_header("Свободный остаток (В ед. хранения)"),
                _normalize_header("Свободный остаток"),
            }:
                headers.append("Свободный остаток")

        _validate_headers(table_type, headers)

        data_rows = rows[(header_index + 2 if sub_header else header_index + 1) :]
        df = pd.DataFrame(data_rows, columns=combined_headers)
        df = df.dropna(how="all")

        items: list[dict] = []
        for _, row in df.iterrows():
            name = _string(row.get(normalized_headers[_normalize_header("Номенклатура")]))
            if not name:
                logger.warning("Запись пропущена: нет наименования")
                continue

            quantity = _number_or_error(
                row.get(
                    normalized_headers[
                        _normalize_header("Остаток (В ед. хранения)")
                    ]
                ),
                "Остаток (В ед. хранения)",
            )

            if quantity is None:
                logger.warning("Запись пропущена: не указано количество")
                continue

            item = {
                "city": "spb",
                "section": "fabrics",
                "article": None,
                "category": None,
                "name": name,
                "quantity": quantity,
                "unit": "ед. хранения",
                "status": None,
            }
            items.append(item)

        logger.info("[IMPORT DONE] Type=%s City=%s Items=%s", table_type, city, len(items))

        return items
    except Exception as exc:  # noqa: BLE001
        logger.error("Ошибка импорта остатков тканей (СПБ)", exc_info=True)
        raise Exception(f"Ошибка при импорте остатков тканей СПБ: {exc}") from exc


def parse_fabrics(stream: SourceType, city: str | None = None, section: str | None = None):
    """Совместимость со старым API: возвращает каталог тканей."""

    return parse_fabrics_catalog(stream)


def parse_hardware(stream: SourceType, city: str | None = None, section: str | None = None):
    """Совместимость со старым API: возвращает каталог фурнитуры."""

    return parse_hardware_catalog(stream)


def parse_stock(stream: SourceType, city: str | None = None, section: str | None = None):
    """Заглушка для остатков: требует явного указания раздела."""

    if section is None:
        raise Exception(
            "Укажите раздел остатков (fabrics/hardware) для импорта."
        )

    normalized = (section or "").lower()
    if normalized == "fabrics":
        if city == "msk":
            return parse_fabrics_stock_msk(stream)
        return parse_fabrics_stock_spb(stream)

    if normalized == "hardware":
        if city == "msk":
            return parse_hardware_stock_msk(stream)
        return parse_hardware_stock_spb(stream)

    raise Exception("Неизвестный раздел остатков. Ожидается fabrics или hardware.")


__all__ = [
    "parse_fabrics_catalog",
    "parse_hardware_catalog",
    "parse_fabrics_stock_spb",
    "parse_fabrics_stock_msk",
    "parse_hardware_stock_spb",
    "parse_hardware_stock_msk",
    "parse_fabrics",
    "parse_hardware",
    "parse_stock",
    "_string",
    "_number",
    "_number_or_error",
    "SchemaMismatchError",
    "TABLE_SCHEMAS",
]
